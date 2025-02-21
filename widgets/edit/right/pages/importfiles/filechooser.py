"""The widget for choosing files to import."""

from bisect import insort_left
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import shutil
import subprocess
import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio, Gdk, Pango, Poppler, GdkPixbuf

from mutagen import File
from mutagen import MutagenError

from . import doublebutton
from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import TRANSFER
from common.constants import SND_EXT, JPG_EXT, PDF_EXT
from common.contextmanagers import signal_blocker
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.utilities import debug
from common.utilities import make_time_str
from ripper import ripper
from widgets import options_button

VALID_EXT = SND_EXT + JPG_EXT + PDF_EXT
NEW_FOLDER_NAME = 'new folder'

# As in recordingselector, disconnect the model from the view when
# populating to speed the operation and to eliminate unnecessary signals.
@contextmanager
def no_model(view):
    model = view.get_model()
    selection = view.get_selection()
    with stop_emission(selection, 'changed'):
        view.set_model(None)
    yield
    with stop_emission(selection, 'changed'):
        view.set_model(model)

# monitor sends multiple signals in response to a change in a directory
# (e.g., CREATED and CHANGES_DONE_HINT when creating a directory). The
# usual decorator (emission_stopper) fails because the context manager
# (stop_emission) deletes the _stop_emission flag on receipt of the
# first signal. This decorator unsets the flag when it recognizes
# CHANGES_DONE_HINT. The corresponding context manager merely sets
# the flag, but it preserves consistency with the other context manager.
def monitor_emission_stopper(f):
    @wraps(f)
    def new_f(self, monitor, gio_file, other_file, event_type):
        if getattr(monitor, '_signal_blocker', False):
            if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
                monitor._signal_blocker = False
            return
        return f(self, monitor, gio_file, other_file, event_type)
    return new_f

@contextmanager
def monitor_stop_emission(obj):
    obj._signal_blocker = True
    yield
    pass

@Gtk.Template.from_file('data/glade/edit/right/filechooser.glade')
class FileChooser(Gtk.Box):
    __gtype_name__ = 'file_chooser_box'

    file_chooser_liststore = Gtk.Template.Child()
    file_chooser_treeview = Gtk.Template.Child()
    file_chooser_treeselection = Gtk.Template.Child()
    file_chooser_filenames_treeviewcolumn = Gtk.Template.Child()
    file_chooser_filenames_cellrenderertext = Gtk.Template.Child()
    file_chooser_path_label = Gtk.Template.Child()
    file_chooser_up_button = Gtk.Template.Child()
    file_chooser_newdir_button = Gtk.Template.Child()
    file_chooser_delete_button = Gtk.Template.Child()
    file_chooser_types_label = Gtk.Template.Child()
    file_chooser_controls_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('file-chooser')

        self.current_dir = []

        # Monitor the transfer directory for changes.
        self.monitor = self._monitor_current_dir()

        # Prepare the context menu.
        self.context_menu = context_menu = Gtk.Menu()
        for menu_item_label in ('Open', 'Rename', 'Delete'):
            menu_item = Gtk.MenuItem.new_with_label(menu_item_label)
            context_menu.append(menu_item)
            menu_item.connect('activate',
                    self.on_context_menu_menuitem_activate)
        context_menu.show_all()
        context_menu.attach_to_widget(self.file_chooser_treeview)

        GLib.idle_add(self.populate_file_chooser)

        doublebutton.config(0, False, False)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

        def func(column, cell, model, treeiter, user):
            gray = Gdk.RGBA(0.6, 0.6, 0.6, 1.0)
            white = Gdk.RGBA(0.9, 0.9, 0.9, 1.0)
            valid = model.get_value(treeiter, 3)
            cell.set_property('foreground-rgba', (gray, white)[valid])
        treeviewcolumn = self.file_chooser_filenames_treeviewcolumn
        cellrenderertext = self.file_chooser_filenames_cellrenderertext
        treeviewcolumn.set_cell_data_func(cellrenderertext, func)

        def func(selection, model, path, path_currently_selected, *data):
            name, duration, isdir, valid = model[path]
            return valid
        self.file_chooser_treeselection.set_select_function(func)

        ripper.connect('rip-started', self.on_rip_started)
        ripper.connect('rip-finished', self.on_rip_finished)
        ripper.connect('rip-aborted', self.on_rip_finished)

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)

    def on_options_edit_clear_activate(self, menuitem):
        # Left button should be insensitive until a sound file is selected.
        self.file_chooser_treeselection.unselect_all()
        doublebutton.config(0, False, False)

    @monitor_emission_stopper
    def on_current_directory_changed(self, monitor, gio_file,
            other_file, event_type):
        match event_type:
            case Gio.FileMonitorEvent.CHANGES_DONE_HINT:
                self.populate_file_chooser()
            case Gio.FileMonitorEvent.DELETED:
                if Path(TRANSFER, *self.current_dir).is_dir():
                    self.populate_file_chooser()
                else:
                    # If the current directory got deleted, move up.
                    button = self.file_chooser_up_button
                    self.on_file_chooser_up_button_clicked(button)

    def on_context_menu_menuitem_activate(self, menuitem):
        model, treepaths = self.file_chooser_treeselection.get_selected_rows()

        # If no row is selected, then the click must have been on an invalid
        # row. In that case, the only operation permitted is Delete and
        # self.treepaths got set with the path of the row (in
        # on_file_chooser_treeview_button_press_event).
        if not treepaths:
            with signal_blocker(self.file_chooser_treeselection, 'changed'):
                self._delete(self.treepaths)
            return

        match menuitem.get_label():
            case 'Open':
                name, duration, isdir, valid = model[treepaths[0]]
                if isdir:
                    self._down_dir(name)
                else:
                    # Other possibilities:
                    # xdg-open?
                    # Gio.AppInfo.get_default_for_type(
                    # x = Gio.File.new_for_commandline_arg('alpha.mp3')
                    # x = Gio.AppInfo.get_default_for_type('audio/flac', False)
                    # '/opt/google/chrome/chrome' is another possibility for
                    # jpg and pdf.
                    handlers = {JPG_EXT: ['gwenview'],
                            PDF_EXT: ['okular'],
                            ('.zip',): ['ark'],
                            ('.xlsx', '.ods'): ['libreoffice', '--calc'],
                            SND_EXT: ['play']}
                    for extensions, command in handlers.items():
                        name_fp = Path(TRANSFER, *self.current_dir, name)
                        if name_fp.suffix in extensions:
                            subprocess.Popen([*command, str(name_fp)])
                            break
                    else:
                        raise OSError("No handler found")
            case 'Rename':
                col = self.file_chooser_treeview.get_column(0)
                cellrenderertext = self.file_chooser_filenames_cellrenderertext
                cellrenderertext.props.editable = True
                treeselection = self.file_chooser_treeselection
                with stop_emission(treeselection, 'changed'):
                    self.file_chooser_treeview.set_cursor(treepaths[0], col,
                            True)
            case 'Delete':
                self._delete(treepaths)

    @Gtk.Template.Callback()
    def on_file_chooser_treeview_button_press_event(self, treeview, event):
        if event.type == Gdk.EventType.BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 3:
            # Pop up the menu if we clicked on a row with the right button.
            # Note that clicking on the row even with the right button
            # still selects it, so we can get the row in the handler for
            # the selection (on_file_chooser_treeselection_changed) using
            # get_selected -- unless the row is invalid. In that case,
            # it is impossible to select it, so we save the row in
            # self.treepaths instead.
            x, y = int(event.x), int(event.y)
            row = self.file_chooser_treeview.get_dest_row_at_pos(x, y)
            if row is not None:
                row_path, drop_position = row
                model = self.file_chooser_liststore
                name, duration, isdir, valid = model[row_path]

                menu_items = self.context_menu.get_children()
                if not valid:
                    menu_items[0].set_sensitive(False)
                    menu_items[1].set_sensitive(False)
                    self.treepaths = [row_path]
                    self.file_chooser_types_label.set_text('')
                else:
                    for menu_item in menu_items:
                        menu_item.set_sensitive(True)

                self.context_menu.popup(None, None, None, None, event.button,
                        event.time)

                # Select just this row.
                treeselection = self.file_chooser_treeselection
                with stop_emission(treeselection, 'changed'):
                    treeselection.unselect_all()
                treeselection.select_path(row_path)

                return True

    @Gtk.Template.Callback()
    def on_file_chooser_newdir_button_clicked(self, button):
        def name_found(name):
            return any(row[0] == name
                    for row in self.file_chooser_liststore)
        i, new_folder_name = 0, NEW_FOLDER_NAME
        while name_found(new_folder_name):
            i += 1
            new_folder_name = f'{NEW_FOLDER_NAME}-{i}'

        new_row = (new_folder_name, '', True, True)
        insort_left(self.file_chooser_liststore, new_row, key=self.sort_key)

        # Select the new row.
        self.file_chooser_treeselection.unselect_all()
        for row in self.file_chooser_liststore:
            if row[0] == new_row[0]:
                break
        self.file_chooser_treeselection.select_iter(row.iter)
        self.file_chooser_treeview.scroll_to_cell(row.path, None, True, 0.5)

        with monitor_stop_emission(self.monitor):
            Path(TRANSFER, *self.current_dir, new_folder_name).mkdir()

    @Gtk.Template.Callback()
    def on_edit_import_filenames_cellrenderertext_edited(self, cell, treepath,
            text):
        self.file_chooser_filenames_cellrenderertext.props.editable = False

        oldname, duration, isdir, valid = self.file_chooser_liststore[treepath]
        if text == oldname:
            return

        target = Path(TRANSFER, *self.current_dir, text.strip())
        if target.suffix and target.suffix not in VALID_EXT:
            return

        oldpath = Path(TRANSFER, *self.current_dir, oldname)
        if oldpath.is_file():
            # Do not allow the extension to change.
            target = oldpath.with_stem(target.stem)

        treeselection = self.file_chooser_treeselection
        with stop_emission(treeselection, 'changed'):
            del self.file_chooser_liststore[treepath]

        new_row = (target.name, duration, isdir, valid)
        insort_left(self.file_chooser_liststore, new_row,
                key=self.sort_key)

        # Find and select new_row.
        for row in self.file_chooser_liststore:
            if row[0] == target.name:
                with stop_emission(treeselection, 'changed'):
                    treeselection.unselect_all()
                    treeselection.select_iter(row.iter)
                    treeview = self.file_chooser_treeview
                    treeview.scroll_to_cell(row.path, None, True, 0.5)
                break

        with monitor_stop_emission(self.monitor):
            oldpath.rename(target)
        doublebutton.config(None, True, False)

    @Gtk.Template.Callback()
    def on_file_chooser_filenames_cellrenderertext_editing_canceled(self,
                cellrenderer):
        self.file_chooser_filenames_cellrenderertext.props.editable = False

    @Gtk.Template.Callback()
    def on_file_chooser_delete_button_clicked(self, button):
        model, treepaths = self.file_chooser_treeselection.get_selected_rows()
        self._delete(treepaths)

    @Gtk.Template.Callback()
    def on_file_chooser_up_button_clicked(self, button):
        old_dir = self.current_dir[-1]
        del self.current_dir[-1]
        self.populate_file_chooser()
        self.file_chooser_up_button.set_sensitive(len(self.current_dir) > 0)
        label_text = '/' + '/'.join(self.current_dir)
        self.file_chooser_path_label.set_text(label_text)
        self._set_delete_button_sensitive()
        self.monitor = self._monitor_current_dir()
        self.file_chooser_types_label.set_text('')

        # Select the row with the directory we just exited.
        for row in self.file_chooser_liststore:
            if row[0] == old_dir:
                treeselection = self.file_chooser_treeselection
                with stop_emission(treeselection, 'changed'):
                    treeselection.select_iter(row.iter)
                treeview = self.file_chooser_treeview
                treeview.scroll_to_cell(row.path, None, True, 0.5)
                break

        doublebutton.config(None, False, False)

    @Gtk.Template.Callback()
    @emission_stopper()
    def on_file_chooser_treeselection_changed(self, selection):
        model, treepaths = selection.get_selected_rows()
        if not treepaths:
            self._set_delete_button_sensitive()
            self.file_chooser_types_label.set_text('')
            doublebutton.config(None, False, False)
            return

        name, duration, isdir, valid = model[treepaths[0]]
        name_fp = Path(TRANSFER, *self.current_dir, name)
        if name_fp.is_dir():
            self._down_dir(name)
            self._set_delete_button_sensitive()
            self.file_chooser_types_label.set_text('')
            return
        self._set_delete_button_sensitive()

        # The first row gets selected on startup. Prevent that selection by
        # setting can-focus to False on the treeview. It gets set to True here
        # so that ctrl-click works for deselecting.
        self.file_chooser_treeview.set_can_focus(True)

        # Create label describing file types selected.
        suffix_map = {'sound': SND_EXT, 'image': JPG_EXT, 'doc': PDF_EXT}
        suffixes = [Path(model[tp][0]).suffix for tp in treepaths]
        label_l = []
        for key, val in suffix_map.items():
            if any(suffix in val for suffix in suffixes):
                label_l.append(key)
        label = ', '.join(label_l)
        self.file_chooser_types_label.set_text(label)

        self.config_doublebutton()

    def on_rip_started(self, ripper, uuid, disc_num):
        self.config_doublebutton()

    def on_rip_finished(self, ripper):
        self.config_doublebutton()

    def on_recording_selection_changed(self, selection):
        self.config_doublebutton()

    def config_doublebutton(self):
        model, treepaths = self.file_chooser_treeselection.get_selected_rows()
        filechooser_has_selection = bool(treepaths)
        filechooser_has_snd = \
                any(Path(model[tp][0]).suffix in SND_EXT for tp in treepaths)
        is_ripping = ripper.is_ripping

        track_treestore = getattr_from_obj_with_name(
                'edit-tracks-page.track_treestore')
        recording_has_snd = bool(len(track_treestore))

        label_add = is_ripping or recording_has_snd

        left_sensitive = not is_ripping and filechooser_has_snd \
                or label_add and filechooser_has_selection \
                    and not filechooser_has_snd

        right_sensitive = not is_ripping \
                and recording_has_snd and filechooser_has_snd

        doublebutton.config(label_add, left_sensitive, right_sensitive)

    def yield_directory_content(self):
        for name_fp in Path(TRANSFER, *self.current_dir).iterdir():
            name = str(name_fp.name)
            if name_fp.is_dir():
                row = (name, '', True, True)
            elif name_fp.suffix in PDF_EXT:
                fileuri = name_fp.absolute().as_uri()
                try:
                    Poppler.Document.new_from_file(fileuri, None)
                except GLib.GError as e:
                    valid = False
                else:
                    valid = True
                row = (name, '', False, valid)
            elif name_fp.suffix in JPG_EXT:
                try:
                    GdkPixbuf.Pixbuf.new_from_file(str(name_fp))
                except GLib.GError as e:
                    valid = False
                else:
                    valid = True
                row = (name, '', False, valid)
            elif name_fp.suffix in ('.wav', '.flac', '.ogg', '.mp3'):
                try:
                    snd_file = File(name_fp)
                except MutagenError as e:
                    valid = False
                else:
                    valid = True
                row = (name, '', False, valid)
            else:
                row = (name, '', False, False)

            yield row

    def populate_file_chooser(self):
        with no_model(self.file_chooser_treeview):
            self.file_chooser_liststore.clear()

            rows = list(self.yield_directory_content())
            rows.sort(key=self.sort_key)

            for row in rows:
                self.file_chooser_liststore.append(row)

        self.file_chooser_delete_button.set_sensitive(False)
        doublebutton.config(None, False, False)

    # Used by importfiles.import_.
    def unselect_all(self):
        self.file_chooser_treeselection.unselect_all()

    def get_selected_files(self):
        selection = self.file_chooser_treeselection
        model, treepaths = selection.get_selected_rows()
        file_dir = self.file_chooser_path_label.get_text().lstrip('/')
        return file_dir, [model[treepath][0] for treepath in treepaths
                if model[treepath][3]]  # return only valid selected files

    def _down_dir(self, name):
        self.current_dir.append(name)
        self.populate_file_chooser()
        self.file_chooser_up_button.set_sensitive(True)
        label_text = '/' + '/'.join(self.current_dir)
        self.file_chooser_path_label.set_text(label_text)
        doublebutton.config(None, False, False)
        GLib.idle_add(self.file_chooser_types_label.set_text, '')

        self.monitor = self._monitor_current_dir()

    def _set_delete_button_sensitive(self):
        selection = self.file_chooser_treeselection
        model, treepaths = selection.get_selected_rows()

        something_selected = bool(treepaths)
        dir_selected = any(model[p][2] for p in treepaths)
        empty_dir = not len(self.file_chooser_liststore)

        sensitive = empty_dir or something_selected and not dir_selected
        self.file_chooser_delete_button.set_sensitive(sensitive)

    def _delete(self, paths):
        current_fp = Path(TRANSFER, *self.current_dir)
        if not paths:
            # Delete current directory.
            current_fp.rmdir()
            self.on_file_chooser_up_button_clicked(self.file_chooser_up_button)
            return

        liststore = self.file_chooser_liststore
        if len(paths) == 1:
            # Delete selected directory.
            name, duration, isdir, valid = liststore[paths[0]]
            del_fp = Path(current_fp, name)
            if del_fp.is_dir():
                # Delete the selected directory (and its contents).
                shutil.rmtree(str(del_fp))
                return

        # Delete selected files.
        with stop_emission(self.file_chooser_treeselection, 'changed'):
            for path in reversed(paths):
                name, duration, isdir, valid = liststore[path]
                del_fp = Path(current_fp, name)
                if not del_fp.is_dir():
                    del liststore[path]
                    del_fp.unlink()
        self.file_chooser_treeselection.unselect_all()

    def _monitor_current_dir(self):
        current_dir = str(Path(TRANSFER, *self.current_dir))
        gio_file = Gio.File.new_for_path(current_dir)
        flags = Gio.FileMonitorFlags.NONE
        monitor = gio_file.monitor_directory(flags, None)
        self.handler_id = monitor.connect('changed',
                self.on_current_directory_changed)
        return monitor

    def sort_key(self, row):
        suffix_sort = ['.wav', '.flac', '.ogg', '.mp3',
                '.jpg', '.jpeg',
                '.pdf',
                '.zip',
                '.ods']

        if row[2]:  # directories go first...
            type_key = -1
        else:       # ...and then files sort by suffix
            try:
                type_key = suffix_sort.index(Path(row[0]).suffix)
            except ValueError:
                type_key = sys.maxsize
        return (type_key, row[0])

