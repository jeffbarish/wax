"""Import files."""

import atexit
import shutil
from pathlib import Path

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

from common.connector import register_connect_request
from common.constants import TRANSFER, IMAGES, DOCUMENTS, SOUND
from common.utilities import debug

class Importer(GObject.Object):
    @GObject.Signal
    def import_track_finished(self, uuid: str, disc_num: int, track_num: int):
        pass

    def __init__(self):
        super().__init__()
        self.uuid = None
        self.saved = False

        atexit.register(self.rm_zombie)

        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)

    def get_name(self):
        return 'importer'

    def import_track(self, uuid, file_dir, file_name):
        if uuid != self.uuid:
            self.rm_zombie()
        if self.uuid is None or uuid != self.uuid:
            for parent in (IMAGES, DOCUMENTS, SOUND):
                Path(parent, uuid).mkdir()
            Path(SOUND, uuid, '0').mkdir()
        self.uuid = uuid

        track_num = self.add_track(uuid, 0, file_dir, file_name)
        return track_num

    def add_track(self, uuid, disc_num, file_dir, file_name):
        self.saved = False

        src_path = Path(TRANSFER, file_dir, file_name)

        dest_dir = Path(SOUND, uuid, str(disc_num))
        track_num = len(list(dest_dir.iterdir()))

        dst_path = Path(dest_dir, f'{track_num:02d}{src_path.suffix}')

        shutil.copyfile(src_path, dst_path)

        self.emit('import-track-finished', uuid, disc_num, track_num)
        return track_num

    def on_save_button_clicked(self, button, label):
        self.saved = True

    def rm_zombie(self):
        if self.uuid is None:
            return

        if not self.saved:
            for parent in (IMAGES, DOCUMENTS, SOUND):
                shutil.rmtree(Path(parent, self.uuid), ignore_errors=True)
            self.uuid = None

