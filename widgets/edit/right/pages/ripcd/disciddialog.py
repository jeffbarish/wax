"""This dialog advises users that a CD has already been ripped. It presents
a list of the works based on tracks from the CD. Clicking on one of the works
in the list selects the work and configures the doublebutton in Rip CD to
Add so that Wax is configured to re-rip the CD."""

from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Pango, GLib
from gi.repository.GdkPixbuf import Pixbuf

from . import doublebutton
from common.config import config
from common.connector import getattr_from_obj_with_name
from common.constants import EXPAND, NOEXPAND, IMAGES, IMAGES_DIR
from common.utilities import debug

message1 = '<span weight=\"bold\" size=\"larger\">This CD was already ' \
        'ripped.</span>'

message2a = '''The work below was created from this CD.
If you want to rerip, select the work and then use the Add
action in Edit mode.'''
message2b = '''The works below were created from this CD.
If you want to rerip, select one of the works and then use
the Add action in Edit mode.'''

class DiscidDialog(Gtk.Dialog):
    __gtype_name__ = 'discid_dialog'

    def __init__(self, parent, recording):
        super().__init__()
        self.set_default_size(370, 200)
        self.vbox.set_spacing(6)

        label1 = Gtk.Label.new(message1)
        label1.set_use_markup(True)
        label1.set_xalign(0.5)
        self.vbox.pack_start(label1, *NOEXPAND)

        message2 = message2a if len(recording.works) == 1 else message2b
        label2 = Gtk.Label.new(message2)
        label2.set_xalign(0.0)
        label2.set_margin_top(10)
        self.vbox.pack_start(label2, *NOEXPAND)

        self.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)

        liststore = Gtk.ListStore.new([Pixbuf, str, str, str, int, object])
        treeview = Gtk.TreeView.new_with_model(liststore)
        treeview.set_headers_visible(False)
        treeview.set_vexpand(False)
        self.vbox.pack_start(treeview, *EXPAND)

        treeselection = treeview.get_selection()
        treeselection.set_mode(Gtk.SelectionMode.NONE)

        treeselection.connect('changed', self.on_selection_changed)

        cell0 = Gtk.CellRendererPixbuf.new()
        col0 = Gtk.TreeViewColumn.new()
        col0.pack_start(cell0, False)
        col0.add_attribute(cell0, 'pixbuf', 0)
        treeview.append_column(col0)

        cell1 = Gtk.CellRendererText.new()
        cell1.set_property('ellipsize', Pango.EllipsizeMode.END)
        col1 = Gtk.TreeViewColumn.new()
        col1.pack_start(cell1, True)
        col1.add_attribute(cell1, 'text', 1)
        treeview.append_column(col1)

        top_level = parent.get_toplevel()
        self.set_transient_for(top_level)

        self.show_all()

        uuid = recording.uuid
        filename = Path(IMAGES, uuid, 'thumbnail-00.jpg')
        if not filename.exists():
            filename = Path(IMAGES_DIR, 'noimage_thumbnail.png')
        thumbnail_pb = Pixbuf.new_from_file(str(filename))

        # Sort works by the track id of the first track in each work.
        items = list(recording.works.items())
        items.sort(key=lambda i: i[1].track_ids[0])
        for work_num, work in items:
            n_primary = len(config.genre_spec[work.genre]['primary'])
            vals = ['; '.join(v) for v in work.metadata[:n_primary]]
            description = '\n'.join(vals)
            row = (thumbnail_pb, description, work.genre, uuid,
                    work_num, recording.tracks)
            liststore.append(row)

        treeselection.set_mode(Gtk.SelectionMode.SINGLE)

    def on_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return

        _, _, genre, uuid, work_num, tracks = model[treeiter]

        selector = getattr_from_obj_with_name('selector')
        selector.set_selection(genre, uuid, work_num, tracks)

        button = self.action_area.get_children()[0]
        GLib.timeout_add(500, button.clicked)

        doublebutton.config(1, True, True)

