"""This module contains the model, view, and controller for the recording
selector."""

import pickle
import shelve
import unicodedata
import xml.sax.saxutils
from bisect import insort_left
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import NamedTuple

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject, Pango

from . import genre_button
from common.config import config
from common.connector import register_connect_request
from common.constants import SHORT, LONG
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.genrespec import genre_spec
from common.utilities import debug
from common.utilities import playable_tracks
from contextlib import contextmanager
from widgets import control_panel

# Disconnecting the model before performing operations on the model
# such as clear or multiple appends (populate) expedites these operations.
@contextmanager
def no_model(view):
    # Setting the model to None clears the sort indicator settings and
    # selections. Save them before disconnecting the model so that they
    # can be restored after restoring the model.
    columns = view.get_columns()
    sort_indicators = [column.get_sort_indicator() for column in columns]

    model, treeiter = view.selection.get_selected()
    if treeiter is not None:
        _, uuid, work_num = model[treeiter]

    with stop_emission(view.selection, 'changed'):
        view.set_model(None)

    yield

    with stop_emission(view.selection, 'changed'):
        view.set_model(model)

    # Restore sort indicator settings.
    for column, setting in zip(columns, sort_indicators):
        column.set_sort_indicator(setting)

    # Restore selection.
    if treeiter is not None:
        for row in model:
            _, row_uuid, row_work_num = row
            if (row_uuid, row_work_num) == (uuid, work_num):
                treepath = model.get_path(row.iter)
                with stop_emission(view.selection, 'changed'):
                    view.selection.select_path(treepath)
                view.scroll_to_cell(treepath, None, True, 0.5, 0.0)
                break

class RecordingSelector:
    def __init__(self):
        self.model = RecordingModel()
        self.model.connect('row-inserted', self.on_row_inserted)
        self.model.connect('row-deleted', self.on_row_deleted)

        self.view = RecordingView(self.model.model_filter)
        self.view.connect('button-press-event', self.on_button_press_event)
        self.view.selection.connect('changed', self.on_selection_changed)

        genre_button.connect('genre-changed', self.on_genre_changed)

        register_connect_request('play-notebook', 'page', self.on_page)

    def on_row_inserted(self, model, path, treeiter):
        # If the model is now not empty, enable drag from the header button.
        columns = self.view.get_columns()
        if len(model) == 1 and len(columns) > 1:
            for col in columns:
                header_button = col.get_button()
                header_button.drag_source_set(
                        Gdk.ModifierType.BUTTON1_MASK,
                        [Gtk.TargetEntry.new(
                                'column',
                                Gtk.TargetFlags.SAME_APP,
                                0)],
                        Gdk.DragAction.COPY)

    def on_row_deleted(self, model, path):
        # If the model is now empty, disable drag from the header button.
        if not len(model):
            for col in self.view.get_columns():
                header_button = col.get_button()
                header_button.drag_source_set(0, [], 0)

    def on_page(self, playnotebook, up):
        model, treeiter = self.view.selection.get_selected()
        treepath = model.get_path(treeiter)
        direction = ('next', 'prev')[up]
        getattr(treepath, direction)()
        self.view.selection.select_path(treepath)

    @emission_stopper('changed')
    def on_selection_changed(self, selection):
        # If I ever use stop_emission on this signal, then this handler will
        # assure suppression of the signal because it will be called before
        # any other handler. Normally I would use do_selection_changed and
        # connect_after, but TreeView creates the TreeSelection, so I cannot
        # subclass TreeSelection to override the default signal handler.
        #
        # Note that this handler is triggered only when the user changes the
        # recording selection directly. The recording selection also gets
        # set from set_selection when the playqueue selection, the incremental
        # search, or the sibling search selection changes, but from a
        # stop_emission context, so this handler does not get triggered then.
        model_filter, treeiter = selection.get_selected()
        treeiter = self.model.convert_iter_to_child_iter(treeiter)
        self.model.read_long_metadata(treeiter)

    # Double-click switches to play mode.
    def on_button_press_event(self, treeview, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 1:
            x, y = (int(event.x), int(event.y))
            path_t = self.view.get_path_at_pos(x, y)

            # It is hard to see how it would be possible to double-click in
            # the recording list without selecting a recording (a single-
            # click), but play it safe and confirm that there is a selection
            # before switching to play mode.
            if path_t is not None:
                control_panel.set_mode('Play')

    def on_genre_changed(self, genre_button, genre):
        self.populate_short_metadata(genre)

    def populate_short_metadata(self, genre):
        self.model.genre = genre
        primary_keys = config.genre_spec[genre]['primary']
        self.view.create_rec_treeview(genre, primary_keys)
        self.view.set_column_visibility(genre)

        sort_column = self.view.restore_sort_indicators(genre)
        with no_model(self.view):
            self.model.load_sorted_data(sort_column)

    # Called from selector.update_filter_button_menus when updating filter
    # button menus.
    def update_filter_button_menus(self, filterbuttonbox):
        model_filter, treeiter = self.view.selection.get_selected()

        # Hide all the buttons to deactivate filtering.
        visible_buttons = list(filterbuttonbox)
        for button in visible_buttons:
            button.hide()

        model, treeiter = self.view.selection.get_selected()
        with no_model(self.view):
            self.model.model_filter.refilter()

            # Unhide each button successively to introduce successive stages
            # of filtering.
            for button in visible_buttons:
                column_data = self.model.get_column_data(button.index)
                if button.label not in column_data:
                    button.label = column_data[0]
                button.show()
                button.update_menu(column_data)
                self.model.model_filter.refilter()

    # Called from selector.finish_on_genre_changed.
    def refilter(self):
        with no_model(self.view):
            self.model.model_filter.refilter()

# The first item is a list of tuples of strings. Each tuple corresponds to
# a column of the view. The number of columns varies, hence the need for a
# list (rather than a tuple per column). Tuples can contain multiple values
# to support name groups.
class RecordingModelRow(NamedTuple):
    short: object   # ((tuple(str, ...))) (short primary metadata)
    uuid: str
    work_num: int

class RecordingModel(Gtk.ListStore):
    def __init__(self):
        _types = RecordingModelRow.__annotations__.values()
        super().__init__(*_types)

        # recordingmodel gets wrapped in a treemodelfilter.
        self.model_filter = self.filter_new()

        self.recording = None
        self.work_num = 0

        # clicked_column_id is the index of the column that was clicked for
        # sorting. The sort_column_id is always 0; clicked_column_id is the
        # index into the tuple of short metadata values that resides in column
        # 0 of the model.
        self.clicked_column_id = 0

    def convert_iter_to_child_iter(self, treeiter):
        if treeiter is None:
            return None
        treeiter = self.model_filter.convert_iter_to_child_iter(treeiter)
        return treeiter

    def convert_child_iter_to_iter(self, treeiter):
        if treeiter is None:
            return None
        v, treeiter = self.model_filter.convert_child_iter_to_iter(treeiter)
        if not v:
            raise ValueError('convert_child_iter_to_iter failed')
        return treeiter

    # set_visible_func is a closure that provides filterbuttonbox to
    # visible_func
    def set_visible_func(self, filterbuttonbox):
        def visible_func(model, treeiter, *data):
            recording_model_row = RecordingModelRow._make(model[treeiter])

            # name_groups is a list of tuples of names (one for each column).
            name_groups = recording_model_row.short
            return all((button.label in name_groups[button.index])
                    for button in filterbuttonbox)
        self.model_filter.set_visible_func(visible_func)

    def sort_key(self, row):
        def get_sort_t(row, column_index):
            metadata_short = row[0]
            val_tuple = metadata_short[column_index]

            # Sort name groups using the first name.
            val = val_tuple[0]

            # Extract any numeric element and make it the second component
            # of the tuple used in the comparison.
            val_split = val.split()
            val_str = [unicodedata.normalize('NFKD', v.lower())
                    for v in val_split if not v.isdigit()]
            val_num = [int(v) for v in val_split if v.isdigit()]
            return (val_str, val_num)

        primary_keys = config.genre_spec[self.genre]['primary']
        n_cols = len(primary_keys)

        # Create a list of column indexes with clicked_column_id first (or
        # the id of the last column if clicked_column_id is too high).
        column_indexes = list(range(n_cols))
        column_indexes.insert(0, column_indexes.pop(self.clicked_column_id))

        return [get_sort_t(row, i) for i in column_indexes]

    def yield_short_data(self, genre):
        short_path = Path(SHORT, genre)
        with open(short_path, 'rb') as fo:
            while True:
                try:
                    yield pickle.load(fo)
                except EOFError:
                    return

    def load_sorted_data(self, column_id):
        self.clicked_column_id = column_id

        short_data = list(self.yield_short_data(self.genre))
        short_data.sort(key=self.sort_key)

        self.clear()
        for row in short_data:
            self.append(row)

    def get_column_data(self, index):
        short_values = (v for row in self.model_filter
                for v in RecordingModelRow._make(row).short[index])
        def make_key(val):
            # Extract any numeric element and make it the second component of
            # the tuple used in the comparison.
            val_split = val.split()
            val_str = [unicodedata.normalize('NFKD', v.lower())
                    for v in val_split if not v.isdigit()]
            val_num = [int(v) for v in val_split if v.isdigit()]
            return (val_str, val_num)
        short_values_sorted = sorted(short_values, key=make_key)
        column_data = [k for k, g in groupby(short_values_sorted)]
        return column_data

    # Used when saving a new recording.
    def insert_short(self, work_short, uuid, work_num):
        new_row = RecordingModelRow(work_short, uuid, work_num)
        insort_left(self, new_row, key=self.sort_key)

    # Called from view when selection changes and from selector when
    # playqueue_select selection changes.
    def read_long_metadata(self, treeiter):
        if treeiter is None:
            self.recording = None
        else:
            # Read just the entry we need before closing the shelf because
            # editnotebook might need to write to the shelf.
            row = RecordingModelRow._make(self[treeiter])
            with shelve.open(LONG, 'r') as recording_shelf:
                self.recording = recording = recording_shelf[row.uuid]
            self.work = work = recording.works[row.work_num]
            self.work_num = row.work_num

            # recording.tracks is a list of all tracks. Pull out the ones
            # in the current work in the order specified by work.track_ids.
            self.tracks_playable = playable_tracks(recording.tracks,
                    work.track_ids)

            # self.work.metadata is [(val1, ...), ...], whereas
            # self.metadata is [(key, (val1, ...)), ...].
            keys = genre_spec.all_keys(self.genre)
            self.metadata = list(zip(keys, work.metadata))

    def set_recording(self, recording, work_num):
        self.recording = recording
        self.work = recording.works[work_num]
        self.work_num = work_num
        self.tracks_playable = playable_tracks(recording.tracks,
                self.work.track_ids)
        keys = genre_spec.all_keys(self.genre)
        self.metadata = list(zip(keys, recording.works[work_num].metadata))

    def update_work_props(self):
        props_d = dict(self.work.props)

        times_played, = props_d['times played']
        if not times_played:
            times_played = 0
        props_d['times played'] = (str(int(times_played) + 1),)

        now = datetime.now()
        date_played = now.strftime("%Y %b %d")
        props_d['date played'] = (date_played,)

        new_props = list(props_d.items())
        new_work = self.work._replace(props=new_props)
        self.recording.works[self.work_num] = self.work = new_work

        with shelve.open(LONG, 'w') as recording_shelf:
            recording_shelf[self.recording.uuid] = self.recording

class RecordingView(Gtk.TreeView):
    @GObject.Signal
    def column_widths_changed(self, widths: object):
        pass

    def __init__(self, model_filter):
        super().__init__()
        self.set_name('recording-view')
        self.set_model(model_filter)
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.column_pool = []
        self.selection = self.get_selection()

        self.cell = Gtk.CellRendererText()
        self.cell.set_property('ellipsize', Pango.EllipsizeMode.END)

        # Note that get_model on the RecordingView returns model_filter,
        # not model. Likewise, get_selected on the selection returns
        # model_filter. And vice versa: When making a selection, the
        # treeiter must be converted to the model_filter.
        self.model = model_filter.props.child_model

    def do_get_preferred_width(self):
        # This override prevents a column from expanding the TreeView. It
        # does not seem to matter what value I put here.
        minimum_width = natural_width = 100
        return (minimum_width, natural_width)

    def do_button_release_event(self, event):
        if self._column_widths_changing:
            self._column_widths_changing = False

            widths = self.get_column_widths()
            self.emit('column-widths-changed', widths)

    def on_filter_button_created(self, filterbuttonbox, button):
        # If there is a selection, configure the new filter button to
        # preserve the selection.
        model_filter, treeiter = self.selection.get_selected()
        if treeiter is not None:
            short, uuid, work_num = model_filter[treeiter]
            selected_short, = zip(*short)
            button.label = selected_short[button.index]

    def on_filter_button_deactivated(self, filterbuttonbox, column_index):
        columns = self.get_columns()
        column = columns[column_index]
        column.set_visible(True)

        fixed_width = sum(column.get_fixed_width() for column in columns[:-1])
        allocation = self.get_allocation()
        if fixed_width + 20 > allocation.width:
            for col in columns:
                col.set_fixed_width(-1)
        self.queue_resize()

        # If there is a selection, scroll it into view.
        model_filter, treeiter = self.selection.get_selected()
        if treeiter is not None:
            treepath = model_filter.get_path(treeiter)
            self.scroll_to_cell(treepath, None, True, 0.5, 0.0)

    def create_rec_treeview(self, genre, primarykeys):
        # Adjust the number of columns for the new genre by creating missing
        # columns or removing excess ones. Put removed columns in a pool so
        # that they can be reused when needed.
        ncols = len(primarykeys)
        for col_index in range(len(self.get_columns()), ncols):
            # First try to pull additional columns from the pool. If there
            # are no columns in the pool, create one.
            try:
                col = self.column_pool.pop()
            except IndexError:
                col = self.make_column()
            self.append_column(col)

        # Remove excess columns and put them in the pool.
        for col in self.get_columns()[ncols:]:
            self.remove_column(col)
            self.column_pool.append(col)

        # Get column widths.
        default_widths = [80] * ncols
        widths = config.column_widths.get(genre, default_widths)

        # Now set the properties of all the columns.
        for col, k, w in zip(self.get_columns(), primarykeys, widths):
            k = xml.sax.saxutils.escape(str(k))  # escape &, <, and >
            label = col.get_widget()
            label.set_markup(f"<span style='italic'>{k}</span>")
            col.set_fixed_width(w)
        col.set_fixed_width(-1)

    def make_column(self):
        lab = Gtk.Label()
        lab.set_use_markup(True)
        lab.show()
        col = Gtk.TreeViewColumn.new()
        col.pack_start(self.cell, True)
        col.set_cell_data_func(self.cell, self.rec_cell_data_func)
        col.set_widget(lab)
        col.set_clickable(True)
        col.set_resizable(True)
        col.connect('clicked', self.on_column_clicked)
        col.connect('notify::width', self.on_column_width)

        # Start with drag disabled. It will be enabled when the first work
        # gets added to the model.
        header_button = col.get_button()
        header_button.drag_source_set(0, [], 0)
        header_button.connect('drag-data-get',
                self.on_header_button_drag_data_get, col)
        header_button.connect('drag-begin',
                self.on_header_button_drag_begin)
        return col

    def rec_cell_data_func(self, column, cell, model, listiter, arg):
        # Column 0 contains the recording.  Thus, we obtain the value by
        # indexing on the metadata key, which is available as the title of
        # the column.
        values = model.get_value(listiter, 0)
        columns = self.get_columns()
        col_index = columns.index(column)
        value = values[col_index]
        cell.props.text = '\n'.join(value)

    def on_column_clicked(self, column):
        columns = self.get_columns()
        column_index = columns.index(column)
        for col in columns:
            col.set_sort_indicator(False)
        columns[column_index].set_sort_indicator(True)

        # Update config.
        sort_indicators_settings = [False] * len(columns)
        sort_indicators_settings[column_index] = True
        with config.modify('sort indicators') as sort_indicators:
            sort_indicators[self.model.genre] = sort_indicators_settings

        with no_model(self):
            self.model.load_sorted_data(column_index)

    # When any column changes width, set a flag. Send the signal when the
    # user releases the mouse button.
    def on_column_width(self, column, paramspec):
        self._column_widths_changing = True

    def get_column_widths(self):
        # If the column never appeared (it was always represented by a filter
        # button) then its width will be 0. Use its fixed width -- which was
        # initialized to the value in config -- instead.
        return [(col.props.width or col.get_fixed_width())
                for col in self.get_columns()]

    # Use a snapshot of the column button as the drag icon.
    def on_header_button_drag_begin(self, button, context):
        win = button.get_event_window()
        width = win.get_width()
        height = win.get_height()
        pb = Gdk.pixbuf_get_from_window(win, 0, 0, width, height)
        Gtk.drag_set_icon_pixbuf(context, pb, 0, 0)

    # The cargo for the drag is the index of the column. Take the first
    # name in name groups.
    def on_header_button_drag_data_get(self, button, drag_context, data,
            info, time, column):
        columns = self.get_columns()
        index = columns.index(column)
        data.set(data.get_selection(), 8, pickle.dumps(index))

        # If the column we just hid has the sort indicator, 'click' on the
        # next column. If this column was the last one, then 'click' on the
        # first column.
        if column.get_sort_indicator():
            next_column = columns[(index + 1) % len(columns)]
            next_column.emit('clicked')
        column.set_visible(False)

    def set_column_visibility(self, genre):
        columns = self.get_columns()
        for column in columns:
            column.set_visible(True)

        # Hide the columns configured as filter buttons.
        for index in config.filter_config[genre]:
            columns[index].set_visible(False)

    # Restore sort indicators to settings stored in config.
    def restore_sort_indicators(self, genre):
        columns = self.get_columns()
        sort_indicators_settings = config.sort_indicators[genre]
        for column, sort in zip(columns, sort_indicators_settings):
            column.set_sort_indicator(sort)
        return sort_indicators_settings.index(True)

    def clear_first_row_selection(self):
        # Hack to prevent the first row from being selected if the user
        # resizes a column immediately after starting wax.
        self.set_cursor('0', None, False)
        self.selection.unselect_all()

