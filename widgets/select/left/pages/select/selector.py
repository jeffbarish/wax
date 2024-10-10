"""This module assembles the genre selector, recording view, and
track view into a grid."""

import pickle
import unicodedata
from operator import attrgetter

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from . import genre_button
from .recordingselector import RecordingSelector
from .trackselector import TrackSelector
from .alphabetscroller import AlphabetScroller
from .filterbutton import FilterButtonBox
from common.config import config
from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.decorators import idle_add
from common.types import DragCargo
from common.utilities import debug
from widgets.select.right import select_right as playqueue_select
from widgets.select.right import playqueue_model_with_attrs

PANED_POSITION = config.geometry['selector_paned_position']

class Selector(Gtk.Grid):
    def __init__(self):
        super().__init__()
        self.set_name('selector')
        self.tab_text = 'Selector'
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_margin_bottom(3)
        self.set_margin_left(3)
        genre_button.set_margin_left(0)

        selector_hbox = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 3)
        selector_hbox.add(genre_button)
        self.add(selector_hbox)

        self.filter_button_box = filter_button_box = FilterButtonBox()
        selector_hbox.add(filter_button_box)

        filter_button_box.connect('filter-button-created',
                self.on_filter_button_created)
        filter_button_box.connect('filter-button-activated',
                self.on_filter_button_activated)
        filter_button_box.connect('filter-button-deactivated',
                self.on_filter_button_deactivated)

        self.alphabet_scroller = alphabet_scroller = AlphabetScroller()
        self.add(alphabet_scroller)

        self.recording_selector = recording_selector = RecordingSelector()
        recording_selector.model.set_visible_func(filter_button_box)

        recording_selector.view.connect('column-widths-changed',
                self.on_column_widths_changed)

        recording_scrolled_window = Gtk.ScrolledWindow()
        recording_scrolled_window.add(recording_selector.view)
        recording_scrolled_window.set_policy(Gtk.PolicyType.NEVER,
                Gtk.PolicyType.AUTOMATIC)
        recording_scrolled_window.set_shadow_type(Gtk.ShadowType.NONE)

        self.recording_selection = recording_selector.view.selection
        self.recording_selection.connect('changed',
                self.on_recording_selection_changed)

        self.track_selector = track_selector = TrackSelector()

        self.track_scrolled_window = track_scrolled_window = \
                Gtk.ScrolledWindow()
        track_scrolled_window.add(track_selector.view)
        track_scrolled_window.set_policy(Gtk.PolicyType.NEVER,
                Gtk.PolicyType.AUTOMATIC)

        self.track_selection = track_selection = track_selector.view.selection
        track_selection.connect('changed', self.on_track_selection_changed)

        self.paned = paned = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        paned.set_position(PANED_POSITION)
        paned.add1(recording_scrolled_window)
        paned.add2(track_scrolled_window)
        self.add(paned)

        self.show_all()
        track_scrolled_window.hide()

        genre_button.connect('genre-changed', self.on_genre_changed)
        genre_button.connect('genre-changing', self.on_genre_changing)

        # Enable drag and drop from recording view.
        target_flags = Gtk.TargetFlags.SAME_APP
        recording_selector.view.enable_model_drag_source(
                Gdk.ModifierType.BUTTON1_MASK,
                [Gtk.TargetEntry.new('recording', target_flags, 0)],
                Gdk.DragAction.COPY)
        recording_selector.view.connect('drag-data-get',
                self.on_recording_selector_drag_data_get)
        recording_selector.view.connect('size-allocate',
                self.on_recording_selector_size_allocate)

        register_connect_request('playqueue_select.playqueue_treeselection',
                'changed', self.on_playqueue_select_selection_changed)

        register_connect_request('alphabet-scroller',
                'scroll-to-letter', self.on_scroll_to_letter)
        register_connect_request('filter-button-box',
                'filter-button-activated', self.on_filter_button_activated)

        register_connect_request('edit-left-notebook',
                'recording-saved', self.on_recording_saved)
        register_connect_request('edit-left-notebook',
                'work-deleted', self.on_work_deleted)
        register_connect_request('edit-left-notebook',
                'recording-deleted', self.on_recording_deleted)

        register_connect_request('search-incremental', 'selection-changed',
                self.on_search_incremental_selection_changed)
        register_connect_request('search-sibling', 'selection-changed',
                self.on_search_sibling_selection_changed)

        register_connect_request('player', 'track-started',
                self.on_track_started)
        register_connect_request('player', 'track-finished',
                self.on_track_finished)
        register_connect_request('player', 'set-started',
                self.on_set_started)

        self.allocation_height = 0

    def on_recording_selector_size_allocate(self, widget, allocation):
        # If the height has not actually changed, do nothing.
        if allocation.height == self.allocation_height:
            return

        self.allocation_height = allocation.height

        # If there is no selection, then scrolling is unnecessary.
        model, treeiter = self.recording_selection.get_selected()
        if treeiter is None:
            return

        # After the track selector opens, the height of the recording
        # selector is less than the height of the paned. Wait until
        # that condition is True before scrolling the selection.
        paned_allocation = self.paned.get_allocation()
        if allocation.height < paned_allocation.height:
            self.scroll_selection()

    def do_destroy(self):
        genre = genre_button.genre
        self.on_genre_changing(genre_button, genre)

    def on_genre_changing(self, genre_button, genre):
        self.save_configuration(genre)

    def on_column_widths_changed(self, recording_view, widths):
        genre = genre_button.genre
        self.save_configuration(genre)

    def save_configuration(self, genre):
        new_column_widths = self.recording_selector.view.get_column_widths()
        with config.modify('column widths') as column_widths:
            column_widths[genre] = new_column_widths

        new_filter_config = self.filter_button_box.get_config()
        with config.modify('filter config') as filter_config:
            filter_config[genre] = new_filter_config

    def on_genre_changed(self, genre_button, genre):
        model, treeiter = self.recording_selector.view.selection.get_selected()
        self.filter_button_box.clear()
        self.hide_track_window()

        # Configure the filter buttons after all handlers for genre-changed
        # have run.
        GLib.idle_add(self.finish_on_genre_changed, genre)

    def finish_on_genre_changed(self, genre):
        # Set filter buttons to their first menuitem only when responding
        # to a manual change in genre. Perform this test only if any
        # button is visible.
        filter_button_box = self.filter_button_box
        if any(filter_button_box):
            for button in filter_button_box:
                button.set_label_to_first_menuitem()
        self.recording_selector.refilter()

        # Set filter button visibility.
        for index in config.filter_config[genre]:
            self.filter_button_box.show_button(index)
            self.update_filter_button_menus(self.filter_button_box)

        # The first row gets selected if the user clicks on a header divider
        # or types tab immediately after starting wax.
        with stop_emission(self.recording_selection, 'changed'):
            self.recording_selector.view.clear_first_row_selection()

    def update_filter_button_menus(self, filterbuttonbox):
        self.recording_selector.update_filter_button_menus(filterbuttonbox)

    def on_filter_button_created(self, filterbuttonbox, button):
        view = self.recording_selector.view
        view.on_filter_button_created(filterbuttonbox, button)
        self.update_filter_button_menus(filterbuttonbox)

    def on_filter_button_deactivated(self, filterbuttonbox, column_index):
        self.update_filter_button_menus(filterbuttonbox)
        view = self.recording_selector.view
        view.on_filter_button_deactivated(filterbuttonbox, column_index)

    def on_filter_button_activated(self, filterbuttonbox):
        self.update_filter_button_menus(filterbuttonbox)

        # Any selection cannot survive a change in a filter button, so clear
        # any selection (if there is one).
        selection = self.recording_selection
        selection.unselect_all()

        self.hide_track_window()

        # The recording selection did not survive the filter,
        # so any corresponding selection in playqueue_select
        # also does not survive.
        selection = playqueue_select.playqueue_treeselection
        selection.unselect_all()

    @emission_stopper()
    def on_recording_selection_changed(self, selection):
        model_filter, treeiter = selection.get_selected()
        if treeiter is None:
            self.recording_selector.model.recording = None
            self.track_scrolled_window.hide()
            return
        self.update_track_selector()
        self.track_scrolled_window.show()

        self.scroll_selection()

    def on_search_incremental_selection_changed(self, searchincremental,
            genre, uuid, work_num, tracks):
        self.set_selection(genre, uuid, work_num, tracks)

    def on_search_sibling_selection_changed(self, searchsibling,
            genre, uuid, work_num, tracks):
        self.set_selection(genre, uuid, work_num, tracks)

    def update_track_selector(self):
        model = self.recording_selector.model
        recording = model.recording
        work = model.work
        with stop_emission(self.track_selection, 'changed'):
            self.track_selector.populate(
                    recording.tracks, work.track_ids, work.trackgroups)

    def hide_track_window(self):
        # If the recording_selector view has been allocated, then it must be
        # resized to fill the space previously occupied by the track window.
        allocation = self.recording_selector.view.get_allocation()
        if allocation.height > 1:
            self.track_scrolled_window.hide()

            allocation.height = self.paned.get_allocation().height
            self.recording_selector.view.size_allocate(allocation)

    def scroll_selection(self):
        model, treeiter = self.recording_selection.get_selected()
        if treeiter is None:
            return  # should not happen

        treepath = model.get_path(treeiter)
        self.recording_selector.view.scroll_to_cell(treepath,
                None, True, 0.5, 0.0)

    @emission_stopper()
    def on_track_selection_changed(self, selection):
        row_selected = bool(selection.count_selected_rows())
        if not row_selected:
            self.track_scrolled_window.hide()
            self.recording_selection.unselect_all()

    def on_recording_selector_drag_data_get(self, treeview, context,
            data, info, time):
        model = self.recording_selector.model
        genre = genre_button.genre
        metadata = model.work.metadata
        tracks = self.track_selector.view.get_selected_tracks()
        group_map = self.track_selector.model.group_map
        uuid = model.recording.uuid
        work_num = model.work_num
        props_wrk = model.recording.works[work_num].props

        cargo = DragCargo(genre, metadata, tracks, group_map, props_wrk,
                uuid, work_num)
        data.set(data.get_selection(), 8, pickle.dumps(cargo))

    # Select the recording that corresponds to the playqueue item.
    @emission_stopper()
    def on_playqueue_select_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return

        getter = attrgetter('genre', 'uuid', 'work_num', 'play_tracks')
        self.set_selection(*getter(playqueue_model_with_attrs[treeiter]))

    # Set the selection either from a playqueue selection (above), a
    # search result, or a newly created recording (on_save_button_clicked
    # in editnotebook).
    def set_selection(self, new_genre, uuid, work_num, tracks):
        # The handler for genre-changed sets the filter buttons to their first
        # menuitem, but code in finish_set_selection sets the buttons correctly
        # for the selection. Also, the handler for genre-changing (above) saves
        # the configuration for the current genre. And the handler in
        # recordingselector reloads the model.
        if new_genre != genre_button.genre:
            genre_button.set_genre(new_genre)

            self.on_genre_changed(genre_button, new_genre)

            self.recording_selector.on_genre_changed(genre_button, new_genre)

            work_editor = getattr_from_obj_with_name('edit-work-page')
            work_editor.on_select_genre_changed(genre_button, new_genre)

            editnotebook = getattr_from_obj_with_name('edit-left-notebook')
            editnotebook.on_select_genre_changed(genre_button, new_genre)

        # Wait for all the other handlers for genre-changed to finish before
        # finalizing the selection.
        self.finish_set_selection(new_genre, uuid, work_num, tracks)

    @idle_add
    def finish_set_selection(self, new_genre, uuid, work_num, tracks):
        # Find the row that corresponds to the playqueue selection.
        row_iter, short = self.get_short_by_uuid(uuid, work_num)
        if row_iter is None:
            return

        # Set the filters to assure that the recording will be visible.
        buttons = {button.index: button
                for button in self.filter_button_box}
        for index, val in enumerate(short):
            # If there is a button for this column index, then set its
            # label to the first name in val.
            if button := buttons.get(index, None):
                button.label = val[0]

        self.update_filter_button_menus(self.filter_button_box)

        # Select and scroll recording.
        model = self.recording_selector.model
        model.read_long_metadata(row_iter)
        treeiter = model.convert_child_iter_to_iter(row_iter)
        with stop_emission(self.recording_selection, 'changed'):
            self.recording_selection.select_iter(treeiter)
        GLib.idle_add(self.scroll_selection)

        # Update trackselector.
        recording = self.recording_selector.model.recording
        work = self.recording_selector.model.work
        with stop_emission(self.track_selection, 'changed'):
            self.track_selector.populate(
                    recording.tracks, work.track_ids, work.trackgroups)

        # Select tracks.
        with stop_emission(self.track_selection, 'changed'):
            self.track_selector.view.set_selected_tracks(tracks)

        self.track_scrolled_window.show()

        # Update editnotebook, playnotebook.metadata, and coverartviewer.
        for obj_name in ('edit-left-notebook.on_recording_selection_changed',
                'play-notebook.on_recording_selection_changed',
                'coverart-viewer.on_recording_selection_changed'):
            getattr_from_obj_with_name(obj_name)(self.recording_selection)

        # A recording is selected now (it got selected above), so sensitize
        # the Play option in the mode menu.
        control_panel_view = getattr_from_obj_with_name('control-panel.view')
        control_panel_view.play_menuitem_set_sensitive(True)

    def on_scroll_to_letter(self, alphabetscroller, letter):
        model = self.recording_selector.model
        if len(model) == 0:
            return

        path = self.get_path_for_letter(model, letter)
        GLib.idle_add(self.recording_selector.view.scroll_to_cell,
                path, None, True, 0.5, 0.0)

    def get_path_for_letter(self, model, letter):
        sort_column_index = model.clicked_column_id
        letter = letter.lower()
        for row in model.model_filter:
            # short is a tuple of names (name group).
            short, uuid, work_num = row
            sort_name_group = short[sort_column_index]
            name = sort_name_group[0]  # first name in name group
            key = name[0]  # first letter of name
            key_norm = unicodedata.normalize('NFKD', key.lower())
            if key_norm >= letter:
                break
        return row.path

    def get_short_by_uuid(self, uuid, work_num):
        for row in self.recording_selector.model:
            short, row_uuid, row_work_num = row
            if (row_uuid, row_work_num) == (uuid, work_num):
                return row.iter, short
        return None, []

    def on_recording_saved(self, editnotebook, genre):
        if genre != genre_button.genre:
            # The genre-changed signal goes to editnotebook and work.editor
            # as well as here and recordingselector. We want it here so that
            # selector and recordingselector.model will actually change to
            # the genre of the new recording, but editor is already in the
            # right genre. Accordingly, we change the genre using set_genre
            # to suppress genre-changed and then call the handlers here and
            # in recordingselector directly.
            genre_button.set_genre(genre)
            self.recording_selector.on_genre_changed(genre_button, genre)
            self.on_genre_changed(genre_button, genre)

        self.finish_recording_saved(editnotebook)

    @idle_add
    def finish_recording_saved(self, editnotebook):
        recording = editnotebook.recording
        work_num = editnotebook.work_num

        # Update model with the new long work metadata.
        model = self.recording_selector.model
        model.set_recording(recording, work_num)

        playnotebook = getattr_from_obj_with_name('play-notebook')
        playnotebook.on_recording_selection_changed(self.recording_selection)

        # Remove the old row, if it exists (if we are saving a revision of
        # an existing recording).
        uuid = recording.uuid
        row_iter, _ = self.get_short_by_uuid(uuid, work_num)
        if row_iter is not None:
            work_editor = getattr_from_obj_with_name('edit-work-page')
            with stop_emission(self.recording_selection, 'changed'), \
                    work_editor.freeze_notify():
                model.remove(row_iter)

        # Insert the new row in the correct sorted position in model (and
        # remove the old row below).
        _, work_short_new = editnotebook.get_work_metadata()
        model.insert_short(work_short_new, uuid, work_num)
        row_iter, _ = self.get_short_by_uuid(uuid, work_num)

        # Set the filters to assure that the recording will be visible.
        buttons = {button.index: button
                for button in self.filter_button_box}
        for index, val in enumerate(work_short_new):
            # If there is a button for this column index, then set its
            # label to the first name in val.
            if button := buttons.get(index, None):
                button.label = val[0]
        self.update_filter_button_menus(self.filter_button_box)

        # Select and scroll the new recording.
        new_iter = model.convert_child_iter_to_iter(row_iter)
        with stop_emission(self.recording_selection, 'changed'):
            self.recording_selection.select_iter(new_iter)
        self.scroll_selection()

        # Update the track metadata and select all tracks.
        tracks = recording.tracks
        trackids_playable = recording.works[work_num].track_ids
        trackgroups = recording.works[work_num].trackgroups
        self.track_selector.populate(tracks, trackids_playable, trackgroups)
        self.track_selection.select_all()
        GLib.idle_add(self.track_scrolled_window.show)

        # A recording is selected now (it got selected above), so sensitize
        # the Play option in the mode menu.
        control_panel_view = getattr_from_obj_with_name('control-panel.view')
        control_panel_view.play_menuitem_set_sensitive(True)

    # Edit option Delete emits work-deleted; delete only the selected work.
    def on_work_deleted(self, editnotebook, genre, uuid, work_num):
        # The user might have selected another work, possibly one in a
        # different genre. If the select genre changed, the recording will
        # be gone the next time the user selects the genre of the deleted
        # recording because the metadata were deleted from the metadata
        # files. If the select genre did not change, search the current
        # genre for the work and remove it if it is found.
        if genre != self.recording_selector.model.genre:
            return

        treeiter, _ = self.get_short_by_uuid(uuid, work_num)
        if treeiter is not None:
            model = self.recording_selector.model
            work_editor = getattr_from_obj_with_name('edit-work-page')
            with stop_emission(self.recording_selection, 'changed'), \
                    work_editor.freeze_notify():
                model.remove(treeiter)
            model.recording = None

        # Update the filter button menus as the content of the columns
        # might have changed.
        self.update_filter_button_menus(self.filter_button_box)

        with stop_emission(self.recording_selection, 'changed'):
            self.recording_selection.unselect_all()

        GLib.idle_add(self.track_scrolled_window.hide)

    # abort emits recording-deleted; all works with the given uuid in the
    # current genre should be deleted. editnotebook deletes works in other
    # genres from short files, so they will not appear when the user selects
    # one of those genres.
    def on_recording_deleted(self, editnotebook, uuid):
        model = self.recording_selector.model

        # Get paths for all rows with row_uuid == uuid.
        delete_paths = [row.path for row in model if row[1] == uuid]

        work_editor = getattr_from_obj_with_name('edit-work-page')
        with stop_emission(self.recording_selection, 'changed'), \
                work_editor.freeze_notify():
            for path in reversed(delete_paths):
                row_iter = model.get_iter(path)
                model.remove(row_iter)

        self.recording_selection.unselect_all()

    def on_track_started(self, player, tracktuple, grouptuple,
            track_duration, more_tracks, uuid):
        # Scroll the playing track.
        # queuefiles.on_queuefiles_load_button_clicked appends a new set
        # and then finishes by selecting the set. *Appending the set*
        # triggers player.on_playqueue_model_row_inserted, which calls
        # on_options_play_restart, which calls queue_tracks_of_first_set,
        # which sends ready-play to engine, which replies with track-started,
        # which reacts by emitting track-started, which brings us here.
        # *Selecting the set* (in queuefiles.on_queuefiles_load_button_clicked)
        # triggers self.on_playqueue_select_selection_changed. It calls
        # set_selection, but set_selection runs in the idle loop. It in turn
        # calls finish_set_selection, which also runs in the idle loop.
        # Thus, recording_selector.model gets updated after we come here.
        # Accordingly, we cannot test whether the uuid in the track-started
        # signal corresponds to the uuid of the recordingselector model.
        # Accordingly, when we give the next command to scroll the
        # playing track, we might actually be scrolling the tracks for
        # the wrong recording. If tracktuple.track_id does not exist in
        # the recording, nothing happens. The correct track gets selected
        # and scrolled in trackselector.scroll_first_selected_track,
        # which is called by trackselector.set_selected_tracks, which is
        # called from finish_set_selection. Although the scrolling performed
        # by this handler gets overridden when appending a new set,
        # I still need this method to update the track selection as play
        # progresses.
        self.track_selector.view.scroll_playing_track(tracktuple.track_id)

    def on_track_finished(self, player, n_tracks, track_id, uuid, work_num):
        model = self.recording_selector.model
        if (uuid, work_num) != (model.recording.uuid, model.work_num):
            return

        # If the first set in the play queue is selected, then the recording
        # in selector is the one that is playing. Otherwise, do nothing here.
        selection = playqueue_select.playqueue_treeselection
        model, treeiter = selection.get_selected()  # model is playqueue_model
        if treeiter is None:
            return  # No set is selected.

        treepath = model.get_path(treeiter)
        if treepath != Gtk.TreePath.new_first():
            return  # The set in the play position (first) is not selected.

        self.track_selector.view.unselect_track(track_id)

    def on_set_started(self, player, uuid, work_num):
        model = self.recording_selector.model
        if model.recording.uuid == uuid and model.work_num == work_num:
            model.update_work_props()

            play_props = getattr_from_obj_with_name('play-properties-page')
            play_props.populate(model.recording.props, model.work.props)

            edit_notebook = getattr_from_obj_with_name('edit-left-notebook')
            edit_notebook.update_work_props(uuid, work_num, model.work.props)

