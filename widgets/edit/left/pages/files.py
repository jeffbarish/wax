"""A form for displaying files associated with a recording."""

from datetime import datetime
from pathlib import Path
from typing import List

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango

from common.constants import SOUND, DOCUMENTS, IMAGES, SND_EXT, NOEXPAND
from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.utilities import debug
from ripper import ripper

def get_size_mtime(snd_path):
    stat = snd_path.stat()
    mtime_fmt = '%Y %b %d %H:%M:%S'
    mtime = datetime.fromtimestamp(stat.st_mtime).strftime(mtime_fmt)
    size = f'{stat.st_size / 1e6:.2f}'
    return size, mtime

@Gtk.Template.from_file('data/glade/edit/left/files.glade')
class FilesEditor(Gtk.Box):
    __gtype_name__ = 'edit_files_box'

    uuid_label = Gtk.Template.Child()
    uuid_edit_copy_button = Gtk.Template.Child()
    edit_files_tracks_list_box = Gtk.Template.Child()
    edit_files_other_list_box = Gtk.Template.Child()
    total_size_label = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.tab_text = 'Files'
        self.track_ids = []

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        # FilesListTreeView is going to manage total_size_label, so make
        # total_size_label a class variable of that class.
        FilesListTreeView.total_size_label = self.total_size_label

        # The list boxes for images and for documents (the 'other' category)
        # always exist, so create them here.
        for list_box_type in ('Images', 'Documents'):
            list_box = ListBox()
            list_box.set_label_text(list_box_type)
            self.edit_files_other_list_box.pack_start(list_box, False, 0, 0)
            list_box.hide()

        register_connect_request('ripper', 'rip-started',
                self.on_rip_started)
        register_connect_request('ripper', 'rip-track-position',
                self.on_rip_track_position)
        register_connect_request('ripper', 'rip-track-finished',
                self.on_rip_track_finished)
        register_connect_request('ripper', 'rip-aborted',
                self.on_rip_aborted)
        register_connect_request('tags-metadata', 'import-started',
                self.on_import_started)
        register_connect_request('importer', 'import-track-finished',
                self.on_import_track_finished)
        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)
        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)

    @Gtk.Template.Callback()
    def on_uuid_edit_copy_button_clicked(self, button):
        text = self.uuid_label.get_text()
        self.clipboard.set_text(text, -1)

    def on_recording_saved(self, editnotebook, genre):
        self.clear()
        recording = editnotebook.recording
        work_num = editnotebook.work_num
        work = recording.works[work_num]
        self.track_ids = track_ids = work.track_ids
        self.populate(recording.uuid, track_ids)

    def on_abort_button_clicked(self, button):
        if ripper.disc_num == 0 and not ripper.rerip:
            self.clear()

    # -Rip handlers------------------------------------------------------------
    def on_rip_started(self, ripper, uuid, disc_num):
        self.uuid_label.set_text(uuid)
        self.uuid_edit_copy_button.show()
        self.trackslistbox = self.get_trackslistbox(disc_num)
        self.trackslistbox.show_all()

    def on_rip_track_position(self, ripper, uuid, disc_num, track_num,
            position):
        self.refresh_trackslist(uuid, disc_num)

    def on_rip_track_finished(self, ripper, uuid, disc_num, track_num):
        self.refresh_trackslist(uuid, disc_num)

    def on_rip_aborted(self, ripper):
        if ripper.disc_num == 0 and not ripper.rerip:
            editnotebook = getattr_from_obj_with_name('edit-left-notebook')
            if not editnotebook.revise_mode:
                # We just aborted the initial rip of the first disc and
                # the recording was not saved (we are in create mode), so
                # clear everything. Handlers for abort_button clicked in
                # ripper.ripper and ripper.engine take care of deleting files.
                self.clear()
            # If we are in revise mode, files will be re-populated by a call
            # of editnotebook.populate_forms_from_selection, so either way
            # we are done for this case.
            return

        if ripper.rerip:
            # We just aborted a rerip, so update to get rid of the entry for
            # the .part file.
            self.refresh_trackslist(ripper.uuid, ripper.disc_num)
        else:
            # We just aborted the initial rip of the non-first disc, so
            # hide the trackslistbox for disc_num (the last trackslistbox).
            children = self.edit_files_tracks_list_box.get_children()
            trackslistbox = children[-1]
            trackslistbox.hide()
            FilesListTreeView.update_total_size()

    # -Import handlers---------------------------------------------------------
    def on_import_started(self, importer, uuid, disc_num):
        self.uuid_label.set_text(uuid)
        self.uuid_edit_copy_button.show()
        self.trackslistbox = self.get_trackslistbox(disc_num)
        self.trackslistbox.show_all()

    def on_import_track_finished(self, importer, uuid, disc_num, track_num):
        self.refresh_trackslist(uuid, disc_num)

    # populate is called in editnotebook.on_recording_selection_changed when
    # the recording selection changes. The recording selection changes also
    # when editnotebook saves a new recording and calls selector.set_selection.
    # In that case, we populate Files with a snapshot of the sound directory
    # which might not be complete as a rip could still be underway. If a rip
    # is underway, the handler for rip-track-position (in TracksListBox) will
    # update the snapshot as the rip progresses.
    def populate(self,
            uuid: str,
            track_ids: List[tuple]):
        self.track_ids = track_ids

        path = Path(SOUND, uuid)
        if not path.is_dir():
            self.uuid_label.set_text('Sound files directory not found')
            self.uuid_edit_copy_button.hide()
            return

        self.uuid_label.set_text(uuid)
        self.uuid_edit_copy_button.show()

        for subdir in sorted(path.iterdir()):
            disc_num_str = subdir.name
            trackslistbox = self.get_trackslistbox(int(disc_num_str))
            trackslistbox.show_all()
            for sf_path in sorted(subdir.iterdir()):
                if sf_path.suffix not in SND_EXT:
                    continue
                file_size, mtime = get_size_mtime(sf_path)
                t = (int(disc_num_str), int(sf_path.stem))
                dim = t not in track_ids
                row = (sf_path.name, file_size, mtime, dim)
                trackslistbox.append(row)

        for main_dir, listbox in zip((IMAGES, DOCUMENTS),
                self.edit_files_other_list_box.get_children()):
            path = Path(main_dir, uuid)
            if file_list := list(path.iterdir()):
                listbox.show_all()
                for sf_path in sorted(file_list):
                    if sf_path.name.startswith('thumbnail'):
                        continue
                    file_size, mtime = get_size_mtime(sf_path)
                    row = (sf_path.name, file_size, mtime, False)
                    listbox.append(row)

        FilesListTreeView.update_total_size()

    def refresh_trackslist(self, uuid, disc_num):
        trackslistbox = self.get_trackslistbox(disc_num)
        trackslistbox.files_list_treeview.files_list_liststore.clear()

        path = Path(SOUND, uuid, str(disc_num))

        # If we are ripping the last disc, then ripper deletes the path
        # folder on abort_button clicked. If a rip-track-position signal
        # got queued immediately after the abort_button clicked, then we
        # could come here after path is deleted.
        if not path.is_dir():
            return

        for sf_path in sorted(path.iterdir()):
            # If the part file name.flac.part got deleted before we arrived
            # here, then try getting the size of name.flac.
            try:
                file_size, mtime = get_size_mtime(sf_path)
            except FileNotFoundError:
                sf_path = Path(str(sf_path).removesuffix('.part'))
                try:
                    file_size, mtime = get_size_mtime(sf_path)
                except FileNotFoundError:
                    # If name.flac is not present either, something is
                    # wrong. Skip to the next sf_path.
                    continue

            if sf_path.suffix == '.part':
                dim = True
            else:
                t = (disc_num, int(sf_path.stem))
                dim = t not in self.track_ids
            row = (sf_path.name, file_size, mtime, dim)
            trackslistbox.append(row)

        FilesListTreeView.update_total_size()

    def get_trackslistbox(self, disc_num):
        children = self.edit_files_tracks_list_box.get_children()
        try:
            return children[disc_num]
        except IndexError:
            new_trackslistbox = TracksListBox(disc_num)
            new_trackslistbox.set_label_text(str(disc_num))
            self.edit_files_tracks_list_box.pack_start(new_trackslistbox,
                    False, 0, 0)
            return new_trackslistbox

    def clear(self):
        self.uuid_label.set_text('')
        self.uuid_edit_copy_button.hide()
        for box in (self.edit_files_tracks_list_box,
                self.edit_files_other_list_box):
            for listbox in box.get_children():
                listbox.hide()
                listbox.files_list_liststore.clear()
        FilesListTreeView.update_total_size()
        self.track_ids = []

# Put FilesListTreeView in a box with a label for a title.
class ListBox(Gtk.Box):
    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.VERTICAL)

        # Set title_label color to #66668383d9d9 and font to Monospace 9.
        attr = Pango.attr_foreground_new(0x6666, 0x8383, 0xd9d9)
        attrs = Pango.AttrList.new()
        attrs.insert(attr)
        font_description = Pango.FontDescription.from_string('Monospace 9')
        attr = Pango.attr_font_desc_new(font_description)
        attrs.insert(attr)

        self.title_label = title_label = Gtk.Label()
        title_label.set_xalign(0.0)
        title_label.set_margin_start(4)
        title_label.set_attributes(attrs)

        self.pack_start(title_label, *NOEXPAND)

        self.files_list_treeview = FilesListTreeView()
        self.pack_start(self.files_list_treeview, True, True, 0)

    def set_label_text(self, text):
        self.title_label.set_text(text)

    # Delegate any unknown attributes (e.g., append) to FilesListTreeView.
    def __getattr__(self, attr):
        return getattr(self.files_list_treeview, attr)

# Subclass has stuff specifically for the tracks lists.
class TracksListBox(ListBox):
    def __init__(self, disc_num):
        super().__init__()
        self.disc_num = disc_num
        self.title_label.set_text(f'Disc {disc_num + 1}')

    def set_label_text(self, text):
        self.title_label.set_text(f'Disc {int(text) + 1}')

@Gtk.Template.from_file('data/glade/edit/left/files_treeview.glade')
class FilesListTreeView(Gtk.TreeView):
    __gtype_name__ = 'edit_files_treeview'

    # Keep track of all the liststores created so that update_total_size can
    # cycle through them to compute the total size.
    liststores = []

    # FilesEditor gets total_size_label from the Glade specification, but it
    # writes it to this class variable so that update_total_size can update it.
    total_size_label = None

    def __init__(self):
        super().__init__()

        # fname, file_size, mtime, dim
        _types = [str, str, str, bool]
        self.files_list_liststore = Gtk.ListStore.new(_types)
        self.set_model(self.files_list_liststore)
        FilesListTreeView.liststores.append(self.files_list_liststore)

        self.set_headers_visible(False)
        self.selection = self.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.NONE)

        color = Gdk.RGBA()
        def func(column, cell, model, treeiter, *data):
            dim = model.get_value(treeiter, 3)
            color.parse(('#dddddd', '#888888')[dim])
            cell.props.foreground_rgba = color

        for col in self.get_columns():
            for cell in col.get_cells():
                col.set_cell_data_func(cell, func)

    def append(self, new_row):
        self.files_list_liststore.append(new_row)

    @classmethod
    def update_total_size(cls):
        total_size = 0.0
        for liststore in cls.liststores:
            for row in liststore:
                if not row[0].endswith('.part'):
                    total_size += float(row[1])
        total_size_text = f'Total size: {total_size:.2f}' if total_size else ''
        FilesListTreeView.total_size_label.set_text(total_size_text)


page_widget = FilesEditor()

