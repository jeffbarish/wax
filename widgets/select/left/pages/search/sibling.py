"""Sibling search."""

import pickle
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GLib, GObject
from gi.repository.GdkPixbuf import Pixbuf

from common.config import config
from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import IMAGES, IMAGES_DIR
from common.contextmanagers import signal_blocker
from common.decorators import emission_stopper
from common.decorators import idle_add
from common.types import DragCargo, GroupTuple
from common.utilities import debug
from widgets.select.right import playqueue_model
from widgets import control_panel

@Gtk.Template.from_file('data/glade/select/search/sibling.glade')
class SearchSibling(Gtk.Box):
    __gtype_name__ = 'sibling_box'

    @GObject.Signal
    def selection_changed(self, genre: str, uuid: str, work_num: int,
            tracks: object):
        pass

    sibling_liststore = Gtk.Template.Child()
    sibling_treeviewcolumn_text = Gtk.Template.Child()
    sibling_cellrenderertext = Gtk.Template.Child()
    sibling_treeselection = Gtk.Template.Child()
    sibling_treeview = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('search-sibling')
        self.tab_text = 'Sibling'

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('search-incremental', 'selection-changed',
                self.on_search_incremental_selection_changed)
        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)
        register_connect_request('edit-left-notebook', 'work-deleted',
                self.on_work_deleted)
        register_connect_request('playqueue_select.playqueue_treeselection',
                'changed', self.on_playqueue_select_selection_changed)

        def func(column, cell, model, treeiter, val):
            work_num = model[treeiter][1]
            work = self.recording.works[work_num]
            work_long = work.metadata
            primary_keys = config.genre_spec[work.genre]['primary']
            primary_work_long = work_long[:len(primary_keys)]
            primary_metadata, = zip(*primary_work_long)
            primary_vals_str = '\n'.join(primary_metadata)
            cell.set_property('text', primary_vals_str)
        cell = self.sibling_cellrenderertext
        col = self.sibling_treeviewcolumn_text
        col.set_cell_data_func(cell, func)

        # Enable drag and drop from sibling view.
        target_flags = Gtk.TargetFlags.SAME_APP
        self.sibling_treeview.enable_model_drag_source(
                Gdk.ModifierType.BUTTON1_MASK,
                [Gtk.TargetEntry.new('recording', target_flags, 0)],
                Gdk.DragAction.COPY)
        self.sibling_treeview.connect('drag-data-get',
                self.on_sibling_treeview_drag_data_get)
        self.sibling_treeview.connect('button-press-event',
                self.on_button_press_event)

    def on_sibling_treeview_drag_data_get(self, treeview, context,
            data, info, time):
        model = getattr_from_obj_with_name('selector.recording_selector.model')
        tracks = [t for t in model.recording.tracks
                if t.track_id in model.work.track_ids]
        group_map = getattr_from_obj_with_name(
                'selector.track_selector.model.group_map')
        cargo = DragCargo(model.genre, model.work.metadata, tracks, group_map,
                model.recording.props, model.recording.uuid, model.work_num)
        data.set(data.get_selection(), 8, pickle.dumps(cargo))

    @Gtk.Template.Callback()
    def on_sibling_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return

        def finish():
            work_num = self.sibling_liststore[treeiter][1]
            work = self.recording.works[work_num]
            genre = work.genre
            uuid = self.recording.uuid
            tracks = [t for t in self.recording.tracks
                    if t.track_id in work.track_ids]

            self.emit('selection-changed', genre, uuid, work_num, tracks)
        GLib.idle_add(finish)

    @idle_add
    def on_search_incremental_selection_changed(self, searchincremental,
            genre, uuid, work_num, tracks):
        selector = getattr_from_obj_with_name('selector')
        GLib.idle_add(self.on_recording_selection_changed,
                selector.recording_selection)

    def on_button_press_event(self, treeview, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 1:
            x, y = (int(event.x), int(event.y))
            path_t = self.sibling_treeview.get_path_at_pos(x, y)

            # It is hard to see how it would be possible to double-click in
            # the sibling list without selecting a recording (a single-
            # click), but play it safe and confirm that there is a selection
            # before switching to play mode.
            if path_t is not None:
                control_panel.set_mode('Play')

    @idle_add
    def on_recording_selection_changed(self, recording_selection):
        model_filter, selected_row_iter = recording_selection.get_selected()
        if selected_row_iter is None:
            return

        def finish():
            recording_model = model_filter.props.child_model
            self.recording = recording = recording_model.recording

            with signal_blocker(self.sibling_treeselection, 'changed'):
                self.sibling_liststore.clear()

            if len(recording.works) > 1:
                # Every work has the same cover.
                uuid = recording.uuid
                filename = Path(IMAGES, uuid, 'thumbnail-00.jpg')
                if not filename.exists():
                    filename = Path(IMAGES_DIR, 'noimage_thumbnail.png')
                thumbnail_pb = Pixbuf.new_from_file(str(filename))

                # Sort works by the track id of the first track in each work.
                for work_num, work in sorted(recording.works.items(),
                        key=lambda t: t[1].track_ids[0]):
                    row = (thumbnail_pb, work_num)
                    treeiter = self.sibling_liststore.append(row)
                    if recording_model.work_num == work_num:
                        with signal_blocker(self.sibling_treeselection,
                                'changed'):
                            self.sibling_treeselection.select_iter(treeiter)
        # The recording model updates in response to selection changed, so
        # defer selecting until after that update completes.
        GLib.idle_add(finish)

    @emission_stopper()
    def on_playqueue_select_selection_changed(self, selection):
        selector = getattr_from_obj_with_name('selector')
        GLib.idle_add(self.on_recording_selection_changed,
                selector.recording_selection)

    # If a recording is saved, redo the search. If it is deleted, then it is
    # no longer selected, so the sibling search result is empty.
    def on_recording_saved(self, editnotebook, genre):
        selector = getattr_from_obj_with_name('selector')
        self.on_recording_selection_changed(selector.recording_selection)

    def on_work_deleted(self, editnotebook, genre, uuid, work_num):
        with signal_blocker(self.sibling_treeselection, 'changed'):
            self.sibling_liststore.clear()

    @Gtk.Template.Callback()
    def on_sibling_queue_all_button_clicked(self, button):
        model = getattr_from_obj_with_name('selector.recording_selector.model')

        row_iter = (row for row in self.sibling_liststore)
        def queue_item():
            try:
                thumbnail_pb, work_num = next(row_iter)
            except StopIteration:
                return False

            work = model.recording.works[work_num]
            primary_keys = config.genre_spec[work.genre]['primary']
            primary_work_long = work.metadata[:len(primary_keys)]
            primary_metadata, = zip(*primary_work_long)
            primary_vals_str = '\n'.join(primary_metadata)

            tracks = [t for t in model.recording.tracks
                    if t.track_id in work.track_ids]
            group_map = {t: GroupTuple(g_name, g_metadata)
                    for g_name, g_tracks, g_metadata in work.trackgroups
                        for t in g_tracks}

            new_queue_row = (thumbnail_pb, (primary_vals_str,),
                    tracks, group_map, work.genre, model.recording.uuid,
                    work_num, False, model.recording.props, True)
            playqueue_model.append(new_queue_row)
            return True

        queue_item()
        GLib.timeout_add(500, queue_item)


page_widget = SearchSibling()

