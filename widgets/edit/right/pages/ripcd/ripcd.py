"""Controls for ripping CDs."""

import os

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from . import doublebutton
from .rawmetadata import RawMetadata
from .cddrivewatcher import CDDriveWatcher
from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import EXPAND, NOEXPAND
from common.decorators import idle_add
from common.types import TrackTuple
from common.utilities import debug
from common.utilities import css_load_from_data
from ripper import ripper
from widgets import options_button
from widgets import edit
from widgets.messagelabel import MessageLabel
from worker import worker

css_data = """
progressbar text {
    color: #FFFFFF;
}
"""

@Gtk.Template.from_file('data/glade/edit/right/ripcd.glade')
class RipCD(Gtk.Box):
    __gtype_name__ = 'ripcd_box'

    @GObject.Signal
    def rip_create_clicked(self):
        pass

    ripcd_stack_box = Gtk.Template.Child()

    ripcd_right_stack = Gtk.Template.Child()
    abort_button = Gtk.Template.Child()
    cd_eject_button = Gtk.Template.Child()

    ripcd_left_stack = Gtk.Template.Child()
    ripcd_track_progress_box = Gtk.Template.Child()
    ripcd_progressbar = Gtk.Template.Child()
    ripcd_track_label = Gtk.Template.Child()
    ripcd_message_label_box = Gtk.Template.Child()

    raw_metadata_scrolledwindow = Gtk.Template.Child()

    cd_drive_watcher = CDDriveWatcher()

    def __init__(self):
        super().__init__()
        self.set_name('edit-ripcd')
        self.tab_text = 'Rip CD'
        self.mbquery = None

        css_load_from_data(css_data)

        doublebutton.config(0, self.cd_drive_watcher.disc_ready, False)
        doublebutton.connect('clicked', self.on_doublebutton_clicked)

        self.ripcd_stack_box.pack_start(doublebutton, *NOEXPAND)
        self.ripcd_stack_box.reorder_child(doublebutton, 0)

        self.message_label = MessageLabel()
        self.message_label.show()
        self.ripcd_message_label_box.pack_start(self.message_label, *EXPAND)

        self.raw_metadata = RawMetadata()
        self.raw_metadata_scrolledwindow.add(self.raw_metadata)

        options_button.connect_menuitem('Edit', 'Query MB',
                self.on_options_edit_querymb_activate)
        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)
        options_button.connect_menuitem('Edit', 'Delete',
                self.on_options_edit_delete_activate)

        ripper.connect('rip-track-started', self.on_rip_track_started)
        ripper.connect('rip-track-position', self.on_rip_track_position)
        ripper.connect('rip-finished', self.on_rip_finished)
        ripper.connect('rip-error', self.on_rip_error)

        register_connect_request('tags-metadata', 'import-finished',
                self.on_import_finished)
        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('genre-button', 'genre-changed',
                self.on_genre_changed)

        self.cd_drive_watcher.connect('notify::disc-ready',
                self.on_disc_ready_changed)

    # -Signal handlers---------------------------------------------------------
    def on_disc_ready_changed(self, cddrivewatcher, param):
        selection = getattr_from_obj_with_name('selector.recording_selection')
        model, treeiter = selection.get_selected()
        recording_selected = treeiter is not None
        disc_ready = cddrivewatcher.disc_ready
        changed = getattr_from_obj_with_name('edit-left-notebook.changed')
        sensitive = (recording_selected or changed) and disc_ready
        doublebutton.config(None, disc_ready, sensitive)

        sensitive = recording_selected or disc_ready
        options_button.sensitize_menuitem('Edit', 'Query MB', sensitive)

        self.cd_eject_button.set_sensitive(disc_ready)

    def on_recording_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        recording_selected = treeiter is not None
        changed = getattr_from_obj_with_name('edit-left-notebook.changed')
        busy = changed or ripper.is_ripping
        disc_ready = self.cd_drive_watcher.disc_ready
        doublebutton.config(recording_selected and not busy,
                disc_ready, recording_selected and disc_ready)

        sensitive = recording_selected or disc_ready
        options_button.sensitize_menuitem('Edit', 'Query MB', sensitive)

    def on_genre_changed(self, genre_button, genre):
        disc_ready = self.cd_drive_watcher.disc_ready
        doublebutton.config(0, disc_ready, False)

    def on_import_finished(self, rawmetadata):
        doublebutton.config(1, True, True)

    # -Button signal handlers--------------------------------------------------
    def on_doublebutton_clicked(self, button, label):
        match label:
            case 'Create':
                # I emit rip-create-clicked. It goes to work.editor, images,
                # properties, editnotebook, and importfiles.
                self.emit('rip-create-clicked')

                self.create()
            case 'Add':
                self.add_cd()

    @Gtk.Template.Callback()
    def on_cd_eject_button_clicked(self, button):
        os.system('eject')

    @Gtk.Template.Callback()
    def on_abort_button_clicked(self, button):
        self.mbquery = None
        worker.cancellable.cancel()
        self.raw_metadata.clear()
        self._initialize_controls()
        self.message_label.hide()

    # -Option handlers---------------------------------------------------------
    def on_options_edit_querymb_activate(self, menuitem):
        self.mbquery = None
        self.raw_metadata.clear()
        worker.cancellable.reset()

        # The querymb option is insensitive unless either a recording is
        # selected or a disc is ready. If a disc is not ready, then the
        # other condition must be True. It is also possible that they are
        # both True. In that case, the disc gets priority.
        recording = getattr_from_obj_with_name('edit-left-notebook.recording')
        if self.cd_drive_watcher.disc_ready:
            discid = self.cd_drive_watcher.disc_id
        else:
            discid = recording.discids[0]
        self.query_mb(discid, self.query_mb_cb)

    def on_options_edit_clear_activate(self, menuitem):
        selector = getattr_from_obj_with_name('selector')
        model = selector.recording_selector.model
        recording_selected = model.recording is not None

        self.mbquery = None
        self._initialize_controls()
        doublebutton.config(recording_selected, True, recording_selected)

    def on_options_edit_delete_activate(self, menuitem):
        self.raw_metadata.clear()
        self._initialize_controls()
        disc_ready = self.cd_drive_watcher.disc_ready
        doublebutton.config(0, disc_ready, False)

    # -Ripper signal handlers--------------------------------------------------
    def on_rip_track_started(self, ripper, uuid, n_tracks, track_num):
        text = f'{track_num + 1} / {n_tracks}'
        self.ripcd_progressbar.set_fraction(0.0)
        self.ripcd_track_label.set_text(text)

    def on_rip_track_position(self, ripper, uuid, disc_num, track_num,
            track_position):
        self.ripcd_progressbar.set_fraction(track_position)

    def on_rip_finished(self, ripper):
        self._initialize_controls()

        # If I just finished ripping a CD, the next operation might be
        # to add a CD. Create is less likely (but possible) as it would
        # obliterate the rip just completed.
        doublebutton.config(1, True, True)

    def on_rip_error(self, ripper, message):
        self.queue_message(f'Rip error: {message}')

    # -Query MB methods--------------------------------------------------------
    def query_mb(self, discid, query_mb_cb):
        def query_mb_task(discid):
            # The top directory for this subprocess is worker, so to find
            # common we need to add the cwd for the main process to sys.path.
            import os
            import sys
            sys.path.append(os.getcwd())

            from common.musicbrainz import MBQuery
            return MBQuery.do_discid_query(discid)

        if not worker.cancellable.is_cancelled():
            worker.do_in_subprocess(query_mb_task, query_mb_cb, discid)

    # -Read CD methods---------------------------------------------------------
    def read_sectors(self, read_sectors_cb):
        def read_sectors_task():
            import discid
            disc = discid.read()
            return [t.sectors for t in disc.tracks]

        if not worker.cancellable.is_cancelled():
            worker.do_in_subprocess(read_sectors_task, read_sectors_cb)

    @idle_add
    def read_cd(self, extract_cb):
        self.queue_message('Querying MusicBrainz')

        images_editor = getattr_from_obj_with_name('edit-images-page')
        images_editor.cancellable.reset()

        # The subprocess needs to get disc itself because disc contains
        # ctypes objects which cannot be marshaled, so launcher cannot
        # pass disc (or disc.tracks) to worker.
        def read_cd_task():
            # The top directory for this subprocess is worker, so to find
            # common we need to add the cwd for the main process to sys.path.
            import os
            import sys
            sys.path.append(os.getcwd())

            import discid
            from common.musicbrainz import MBQuery
            disc = discid.read()
            return MBQuery(disc)

        # While read_cd was sitting in the event loop, it is possible that
        # the user clicked abort. Abort asserts cancellable.cancel, but
        # that action terminates a job that is already running. We test
        # worker.cancellable.is_cancelled() here to avoid
        # launching read_cd_task if True.
        if not worker.cancellable.is_cancelled():
            worker.do_in_subprocess(read_cd_task, extract_cb)

    # -Callbacks for read_sectors----------------------------------------------
    # cb for the call in create.
    def read_sectors_full_cb(self, success, sectors):
        self.sectors = sectors
        if success:
            self.read_cd(self.full_extract_cb)

    # cb for the call in add_cd.
    def read_sectors_tracks_cb(self, success, sectors):
        self.sectors = sectors
        if success and not ripper.rerip:
            self.raw_metadata.clear()
            self.read_cd(self.track_extract_cb)

    # -Callbacks for read_cd---------------------------------------------------
    # cb for the call in read_sectors_full_cb.
    def full_extract_cb(self, success, mbquery):
        if not success:
            self._error_extract(mbquery)
            self._function_runner(None, 'track')
            return
        self._function_runner(mbquery, 'image', 'work', 'track', 'raw')

    # cb for the call in read_sectors_tracks_cb.
    def track_extract_cb(self, success, mbquery):
        if not success:
            self._error_extract(mbquery)
            self._function_runner(None, 'track')
            return
        self._function_runner(mbquery, 'track', 'raw')

    # cb for the call in on_options_edit_querymb_activate.
    def raw_extract_cb(self, success, mbquery):
        if not success:
            self._error_extract(mbquery)
            return
        self._function_runner(mbquery, 'raw')

    # -Callback for query_mb---------------------------------------------------
    def query_mb_cb(self, success, mbquery):
        if not success:
            self._error_extract(mbquery)
            return
        self._function_runner(mbquery, 'image', 'raw')

    # -The callbacks for read_cd all call _function_runner---------------------
    def _function_runner(self, mbquery, *function_names):
        for func_name in function_names:
            func = getattr(self, f'_{func_name}_extract')
            func(mbquery)
        self.mbquery = mbquery

    # -The functions for _function_runner--------------------------------------
    def _work_extract(self, mbquery):
        work_editor = getattr_from_obj_with_name('edit-work-page')
        work_editor.map_metadata(mbquery.metadata)
        work_editor._work_metadata_changed = True

    def _track_extract(self, mbquery):
        disc_num = ripper.disc_num

        func = (self._real_tracks, self._default_tracks)[mbquery is None]
        tracks = [(t, (disc_num, t.track_num))
                for t in func(mbquery, disc_num)]
        all_tracks, work_tracks = zip(*tracks)

        track_editor = getattr_from_obj_with_name('edit-tracks-page')
        track_editor.populate(all_tracks, work_tracks, [])
        track_editor._track_metadata_changed = True

    def _image_extract(self, mbquery):
        if not hasattr(ripper, 'disc_num'):
            return
        disc_num = ripper.disc_num
        images_editor = getattr_from_obj_with_name('edit-images-page')
        images_editor.get_images(mbquery, disc_num)

    def _raw_extract(self, mbquery):
        self.raw_metadata.display_metadata(mbquery.metadata,
                mbquery.tracknumbers)

    def _error_extract(self, mbquery):
        if 'Error 404' in mbquery:
            message = 'MusicBrainz: disc not found'
        else:
            message = mbquery.removeprefix('caused by: ')

        self.queue_message(message)
        self.mbquery = None

    # -_track_extract calls one of these two functions-------------------------
    def _real_tracks(self, mbquery, disc_num):
        for i, t in enumerate(mbquery.tracks):
            yield TrackTuple(disc_num, i, t.title, t.duration)

    def _default_tracks(self, mbquery, disc_num):
        # If no disc matching discid has been found, get track information
        # from the disc and add generic Tracks.
        for i, sector in enumerate(self.sectors):
            title = f'Track {i + 1}'
            duration = sector / 75.0
            yield TrackTuple(disc_num, i, title, duration)

    # -Utility methods---------------------------------------------------------
    def create(self):
        doublebutton.hide()
        self.abort_button.set_sensitive(True)
        self.raw_metadata.clear()
        self.mbquery = None
        worker.cancellable.reset()

        self.ripcd_right_stack.set_visible_child_name('stop')

        # The child must be visible for set_visible_child_name to work.
        self.ripcd_progressbar.set_fraction(0.0)
        self.ripcd_track_label.set_text('1 / 1')
        self.ripcd_track_progress_box.show()
        self.ripcd_left_stack.set_visible_child_name('progress')

        self.read_sectors(self.read_sectors_full_cb)

        # rip_disc creates SOUND, IMAGES, DOCUMENTS. (Likewise, importer
        # creates those directories during an import operation.)
        ripper.rip_disc(self.cd_drive_watcher.disc_id)

    def add_cd(self):
        doublebutton.hide()
        self.abort_button.set_sensitive(True)
        worker.cancellable.reset()

        self.ripcd_right_stack.set_visible_child_name('stop')

        self.ripcd_progressbar.set_fraction(0.0)
        self.ripcd_track_label.set_text('1 / 1')
        self.ripcd_track_progress_box.show()
        self.ripcd_left_stack.set_visible_child_name('progress')

        self.read_sectors(self.read_sectors_tracks_cb)

        ripper.add_disc(self.cd_drive_watcher.disc_id)

    def _initialize_controls(self):
        self.ripcd_right_stack.set_visible_child_name('create')
        self.ripcd_left_stack.set_visible_child_name('progress')
        self.ripcd_track_progress_box.hide()
        doublebutton.show()
        self.cd_eject_button.set_sensitive(True)

    def queue_message(self, message):
        # Set left stack to expose message_label.
        restore_child_name = self.ripcd_left_stack.get_visible_child_name()
        def expose_message_label():
            self.ripcd_left_stack.set_visible_child_name('label')
        def restore_left_stack():
            self.ripcd_left_stack.set_visible_child_name(restore_child_name)
        self.message_label.queue_message(message,
                    expose_message_label, restore_left_stack)

