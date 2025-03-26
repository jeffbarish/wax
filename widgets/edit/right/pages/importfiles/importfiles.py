"""Controls for importing files."""

import hashlib
import os
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from . import doublebutton
from .filechooser import FileChooser
from .rawmetadata import RawMetadata
from common.config import config
from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import NOEXPAND, SND_EXT, TRANSFER
from common.utilities import debug
from ripper import ripper
from widgets import options_button

file_chooser = FileChooser()
raw_metadata = RawMetadata()

PANED_POSITION = config.geometry['import_paned_position']

class ImportFiles(Gtk.Paned):
    @GObject.Signal
    def import_create_clicked(self):
        pass

    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_name('edit-importfiles')
        self.tab_text = 'Import'

        self.add1(file_chooser)
        self.add2(raw_metadata)
        self.set_position(PANED_POSITION)

        box = file_chooser.file_chooser_controls_box
        box.pack_start(doublebutton, *NOEXPAND)
        box.reorder_child(doublebutton, 0)

        self.show_all()

        doublebutton.connect('clicked', self.on_doublebutton_clicked)

        options_button.connect_menuitem('Edit', 'Delete',
                self.on_options_edit_delete_activate)

        register_connect_request('tags-metadata', 'import-finished',
                self.on_import_finished)

    def on_options_edit_delete_activate(self, menuitem):
        doublebutton.config(0, True, False)

    # -Button signal handlers--------------------------------------------------
    def on_doublebutton_clicked(self, doublebutton, label):
        match label:
            case 'Create':
                self.emit('import-create-clicked')

                self.import_()
            case 'Add':
                self.add()

    def on_import_finished(self, rawmetadata):
        doublebutton.config(1, True, True)

    # -Utility methods---------------------------------------------------------
    def import_(self):
        file_dir, filenames = file_chooser.get_selected_files()

        snd_filenames = [f for f in filenames if Path(f).suffix in SND_EXT]
        if snd_filenames:
            disc_id = self.make_disc_id(file_dir, snd_filenames)
            ripper.prepare_import(disc_id)

        all_data = raw_metadata.import_selected_files(file_dir, filenames)
        metadata, tracks, props_rec, props_wrk, images, docs = all_data

        if metadata:
            work_editor = getattr_from_obj_with_name('edit-work-page')
            work_editor.map_metadata(metadata)
            work_editor._work_metadata_changed = True

        if tracks:
            track_editor = getattr_from_obj_with_name('edit-tracks-page')
            work_tracks = [t.track_id for t in tracks]
            track_editor.populate(tracks, work_tracks, [])

        if props_rec or props_wrk:
            props_editor = getattr_from_obj_with_name('edit-properties-page')
            props_editor.populate(props_rec, props_wrk)

        if images:
            image_editor = getattr_from_obj_with_name('edit-images-page')
            image_editor.append_images(images)

        if docs:
            docs_editor = getattr_from_obj_with_name('edit-docs-page')
            docs_editor.append_docs(docs)

        file_chooser.unselect_all()

    def add(self):
        raw_metadata.clear()

        file_dir, filenames = file_chooser.get_selected_files()

        snd_filenames = [f for f in filenames if Path(f).suffix in SND_EXT]
        if snd_filenames:
            disc_id = self.make_disc_id(file_dir, snd_filenames)
            ripper.add_import(disc_id)

        all_data = raw_metadata.import_selected_files(file_dir, filenames)
        _, tracks, _, _, images, docs = all_data

        if tracks:
            track_editor = getattr_from_obj_with_name('edit-tracks-page')
            track_editor.append(tracks)

        if images:
            image_editor = getattr_from_obj_with_name('edit-images-page')
            image_editor.append_images(images)

        if docs:
            docs_editor = getattr_from_obj_with_name('edit-docs-page')
            docs_editor.add_docs(docs)

    # Use the hash of all files in filenames as the disc_id for the import.
    # If the user adds a set of files previously imported, ripper will
    # consider the operation a "rerip".
    def make_disc_id(self, file_dir, filenames):
        hash_func = hashlib.new('sha256')

        for filename in filenames:
            filepath = os.path.join(TRANSFER, file_dir, filename)
            with open(filepath, 'rb') as fo:
                while data := fo.read(8192):
                    hash_func.update(data)

        return hash_func.hexdigest()
