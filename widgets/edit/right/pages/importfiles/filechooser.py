"""The widget for choosing files to import."""

from pathlib import Path
import shutil
import subprocess

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio, Gdk, Pango

from mutagen import File
from mutagen import MutagenError

from . import doublebutton
from common.connector import getattr_from_obj_with_name
from common.connector import stop_emission, add_emission_stopper
from common.connector import signal_blocker
from common.connector import QuietProperty
from common.constants import TRANSFER
from common.constants import SND_EXT, JPG_EXT, PDF_EXT
from common.utilities import debug
from common.utilities import make_time_str
from ripper import ripper
from widgets import options_button

VALID_EXT = SND_EXT + JPG_EXT + PDF_EXT

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

        self.file_chooser_liststore.set_default_sort_func(self._sort_func)
        self.file_chooser_liststore.set_sort_column_id(
                Gtk.TREE_SORTABLE_DEFAULT_SORT_COLUMN_ID,
                Gtk.SortType.ASCENDING)

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
            val = model.get_value(treeiter, 3)
            style = (Pango.Style.ITALIC, Pango.Style.NORMAL)[int(val)]
            cell.set_property('style', style)
        treeviewcolumn = self.file_chooser_filenames_treeviewcolumn
        cellrenderertext = self.file_chooser_filenames_cellrenderertext
        treeviewcolumn.set_cell_data_func(cellrenderertext, func)

        ripper.connect('rip-started', self.on_rip_started)
        ripper.connect('rip-finished', self.on_rip_finished)
        ripper.connect('rip-aborted', self.on_rip_finished)

    def on_rip_started(self, ripper, uuid, disc_num):
        doublebutton.config(1, self.snd_is_selected(), False)

    def on_rip_finished(self, ripper):
        model, treepaths = self.file_chooser_treeselection.get_selected_rows()
        suffix_map = {'sound': SND_EXT, 'image': JPG_EXT, 'doc': PDF_EXT}
        suffixes = [Path(model[tp][0]).suffix for tp in treepaths]
        label_l = []
        for key, val in suffix_map.items():
            if any(suffix in val for suffix in suffixes):
                label_l.append(key)

        sensitive = self.snd_is_selected()
        doublebutton.config(None, sensitive, sensitive)

    def on_options_edit_clear_activate(self, menuitem):
        # Left button should be insensitive until a sound file is selected.
        self.file_chooser_treeselection.unselect_all()
        doublebutton.config(0, False, False)

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
            # Pop up the menu if we clicked on a row. Note that clicking on
            # the row selects it, so we can get the row in the handler for
            # the selection using get_selected.
            x, y = int(event.x), int(event.y)
            row = self.file_chooser_treeview.get_dest_row_at_pos(x, y)
            if row is not None:
                row_path, drop_position = row
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
        new_row = ('new folder', '', True, True)
        treeiter = self.file_chooser_liststore.append(new_row)

        # Go into edit mode on the name of the new directory.
        path = self.file_chooser_liststore.get_path(treeiter)
        col = self.file_chooser_treeview.get_column(0)
        self.file_chooser_treeview.scroll_to_cell(path)
        self.file_chooser_treeview.set_cursor(path, col, True)

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

        if oldname == 'new folder':
            target.mkdir()
            self._down_dir(text)
            return

        oldpath = Path(TRANSFER, *self.current_dir, oldname)
        if oldpath.is_file():
            # Do not allow the extension to change.
            target = oldpath.with_stem(target.stem)
        self.file_chooser_liststore[treepath] = \
                (target.name, duration, isdir, valid)

        # Rename changes the TRANSFER directory. The handler for the monitor
        # does a populate, which negates selection of the item being renamed.
        # We need to block the handler, but the complication is that monitor
        # produces the changed signal a short time after the rename, by which
        # time we have already exited the context.
        with signal_blocker(self.monitor, 'changed'):
            oldpath.rename(target)

            # Iterate the event loop to consume the event produced by monitor
            # before unblocking its handler on the way out of the context.
            while Gtk.events_pending():
                Gtk.main_iteration()

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
        self.file_chooser_delete_button.set_sensitive(False)
        self.monitor = self._monitor_current_dir()
        self.file_chooser_types_label.set_text('')

        # Select the row with the directory we just exited.
        for row in self.file_chooser_liststore:
            if row[0] == old_dir:
                self.file_chooser_treeview.scroll_to_cell(row.path)
                break

        doublebutton.config(None, False, False)

    @Gtk.Template.Callback()
    @add_emission_stopper()
    def on_file_chooser_treeselection_changed(self, selection):
        model, treepaths = selection.get_selected_rows()
        if not treepaths:
            self.file_chooser_delete_button.set_sensitive(False)
            self.file_chooser_types_label.set_text('')
            doublebutton.config(None, False, False)
            return

        name, duration, isdir, valid = model[treepaths[0]]
        name_fp = Path(TRANSFER, *self.current_dir, name)
        if name_fp.is_dir():
            self._down_dir(name)
            return
        self.file_chooser_delete_button.set_sensitive(True)

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

        for suffix in ('doc', 'image'):
            names = []
            for tp in treepaths:
                filename = Path(model[tp][0])
                if filename.suffix in suffix_map[suffix]:
                    names.append(str(Path(*self.current_dir, filename)))
            setattr(self, f'_{suffix}_filenames', names)

        revise_mode = getattr_from_obj_with_name(
                'edit-left-notebook.revise_mode')

        # The label can be either Import or Add if a sound file is
        # selected. Otherwise, it must be Add.
        label = None if self.snd_is_selected() else 1

        # Sensitizing the right button makes it possible to select Import,
        # but Import is permissible only if a sound file is selected and
        # no rip is underway.
        right_sensitive = self.snd_is_selected() and not ripper.is_ripping

        # Left is sensitive if something is selected.
        left_sensitive = bool(treepaths)

        doublebutton.config(label, left_sensitive, right_sensitive)

    def snd_is_selected(self):
        model, treepaths = self.file_chooser_treeselection.get_selected_rows()
        return any(Path(model[tp][0]).suffix in SND_EXT for tp in treepaths)

    def populate_file_chooser(self):
        with stop_emission(self.file_chooser_treeselection, 'changed'):
            self.file_chooser_liststore.clear()

        for name_fp in Path(TRANSFER, *self.current_dir).iterdir():
            name = str(name_fp.name)
            if name_fp.is_dir():
                row = (name, '', True, True)
            elif name_fp.suffix in JPG_EXT + PDF_EXT + ('.ods',):
                row = (name, '', False, True)
            elif name_fp.suffix in ('.wav', '.flac', '.ogg', '.mp3'):
                try:
                    snd_file = File(name_fp)
                except MutagenError as e:
                    message = f'Error reading header of {name_fp} ({e})'
                    print(message)
                    duration = 0.0
                    valid = False
                # It is possible that remotefilechooser will attempt to
                # list the directory while the OS is copying files into
                # transfer.  In that case, the header might be incomplete.
                except EOFError as e:
                    message = f'EOFError reading header: {e}'
                    print(message)
                    duration = 0.0
                    valid = False
                else:
                    # Even after all the error handling, it seems that
                    # snd_file can still be None.
                    try:
                        duration = snd_file.info.length
                    except AttributeError:
                        duration = 0.0
                        valid = False
                    else:
                        valid = True
                row = (name, make_time_str(duration), False, valid)
            else:
                row = (name, '', False, False)
            self.file_chooser_liststore.append(row)

        if not len(self.file_chooser_liststore):
            self.file_chooser_delete_button.set_sensitive(True)

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

    def _delete(self, paths):
        current_fp = Path(TRANSFER, *self.current_dir)
        if not paths:
            # Delete current directory.
            current_fp.rmdir()
            self.on_file_chooser_up_button_clicked(self.file_chooser_up_button)
            return

        model = self.file_chooser_liststore
        if len(paths) == 1:
            # Delete selected directory.
            name, duration, isdir, valid = model[paths[0]]
            del_fp = Path(current_fp, name)
            if del_fp.is_dir():
                # Delete the selected directory (and its contents).
                shutil.rmtree(str(del_fp))
                return

        # Delete selected files.
        with stop_emission(self.file_chooser_treeselection, 'changed'):
            for path in reversed(paths):
                name, duration, isdir, valid = model[path]
                del_fp = Path(current_fp, name)
                if not del_fp.is_dir():
                    del model[path]
                    del_fp.unlink()

    def _monitor_current_dir(self):
        current_dir = str(Path(TRANSFER, *self.current_dir))
        gio_file = Gio.File.new_for_path(current_dir)
        flags = Gio.FileMonitorFlags.NONE
        monitor = gio_file.monitor_directory(flags, None)
        monitor.connect('changed', self.on_current_directory_changed)
        return monitor

    def _sort_func(self, model, a, b, x):
        suffix_sort = ['.wav', '.flac', '.ogg', '.mp3',
                '.jpg',
                '.pdf',
                '.ods',
                '']
        def get_index(suffix):
            if suffix in suffix_sort:
                return suffix_sort.index(suffix)
            else:
                return len(suffix_sort)

        # Directory names get listed last.
        dir_a, dir_b = model[a][2], model[b][2]
        if dir_a and not dir_b:
            return 1
        if dir_b and not dir_a:
            return -1

        path_a, path_b = Path(model[a][0]), Path(model[b][0])
        suffix_a, suffix_b = path_a.suffix, path_b.suffix
        if suffix_a != suffix_b:
            return get_index(suffix_a) - get_index(suffix_b)

        # Suffixes are equal. Sort by stem.
        stem_a, stem_b = path_a.stem, path_b.stem
        if stem_a == stem_b:
            return 0
        if stem_a > stem_b:
            return 1
        return -1

