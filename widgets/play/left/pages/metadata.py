"""This module displays long metadata, progress bars, and controls."""

import itertools

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango

from common.connector import register_connect_request
from common.decorators import idle_add
from common.utilities import debug
from widgets.select.right import playqueue_model_with_attrs as playqueue_model
from widgets.select.right import select_right as playqueue_select
from widgets import control_panel

WIKIPEDIA_URL = 'https://en.wikipedia.org/wiki/special:search/'

@Gtk.Template.from_file('data/glade/play/metadata.glade')
class MetadataView(Gtk.Grid):
    __gtype_name__ = 'metadata_grid'

    metadata_treeview = Gtk.Template.Child()
    metadata_liststore = Gtk.Template.Child()
    metadata_key_treeviewcolumn = Gtk.Template.Child()
    metadata_value_treeviewcolumn = Gtk.Template.Child()
    metadata_value_cellrenderertext = Gtk.Template.Child()

    track_metadata_treeview = Gtk.Template.Child()
    track_metadata_liststore = Gtk.Template.Child()
    track_metadata_treeviewcolumn = Gtk.Template.Child()
    track_metadata_cellrenderertext = Gtk.Template.Child()

    track_next_button = Gtk.Template.Child()
    track_progressbar = Gtk.Template.Child()
    track_progressbar_eventbox = Gtk.Template.Child()
    track_time_button = Gtk.Template.Child()
    track_controls_box = Gtk.Template.Child()

    set_next_button = Gtk.Template.Child()
    set_progressbar = Gtk.Template.Child()
    set_time_button = Gtk.Template.Child()
    set_controls_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.tab_text = 'Metadata'
        self.set_name('play-metadata-page')
        self.track_next_button.set_name('track-next-button')
        self.tracktuple = None
        self.current_width = -1

        def func(column, cell, model, treeiter, user):
            val = model.get_value(treeiter, 1)
            val_str = '\n'.join(val)
            cell.set_property('text', val_str)
        treeviewcolumn = self.metadata_value_treeviewcolumn
        cellrenderertext = self.metadata_value_cellrenderertext
        treeviewcolumn.set_cell_data_func(cellrenderertext, func)

        cellrenderertext = self.track_metadata_cellrenderertext
        cellrenderertext.set_padding(0, 0)

        playqueue_model.connect('row-deleted',
                self.on_playqueue_model_row_deleted)
        playqueue_model.connect('row-inserted',
                self.on_playqueue_model_row_inserted)
        playqueue_model.connect('row-changed',
                self.on_playqueue_model_row_changed)

        playqueue_select.playqueue_treeselection.connect('changed',
                self.on_playqueue_select_selection_changed)

        register_connect_request('player', 'position',
                self.on_position)
        register_connect_request('player', 'track-started',
                self.on_track_started)
        register_connect_request('player', 'track-finished',
                self.on_track_finished)
        register_connect_request('player', 'set-ready',
                self.on_set_ready)

        self.initialize_track_time_func()
        self.initialize_set_time_func()

    @Gtk.Template.Callback()
    def on_metadata_treeview_size_allocate(self, treeview, alloc):
        if alloc.width != self.current_width:
            self.current_width = alloc.width
            col0_width = self.metadata_key_treeviewcolumn.get_width()

            # Change the wrap width when the treeview resizes.
            cellrenderertext = self.metadata_value_cellrenderertext
            cellrenderertext.props.wrap_width = alloc.width - col0_width - 8

            # After changing the wrap width, call columns_autosize to get the
            # columns to adjust the height of the rows. Note that the column
            # is set to fixed/280. If I turn this autosize off then there is
            # no wrapping. With automatic/280, same. With automatic/-1, the
            # column is wide enough to accommodate the entire string. With
            # fixed/-1, same. With expand off, no change. Only fixed/280
            # works (regardless of expand). Any number greater than -1
            # works in place of 280. I set it to 0.
            GLib.idle_add(treeview.columns_autosize)

    @Gtk.Template.Callback()
    def on_track_metadata_treeview_size_allocate(self, treeview, alloc):
        if alloc.width != self.current_width:
            self.current_width = alloc.width

            # Change the wrap width when the treeview resizes.
            cellrenderertext = self.track_metadata_cellrenderertext
            cellrenderertext.props.wrap_width = alloc.width - 8

            # As above, the column must be set to fixed/0.
            GLib.idle_add(treeview.columns_autosize)

    def on_playqueue_select_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is not None:
            playable = model[treeiter][9]
            path = model.get_path(treeiter)
            first_path = (path == Gtk.TreePath.new_first())
            controls_visible = first_path and playable
        else:
            first_path = controls_visible = False
        self.track_metadata_treeview.props.visible = controls_visible
        self.track_controls_box.props.visible = controls_visible
        self.set_controls_box.props.visible = first_path

    def on_playqueue_model_row_inserted(self, model, path, treeiter):
        self.set_next_button.props.sensitive = (len(model) > 1)

    def on_playqueue_model_row_deleted(self, model, path):
        self.track_metadata_liststore.clear()

        self.display_track_time(0.0, 0.0)
        self.track_progressbar.set_fraction(0.0)

        self.display_set_time(0.0)
        self.set_progressbar.set_fraction(0.0)

        self.track_metadata_treeview.hide()
        self.track_controls_box.hide()
        self.set_controls_box.hide()

        len_model = len(model)
        if len_model <= 1:
            self.set_next_button.set_sensitive(False)
        if len_model == 0 and control_panel.mode == 'Play':
            control_panel.set_mode('Select')

    @idle_add  # needs to run after track-finished
    def on_playqueue_model_row_changed(self, liststore, path, treeiter):
        if self.tracktuple is None:
            return

        # If the metadata in the first set changes, then update the display
        # of track metadata.
        treeiter_first = liststore.get_iter_first()
        if treeiter_first is None:
            return
        path_first = liststore.get_path(treeiter_first)
        if path_first.compare(path) == 0:
            trackid_map = {tracktuple.track_id: tracktuple
                    for tracktuple in playqueue_model[0].tracks}

            # Update metadata for the trackid that is currently displayed.
            self.playqueue_model_row = playqueue_model[0]
            trackid = self.tracktuple.track_id
            grouptuple = self.playqueue_model_row.group_map.get(trackid, None)
            tracktuple = trackid_map[trackid]
            self.update_track_metadata(tracktuple, grouptuple)

    def on_position(self, player,
            track_position: int, track_duration: int,
            set_position: int, set_duration: int):
        track_ratio = track_position / track_duration
        self.track_position = track_position
        self.track_duration = track_duration
        self.track_progressbar.set_fraction(track_ratio)
        self.display_track_time(track_position, track_duration)

        self.set_position = set_position
        self.set_duration = set_duration
        set_ratio = set_position / set_duration
        self.set_progressbar.set_fraction(set_ratio)
        self.display_set_time(set_position)

    def populate(self, metadata, nonce, uuid):
        model = self.metadata_liststore
        model.clear()

        # Play mode does not distinguish between permanent and nonce metadata
        # in its display.
        for entry in (metadata + nonce):
            # Ignore entries with no values.
            key, values = entry
            if any(values):
                model.append(entry)

    def update_track_metadata(self, tracktuple, grouptuple):
        self.track_metadata_liststore.clear()

        # There is only ever 1 value (no name groups), but the value
        # arrives in a tuple. The tuple makes the format of these metadata
        # consistent with the format of the work metadata. I do a join
        # to accommodate future enhancement.
        def joiner(v):
            return ', '.join(v)

        if grouptuple is not None:
            row = (grouptuple.title, False, Pango.Weight.BOLD, 9.5)
            self.track_metadata_liststore.append(row)

            metadata_strings = [f'{k}: {joiner(v)}'
                    for k, v in grouptuple.metadata]
            for metadata_string in metadata_strings:
                row = (metadata_string, True, Pango.Weight.NORMAL, 8.5)
                self.track_metadata_liststore.append(row)

        self.tracktuple = tracktuple
        row = (tracktuple.title, False, Pango.Weight.NORMAL, 9.5)
        self.track_metadata_liststore.append(row)

        metadata_strings = [(f'{k}: {joiner(v)}')
                for k, v in tracktuple.metadata]
        for metadata_string in metadata_strings:
            row = (metadata_string, True, Pango.Weight.NORMAL, 8.5)
            self.track_metadata_liststore.append(row)

    # -Track progress----------------------------------------------------------
    def on_track_started(self, player, tracktuple, grouptuple,
            track_duration, more_tracks, uuid):
        self.update_track_metadata(tracktuple, grouptuple)

        # Initialize progress display.
        self.track_position = 0.0
        self.track_duration = track_duration
        self.track_progressbar.set_fraction(0.0)
        self.display_track_time(0.0, self.track_duration)
        self.track_next_button.props.sensitive = more_tracks

    def on_track_finished(self, player, n_tracks, track_id, uuid, work_num):
        self.track_next_button.props.sensitive = bool(n_tracks)
        self.tracktuple = None

    def initialize_track_time_func(self):
        def remaining(pos, dur):
            return dur - pos
        def elapsed(pos, dur):
            return pos
        def total(pos, dur):
            return dur
        cycle = (remaining, elapsed, total)
        self.track_time_func_cycle = itertools.cycle(cycle)
        self.track_time_func = next(self.track_time_func_cycle)

    @Gtk.Template.Callback()
    def on_track_time_button_clicked(self, button):
        self.track_time_func = next(self.track_time_func_cycle)
        self.display_track_time(self.track_position, self.track_duration)

    def display_track_time(self, position, duration):
        label = self.seconds_to_str(self.track_time_func(position, duration))
        self.track_time_button.set_label(label)

    # -Set progress------------------------------------------------------------
    def on_set_ready(self, player, set_duration):
        self.set_duration = set_duration
        self.set_position = 0.0
        self.set_progressbar.set_fraction(0.0)
        self.display_set_time(0.0)

        self.set_next_button.props.sensitive = (len(playqueue_model) > 1)

        self.set_controls_box.show()

        # set_duration is 0 for the alert sound.
        self.track_metadata_treeview.props.visible = bool(set_duration)
        self.track_controls_box.props.visible = bool(set_duration)

    def initialize_set_time_func(self):
        def remaining(pos):
            return self.set_duration - pos
        def elapsed(pos):
            return pos
        def total(pos):
            return self.set_duration
        cycle = (remaining, elapsed, total)
        self.set_time_func_cycle = itertools.cycle(cycle)
        self.set_time_func = next(self.set_time_func_cycle)

    @Gtk.Template.Callback()
    def on_set_time_button_clicked(self, button):
        self.set_time_func = next(self.set_time_func_cycle)
        self.display_set_time(self.set_position)

    def display_set_time(self, position):
        label = self.seconds_to_str(self.set_time_func(position))
        self.set_time_button.set_label(label)

    def seconds_to_str(self, seconds):
        seconds = round(seconds)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        if hours:
            return f'{hours}:{minutes:02d}:{seconds:02d}'
        else:
            return f'{minutes:2d}:{seconds:02d}'


page_widget = MetadataView()

