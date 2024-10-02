"""Ripper is the interface to the rest of the program for rip functionality."""

# Consider proxy object
# (https://docs.python.org/3/library/multiprocessing.html#proxy-objects)

import atexit
import shutil
from pathlib import Path

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject
from mutagen.flac import FLAC

from common.connector import register_connect_request
from common.constants import IMAGES, DOCUMENTS, SOUND
from common.enginelauncher import EngineLauncher
from common.utilities import debug
from widgets import options_button

# Decorator to register methods that respond to replies from engine.
reply_map = {}
# This version of the decorator provides tracing information.
# def reply(f):
#     reply = f.__name__[3:].replace('_', '-')
#     def new_f(self, *args):
#         if reply != 'rip-track-position':
#             print('ripper: received reply', reply, args)
#         return f(self, *args)
#     reply_map[reply] = new_f
#     return new_f
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

    # -------------------------------------------------------------------------
    # init_disc gets called in editnotebook when populating edit mode with
    # an existing recording. It prepares ripper to do a rerip or add_disc.
    def init_disc(self, uuid, disc_ids):
        self.uuid = uuid
        self.disc_ids = list(disc_ids)
        self.saved_disc_ids = list(disc_ids)
        self.disc_id = self.disc_ids[-1]
        self.disc_num = len(disc_ids) - 1
        self.rerip = False

    def rip_disc(self, uuid, disc_id):
        # Selecting a recording triggers a call to init_disc, which sets
        # self.uuid (so it is not None). Clicking Create triggers creation
        # of a new uuid. ripcd calls this method with the new uuid, so
        # uuid != self.uuid. Accordingly, we call rm_zombie here. However,
        # rm_zombie does not remove the self.uuid tree because init_disc
        # also copied the discids to saved_disc_ids.
        if uuid != self.uuid:
            self.rm_zombie()

        self.uuid = uuid
        self.disc_id = disc_id
        self.disc_ids = [disc_id]
        self.disc_num = 0
        self.saved_disc_ids = list()
        self.rerip = False

        for parent in (IMAGES, DOCUMENTS, SOUND):
            Path(parent, uuid).mkdir()

        self.do('rip', uuid, 0)

    # It is permissible to add a CD that was already ripped (in which case
    # we re-rip it). Note that uuid for additional discs is the same as the
    # one set on the initial rip_disc. Also, init_disc sets the uuid to the
    # selected recording if no edit is underway in case the user wants to
    # rerip tracks of or add tracks to an existing recording.
    def add_disc(self, disc_id):
        self.disc_id = disc_id
        self.rerip = rerip = disc_id in self.disc_ids
        if not rerip:
            self.disc_ids.append(disc_id)

        self.disc_num = self.disc_ids.index(disc_id)
        self.do('rip', self.uuid, self.disc_num)

        return rerip

    def tag_files(self, tags, tracks):
        disc_dir = Path(SOUND, self.uuid, str(self.disc_num))
        for track_p in disc_dir.glob('*.flac'):
            track_num = int(track_p.stem)
            track = tracks[track_num]
            tags.update(title=track.title)

            tagger = FLAC(str(track_p))
            tagger.update(tags)
            tagger.save()

    def add_picture(self, picture):
        disc_dir = Path(SOUND, self.uuid, str(self.disc_num))
        for track_p in disc_dir.glob('*.flac'):
            tagger = FLAC(str(track_p))
            tagger.clear_pictures()
            tagger.add_picture(picture)
            tagger.save()

    def reset(self):
        self.uuid = self.disc_id = None
        self.disc_ids = []

    def rm_zombie(self):
        if self.uuid is None:  # happens only on the first rip
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
