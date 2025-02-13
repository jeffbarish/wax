"""The view of the play queue that appears in select mode."""

import pickle
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from gi.repository.GdkPixbuf import Pixbuf

from common.config import config
from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.constants import IMAGES, IMAGES_DIR
from common.contextmanagers import signal_blocker
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.decorators import idle_add
from common.types import DragCargo, GroupTuple
from common.utilities import debug
from common.utilities import make_time_str
from common.utilities import playable_tracks
from widgets import options_button

from . import PlayqueueModelRow
from . import playqueue_model, playqueue_model_with_attrs


@Gtk.Template.from_file('data/glade/select/playqueue.glade')
class Playqueue(Gtk.Box):
    __gtype_name__ = 'playqueue_box'

    playqueue_treeview = Gtk.Template.Child()
    playqueue_treeselection = Gtk.Template.Child()
    playqueue_treeviewcolumn_text = Gtk.Template.Child()
    playqueue_cellrenderertext = Gtk.Template.Child()
    playqueue_item_duration_value = Gtk.Template.Child()
    playqueue_total_duration_value = Gtk.Template.Child()
    playqueue_durations_box = Gtk.Template.Child()
    playqueue_item_duration_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('playqueue_select')
        self.tab_text = 'Queue'
        self.playqueue_treeview.set_model(playqueue_model)
        self.set_can_focus(False)

        color = Gdk.RGBA()
        cell = self.playqueue_cellrenderertext
        def func(column, cell, model, treeiter, user):
            val = model.get_value(treeiter, 1)
            text = '\n'.join(val)
            cell.props.text = text

            playable = model.get_value(treeiter, 9)
            color.parse(('#dc143c', '#424242')[playable])
            cell.props.background_rgba = color
        col = self.playqueue_treeviewcolumn_text
        col.set_cell_data_func(cell, func)

        self.context_menu = context_menu = Gtk.Menu()
        menuitem = Gtk.MenuItem.new_with_label('Remove')
        menuitem.show()
        menuitem.connect('activate', self.on_remove_activated)
        context_menu.append(menuitem)
        context_menu.attach_to_widget(self.playqueue_treeview)

        # Restart appears only for the first set in the queue.
        menuitem = Gtk.MenuItem.new_with_label('Restart')
        menuitem.hide()
        menuitem.connect('activate', self.on_play_context_restart)
        context_menu.append(menuitem)
        self.restart_menuitem = menuitem

        menuitem = Gtk.CheckMenuItem.new_with_label('Random')
        menuitem.show()
        menuitem.connect('activate', self.on_random_activated)
        context_menu.append(menuitem)
        self.random_menuitem = menuitem

        target_flags = Gtk.TargetFlags.SAME_APP
        self.playqueue_treeview.enable_model_drag_dest(
                [Gtk.TargetEntry.new('recording', target_flags, 0)],
                Gdk.DragAction.COPY)
        self.playqueue_treeview.enable_model_drag_source(
                Gdk.ModifierType.BUTTON1_MASK,
                [Gtk.TargetEntry.new('recording', target_flags, 0)],
                Gdk.DragAction.MOVE)

        self.playqueue_treeselection.connect('changed',
                self.on_playqueue_select_selection_changed)
        playqueue_model.connect('row-inserted',
                self.on_playqueue_model_row_inserted)
        playqueue_model.connect('row-deleted',
                self.on_playqueue_model_row_deleted)

        register_connect_request('playqueue_play',
                'playqueue-play-selection-changed',
                self.on_playqueue_play_selection_changed)
        register_connect_request('player',
                'set-finished', self.on_set_finished)
        register_connect_request('player',
                'track-finished', self.on_track_finished)
        register_connect_request('play-metadata-page.set_next_button',
                'clicked', self.on_set_next_button_clicked)
        register_connect_request('genre-button.genre_menu',
                'selection-done', self.on_genre_menu_selection_done)
        register_connect_request('edit-left-notebook',
                'recording-saved', self.on_recording_saved)
        register_connect_request('edit-left-notebook',
                'work-deleted', self.on_work_deleted)
        register_connect_request('edit-left-notebook',
                'recording-deleted', self.on_recording_deleted)
        register_connect_request('search-incremental',
                'selection-changed',
                self.on_search_incremental_selection_changed)
        register_connect_request('selector.recording_selection',
                'changed', self.on_recording_selection_changed)
        register_connect_request('track-view.selection',
                'changed', self.on_track_selection_changed)

        options_button.connect_menuitem('Select', 'Remove set',
                self.on_options_select_remove_set)
        options_button.connect_menuitem('Select', 'Clear queue',
                self.on_options_select_clear_queue)

    def on_search_incremental_selection_changed(self, searchincremental,
            genre, uuid, work_num, tracks):
        for row in playqueue_model_with_attrs:
            if (row.uuid, row.work_num) == (uuid, work_num):
                with stop_emission(self.playqueue_treeselection, 'changed'):
                    self.playqueue_treeselection.select_iter(row.iter)
                break
        else:
            self.playqueue_treeselection.unselect_all()

    def on_options_select_remove_set(self, menuitem):
        self.on_remove_activated(menuitem)

    def on_options_select_clear_queue(self, menuitem):
        # When the first set in playqueue_model gets deleted,
        # player.on_playqueue_model_row_deleted prepares the next
        # set for playing. engine sends track-started when it is
        # ready to play the first track of the next set, but by
        # that time clear has already removed that set and
        # moved on. trackid_map gets out of sync with the trackids
        # that engine is sending, which results in a KeyError. To
        # avoid this problem, delete from the end of playqueue_model
        # so that player is never tempted to initiate play.
        with stop_emission(self.playqueue_treeselection, 'changed'), \
                stop_emission(playqueue_model, 'row-deleted'):
            for row in reversed(playqueue_model):
                playqueue_model.remove(row.iter)
        self.playqueue_durations_box.hide()

    def on_play_context_restart(self, menuitem):
        menuitem = options_button.get_menuitem('Play', 'Restart')
        menuitem.activate()

    def on_genre_menu_selection_done(self, menushell):
        # After changing genre, no recording is selected so we also clear
        # any playqueue selection.
        self.playqueue_treeselection.unselect_all()

    def on_playqueue_model_row_inserted(self, model, path, treeiter):
        self._display_item_duration(treeiter)
        self._display_total_duration()
        self.playqueue_durations_box.show_all()

    def on_playqueue_model_row_deleted(self, model, path):
        if len(model):
            self._display_total_duration()
            self.playqueue_durations_box.show_all()

            # Select the new first set.
            first_set = playqueue_model_with_attrs[0]
            self.playqueue_treeselection.select_iter(first_set.iter)
        else:
            self.playqueue_durations_box.hide()

    def on_random_activated(self, menuitem):
        state = menuitem.get_active()
        model, treeiter = self.playqueue_treeselection.get_selected()
        if treeiter is not None:
            row = playqueue_model_with_attrs[treeiter]
            row.random = state

    @emission_stopper()
    def on_playqueue_select_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is not None:
            self._display_item_duration(treeiter)
            self.playqueue_durations_box.show_all()
            with signal_blocker(self.random_menuitem, 'activate'):
                row = PlayqueueModelRow._make(model[treeiter])
                self.random_menuitem.set_active(row.random)
        else:
            self.playqueue_item_duration_box.hide()

    @Gtk.Template.Callback()
    def on_playqueue_treeview_button_press_event(self, treeview, event):
        if event.type == Gdk.EventType.BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 3:
            # Pop up the menu if we clicked on a row. Note that clicking on
            # the row selects it, so we can get the row in the handler for
            # the selection using get_selected.
            x, y = (int(event.x), int(event.y))
            path_t = self.playqueue_treeview.get_path_at_pos(x, y)
            if path_t is not None:
                # The Restart option appears only for the first set.
                path, column, cell_x, cell_y = path_t
                visible = (path == Gtk.TreePath.new_first())
                self.restart_menuitem.props.visible = visible

                row = playqueue_model_with_attrs[path]
                self.random_menuitem.set_active(row.random)

                self.context_menu.popup_at_pointer(event)
        elif event.type == Gdk.EventType._2BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 1:
            # Double-click switches to play mode.
            x, y = (int(event.x), int(event.y))
            path_t = self.playqueue_treeview.get_path_at_pos(x, y)
            if path_t is not None:
                getattr_from_obj_with_name('control-panel.set_mode')('Play')

    def on_set_next_button_clicked(self, button):
        self._remove_first_set()

    def on_set_finished(self, player):
        self._remove_first_set()

    def _remove_first_set(self):
        # This test is necessary because GStreamer is sending two
        # about-to-finish signals for ogg files. This test solves the
        # problem only when playqueue has a single set.
        first_path = Gtk.TreePath.new_first()
        if len(playqueue_model):
            first_treeiter = playqueue_model.get_iter(first_path)
            playqueue_model.remove(first_treeiter)

    def on_remove_activated(self, menuitem):
        model, treeiter = self.playqueue_treeselection.get_selected()
        playqueue_model.remove(treeiter)

    @Gtk.Template.Callback()
    def on_playqueue_treeview_drag_motion(self, treeview, context, x, y, time):
        # It is not permitted to drop a recording in front of the first item
        # in the play queue.
        dest_row = treeview.get_dest_row_at_pos(x, y)
        if dest_row is None:
            self.playqueue_treeview.set_drag_dest_row(None,
                    Gtk.TreeViewDropPosition.AFTER)
        else:
            path, position = dest_row
            self.playqueue_treeview.set_drag_dest_row(path, position)
        Gdk.drag_status(context, Gdk.DragAction.COPY, time)

    @Gtk.Template.Callback()
    def on_playqueue_treeview_drag_data_received(self, treeview, context,
            x, y, data, info, time):
        selection = treeview.get_selection()
        if context.get_suggested_action() == Gdk.DragAction.COPY:
            cargo = DragCargo._make(pickle.loads(data.get_data()))

            # Get values for the primary keys.
            primary_keys = config.genre_spec[cargo.genre]['primary']
            primary_metadata, = zip(*cargo.metadata[:len(primary_keys)])
            primary_vals_str = '\n'.join(primary_metadata)

            # Get thumbnail.
            filename = Path(IMAGES, cargo.uuid, 'thumbnail-00.jpg')
            if not filename.exists():
                filename = Path(IMAGES_DIR, 'noimage_thumbnail.png')
            thumbnail_pb = Pixbuf.new_from_file(str(filename))

            # Although select playqueue does not need props, play metadata
            # obtains property values from playqueue_model.
            play_tracks = list(cargo.tracks)
            source_row = PlayqueueModelRow(thumbnail_pb, (primary_vals_str,),
                    cargo.tracks, cargo.group_map, cargo.genre, cargo.uuid,
                    cargo.work_num, False, cargo.props, True, play_tracks)
            drop_iter = self._place_drop(treeview, x, y, source_row)

            # Do not delete the original row.
            context.finish(True, False, time)

            if drop_iter is not None:
                with stop_emission(self.playqueue_treeselection, 'changed'):
                    selection.select_iter(drop_iter)
                drop_path = playqueue_model.get_path(drop_iter)
                treeview.scroll_to_cell(drop_path, None, True, 0.5, 0.0)
        else:
            # This drag originated in the playqueue itself.
            model, source_iter = selection.get_selected()
            source_row = PlayqueueModelRow._make(model[source_iter])
            with stop_emission(self.playqueue_treeselection, 'changed'):
                selection.unselect_all()
                drop_iter = self._place_drop(treeview, x, y, source_row)
                if drop_iter is None:
                    context.finish(False, False, time)
                else:
                    context.finish(True, True, time)
                    selection.select_iter(drop_iter)

            if drop_iter is not None:
                drop_path = model.get_path(drop_iter)
                treeview.scroll_to_cell(drop_path, None, True, 0.5, 0.0)

    def _place_drop(self, treeview, x, y, source_row):
        model = playqueue_model
        dest_row = treeview.get_dest_row_at_pos(x, y)
        if dest_row is not None:
            path, position = dest_row
            dest_iter = model.get_iter(path)
            if position == Gtk.TreeViewDropPosition.BEFORE:
                drop_iter = model.insert_before(dest_iter, source_row)
            else:
                drop_iter = model.insert_after(dest_iter, source_row)
        else:
            drop_iter = model.append(source_row)
        return drop_iter

    def on_playqueue_play_selection_changed(self, obj, treepath):
        self.playqueue_treeselection.select_path(treepath)

    def on_recording_selection_changed(self, selection):
        model_filter, treeiter = selection.get_selected()
        if treeiter is None:
            self.playqueue_treeselection.unselect_all()

    @idle_add
    def on_track_selection_changed(self, selection):
        model = getattr_from_obj_with_name('selector.recording_selector.model')
        if model.recording is not None:
            track_view = getattr_from_obj_with_name('track-view')
            tracks = track_view.get_selected_tracks()
            uuid = model.recording.uuid
            work_num = model.work_num

            # Traverse the rows of playqueue looking for a matching set.
            for row in playqueue_model_with_attrs:
                if (row.uuid, row.work_num, row.play_tracks) \
                        == (uuid, work_num, tracks):
                    playqueue_treeselection = self.playqueue_treeselection
                    with stop_emission(playqueue_treeselection, 'changed'):
                        playqueue_treeselection.select_iter(row.iter)
                    break
            else:
                with stop_emission(self.playqueue_treeselection, 'changed'):
                    self.playqueue_treeselection.unselect_all()

    def on_track_finished(self, player, n_tracks, track_id, uuid, work_num):
        # Remove the track from play_tracks with id track_id (which might not
        # be the first one if random is set).
        first_set = playqueue_model_with_attrs[0]
        first_set.play_tracks = [t for t in first_set.play_tracks
                if t.track_id != track_id]

        # Update item duration if the first set is selected.
        model, treeiter = self.playqueue_treeselection.get_selected()
        if treeiter is not None:
            path = model.get_path(treeiter)
            if path == Gtk.TreePath.new_first():
                self._display_item_duration(treeiter)

        self._display_total_duration()

    def on_recording_saved(self, editnotebook, genre):
        recording = editnotebook.recording
        work_num = editnotebook.work_num
        uuid = recording.uuid

        for row in playqueue_model_with_attrs:
            if (row.uuid, row.work_num) == (uuid, work_num):
                primary_keys = config.genre_spec[genre]['primary']
                work = recording.works[work_num]
                primary_work_long = work.metadata[:len(primary_keys)]
                primary_metadata, = zip(*primary_work_long)
                primary_vals_str = '\n'.join(primary_metadata)
                row.long_metadata = (primary_vals_str,)

                row.tracks = playable_tracks(recording.tracks, work.track_ids)
                row.genre = genre

                # Update the cover art in both select and play playqueues.
                images_editor = editnotebook.pages['images'].page_widget
                images_liststore = images_editor.images_liststore
                if len(images_liststore):
                    thumbnail = images_editor.images_liststore[0][1]
                    row.image = thumbnail

                    playqueue_play = \
                            getattr_from_obj_with_name('playqueue_play')
                    playqueue_play.update_image(row.path[0], thumbnail)

    def on_work_deleted(self, editnotebook, genre, uuid, work_num):
        for row in reversed(playqueue_model_with_attrs):
            if (row.uuid, row.work_num) == (uuid, work_num):
                del playqueue_model[row.path]

    def on_recording_deleted(self, editnotebook, uuid):
        for row in reversed(playqueue_model_with_attrs):
            if row.uuid == uuid:
                del playqueue_model[row.path]

    # Called from select.random to enqueue a randomly selected recording.
    def enqueue_recording(self, genre, recording, work_num, play_tracks):
        primary_keys = config.genre_spec[genre]['primary']
        work = recording.works[work_num]
        primary_metadata, = zip(*work.metadata[:len(primary_keys)])
        primary_vals_str = '\n'.join(primary_metadata)

        filename = Path(IMAGES, recording.uuid, 'thumbnail-00.jpg')
        if not filename.exists():
            filename = Path(IMAGES_DIR, 'noimage_thumbnail.png')
        thumbnail_pb = Pixbuf.new_from_file(str(filename))

        group_map = {t: GroupTuple(g_name, g_metadata)
                for g_name, g_tracks, g_metadata in work.trackgroups
                for t in g_tracks}
        source_row = PlayqueueModelRow(thumbnail_pb, (primary_vals_str,),
                play_tracks, group_map, genre, recording.uuid,
                work_num, False, recording.props, True, list(play_tracks))
        playqueue_model.append(source_row)

    def _display_item_duration(self, treeiter):
        row = playqueue_model_with_attrs[treeiter]
        item_duration_str = make_time_str(row.duration)
        self.playqueue_item_duration_value.set_text(item_duration_str)

    def _display_total_duration(self):
        total_duration = sum(row.duration
                for row in playqueue_model_with_attrs)
        total_duration_str = make_time_str(total_duration)
        self.playqueue_total_duration_value.set_text(total_duration_str)

    # The next two methods are called from random when generating a queue.
    def scroll_last_set(self):
        last_row = playqueue_model[-1]
        self.playqueue_treeview.scroll_to_cell(
                last_row.path, None, False, 0.0, 0.0)

    def select_and_scroll_first_set(self):
        first_row = playqueue_model[0]
        self.playqueue_treeview.scroll_to_cell(
                first_row.path, None, False, 0.0, 0.0)
        self.playqueue_treeselection.select_iter(first_row.iter)

