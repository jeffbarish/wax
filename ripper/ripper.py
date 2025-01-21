"""Ripper is the interface to the rest of the program for ripping and
importing. It supports mixing of rips and imports by centralizing
maintenance of state variables including uuid, discids, and disc_num.
It also does zombie protection."""

import atexit
import shutil
import time
from pathlib import Path

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

from mutagen.flac import FLAC, Picture
from mutagen import id3

from common.connector import register_connect_request
from common.constants import IMAGES, DOCUMENTS, SOUND, TRANSFER
from common.enginelauncher import EngineLauncher
from common.utilities import debug
from widgets import options_button

reply_map = {}

# Decorator to register methods that respond to replies from engine.
def reply(f):
    reply = f.__name__.removeprefix('on_').replace('_', '-')
    reply_map[reply] = f
    return f


class Ripper(GObject.Object):
    @GObject.Signal
    def rip_started(self, uuid: str, disc_num: int):
        pass

    @GObject.Signal
    def rip_finished(self):
        pass

    @GObject.Signal
    def rip_track_started(self, uuid: str, n_tracks: int, track_num: int):
        pass

    @GObject.Signal
    def rip_track_finished(self, uuid: str, disc_num: int, track_num: int):
        pass

    @GObject.Signal
    def rip_track_position(self, uuid: str, disc_num: int, track_num: int,
            position: float):
        pass

    @GObject.Signal
    def rip_aborted(self):
        pass

    @GObject.Signal
    def rip_error(self, message: str):
        pass

    @GObject.Signal
    def import_track_finished(self, uuid: str, disc_num: int, track_num: int):
        pass

    def __init__(self):
        super().__init__()
        self.uuid = self.disc_id = None
        self.disc_ids = []
        self.saved_disc_ids = []

        atexit.register(self.rm_zombie)

        self.rip_engine_launcher = EngineLauncher('ripper/engine.py',
                self.reply_handler)
        self.do = self.rip_engine_launcher.send_command
        self.state = 'NULL'

        register_connect_request('edit-ripcd.abort_button',
                'clicked', self.on_abort_button_clicked)
        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)

        options_button.connect_menuitem('Edit', 'Delete',
                self.on_options_edit_delete_activate)
        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

    # Connector calls get_name to get the name of the object. As Ripper is
    # not a widget, there is no set/get_name.
    def get_name(self):
        return 'ripper'

    @property
    def is_ripping(self):
        return self.state == 'PLAYING'

    # -Handlers for button-----------------------------------------------------
    def on_abort_button_clicked(self, button):
        self.do('stop')

        # If we are reripping, just remove the .part file (in engine.on_stop).
        # If we abort the initial rip of the last disc, delete its tracks.
        # Normally, a rip of the last disc is not a rerip, but it is possible
        # to rerip the last disc so we need to test separately for that case.
        last_disc = (self.disc_id == self.disc_ids[-1])
        if not self.rerip and last_disc:
            shutil.rmtree(Path(SOUND, self.uuid, str(self.disc_num)),
                    ignore_errors=True)
            self.disc_ids.remove(self.disc_id)
            if self.disc_id in self.saved_disc_ids:
                self.saved_disc_ids.remove(self.disc_id)
            self.disc_id = None

            # If disc_ids is now empty, delete the uuid directory too.
            if not self.disc_ids:
                shutil.rmtree(Path(SOUND, self.uuid))

    def on_save_button_clicked(self, button, label):
        if self.disc_id is None:
            return
        self.saved_disc_ids = list(self.disc_ids)

    # -Handlers for options----------------------------------------------------
    def on_options_edit_clear_activate(self, menuitem):
        self.do('stop')

        # Clear deletes tracks for all discs that have not been saved, so
        # it is different from abort.
        self.rm_zombie()

    # The delete option deletes a work, not a recording, so we handle the
    # deletion in editnotebook, where we have the recording. Here, we simply
    # stop any ongoing rip (without generating a rip-aborted signal).
    def on_options_edit_delete_activate(self, menuitem):
        self.do('stop')

    # -Generic-----------------------------------------------------------------
    def make_uuid(self):
        self.rm_zombie()

        self.uuid = f'{time.time_ns():019d}'
        return self.uuid

    def restore(self, uuid, disc_ids):
        self.uuid = uuid
        self.disc_ids = list(disc_ids)
        self.saved_disc_ids = list(disc_ids)
        self.disc_id = self.disc_ids[-1]
        self.disc_num = len(disc_ids) - 1
        self.rerip = False

    def prepare_create(self, disc_id):
        self.uuid = uuid = self.make_uuid()

        self.disc_id = disc_id
        self.disc_ids = [disc_id]
        self.disc_num = 0
        self.saved_disc_ids = list()
        self.rerip = False

        for parent in (IMAGES, DOCUMENTS, SOUND):
            Path(parent, uuid).mkdir()

    def prepare_add(self, disc_id):
        self.disc_id = disc_id
        self.rerip = disc_id in self.disc_ids
        if not self.rerip:
            self.disc_ids.append(disc_id)
        self.disc_num = self.disc_ids.index(disc_id)

    # -Rip---------------------------------------------------------------------
    # Called from ripcd.create.
    def rip_disc(self, disc_id):
        self.prepare_create(disc_id)

        self.do('rip', self.uuid, 0)

    # Called from ripcd.add_cd.
    def add_disc(self, disc_id):
        self.prepare_add(disc_id)

        self.do('rip', self.uuid, self.disc_num)

    def tag_files(self, tags, jpg_data, tracks):
        if self.is_ripping:
            return

        disc_dir = Path(SOUND, self.uuid, str(self.disc_num))
        for track in tracks:
            file_p = Path(disc_dir, f'{track.track_num:02d}.flac')
            tagger = FLAC(str(file_p))

            tagger.update(tags)

            if jpg_data is not None:
                pic = Picture()
                pic.data = jpg_data
                pic.type = id3.PictureType.COVER_FRONT
                pic.mime = 'image/jpeg'
                pic.width = 500
                pic.height = 500
                pic.depth = 16

                tagger.clear_pictures()
                tagger.add_picture(pic)

            tagger['title'] = track.title

            tagger.save()

    # -Import------------------------------------------------------------------
    # Called from importfiles.import_ when filechooser has sound files
    # selected.
    def prepare_import(self, disc_id):
        self.prepare_create(disc_id)

        Path(SOUND, self.uuid, '0').mkdir()

    # Import one track. Called from rawmetadata.import_selected_files.
    def import_track(self, file_dir, file_name):
        src_path = Path(TRANSFER, file_dir, file_name)

        dest_dir = Path(SOUND, self.uuid, str(self.disc_num))
        track_num = len(list(dest_dir.iterdir()))

        dst_path = Path(dest_dir, f'{track_num:02d}{src_path.suffix}')

        shutil.copyfile(src_path, dst_path)

        # Triggers update of display in files.
        self.emit('import-track-finished', self.uuid, self.disc_num, track_num)

        return track_num

    # Called from importfiles.add when filechooser has sound files selected.
    def add_import(self, disc_id):
        self.prepare_add(disc_id)

        # import_track will not overwrite an existing file (it assigns a
        # track_num one greater than the track_num of the last track in the
        # directory). Accordingly, we delete the directory and start fresh.
        if self.rerip:
            shutil.rmtree(Path(SOUND, self.uuid, str(self.disc_num)))

        Path(SOUND, self.uuid, str(self.disc_num)).mkdir()

    # -Other-------------------------------------------------------------------
    def reset(self):
        self.uuid = self.disc_id = None
        self.disc_ids = []

    def rm_zombie(self):
        # rm_zombie gets called at exit. If no tracks were ripped or imported
        # prior to exit, then self.uuid is still None.
        if self.uuid is None:
            return

        if not self.saved_disc_ids:
            for path in (SOUND, IMAGES, DOCUMENTS):
                shutil.rmtree(Path(path, self.uuid), ignore_errors=True)
        else:
            # Remove sound files for unsaved discs.
            top_path = Path(SOUND, self.uuid)
            if top_path.is_dir():
                for i_dir in top_path.iterdir():
                    if int(i_dir.name) >= len(self.saved_disc_ids):
                        shutil.rmtree(Path(SOUND, self.uuid, i_dir.name))

    # -Reply handlers----------------------------------------------------------
    def reply_handler(self, command, args):
        reply_map[command](self, *args)

    @reply
    def on_rip_started(self, uuid, disc_num):
        self.emit('rip-started', uuid, disc_num)

    @reply
    def on_rip_track_started(self, uuid, n_tracks, track_num):
        self.emit('rip-track-started', uuid, n_tracks, track_num)

    @reply
    def on_rip_track_position(self, uuid, disc_num, track_num, position):
        self.emit('rip-track-position', uuid, disc_num, track_num, position)

    @reply
    def on_rip_track_finished(self, uuid, disc_num, track_num):
        self.emit('rip-track-finished', uuid, disc_num, track_num)

    @reply
    def on_rip_finished(self):
        self.emit('rip-finished')

    @reply
    def on_error(self, *message):
        self.emit('rip-error', ' '.join(message))

    @reply
    def on_state(self, state):
        self.state = state

    @reply
    def on_rip_aborted(self):
        self.emit('rip-aborted')
