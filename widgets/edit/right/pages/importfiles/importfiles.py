"""Controls for importing files."""

from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib

from . import doublebutton
from .filechooser import FileChooser
from .rawmetadata import RawMetadata
from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import NOEXPAND, SND_EXT
from common.utilities import debug
from ripper import ripper
from widgets import options_button
from widgets import config
from widgets import edit

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
        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)

    def on_options_edit_delete_activate(self, menuitem):
        doublebutton.config(0, True, False)

    # -Button signal handlers--------------------------------------------------
    def on_doublebutton_clicked(self, doublebutton, label):
        match label:
            case 'Create':
                self.emit('import-create-clicked')
                uuid = edit.make_uuid()

                # Prepare ripper with the uuid in case the next operation is
                # Add CD.
                ripper.init_disc(uuid, ['0'])

                self.import_(uuid)
            case 'Add':
                GLib.idle_add(self.add, edit.uuid)

    def on_import_finished(self, rawmetadata):
        doublebutton.config(1, True, True)

    def on_recording_selection_changed(self, selection):
        # See whether a soundfile is already selected.
        file_chooser = getattr_from_obj_with_name('file-chooser')
        file_chooser_treeselection = file_chooser.file_chooser_treeselection
        model, treepaths = file_chooser_treeselection.get_selected_rows()
        snd_selected = any(Path(model[tp][0]).suffix in SND_EXT
                for tp in treepaths)

        model, treeiter = selection.get_selected()
        recording_selected = treeiter is not None
        doublebutton.config(recording_selected, snd_selected, False)

    # -Utility methods---------------------------------------------------------
    def import_(self, uuid):
        file_dir, filenames = file_chooser.get_selected_files()
        all_data = raw_metadata.import_selected_files(uuid, file_dir,
                filenames)
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

    def add(self, uuid):
        raw_metadata.clear()

        file_dir, filenames = file_chooser.get_selected_files()
        all_data = raw_metadata.import_selected_files(uuid, file_dir,
                filenames)
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

