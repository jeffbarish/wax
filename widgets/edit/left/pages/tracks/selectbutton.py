from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GdkPixbuf, GObject

from common.constants import IMAGES_DIR
from common.utilities import debug

class SelectButton(Gtk.Box):
    @GObject.Signal
    def select_button_clicked(self, select: str):
        pass

    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_name('select-button')
        self.set_spacing(0)

        checkbox_all_path = str(Path(IMAGES_DIR, 'checkbox-all.png'))
        checkbox_all_pb = GdkPixbuf.Pixbuf.new_from_file(checkbox_all_path)
        self.checkbox_all_pb = checkbox_all_pb

        checkbox_none_path = str(Path(IMAGES_DIR, 'checkbox-none.png'))
        checkbox_none_pb = GdkPixbuf.Pixbuf.new_from_file(checkbox_none_path)
        self.checkbox_none_pb = checkbox_none_pb

        checkbox_image = Gtk.Image.new_from_pixbuf(checkbox_none_pb)
        self.checkbox_image = checkbox_image

        self.left_button = left_button = Gtk.Button()
        left_button.set_name('select-button-left')
        left_button.set_can_focus(False)
        left_button.set_sensitive(True)
        left_button.set_image(checkbox_image)
        left_button.connect('clicked', self.on_left_button_clicked)

        self.right_button = right_button = Gtk.MenuButton()
        right_button.set_name('select-button-right')
        right_button.set_can_focus(False)
        right_button.set_sensitive(True)
        self.initialize_menu()

        self.add(left_button)
        self.add(right_button)

    def on_left_button_clicked(self, button):
        current_pb = self.checkbox_image.get_pixbuf()
        select_all = (current_pb == self.checkbox_all_pb)
        self.change_image(select_all)
        self.emit('select-button-clicked', ('none', 'all')[select_all])

    def on_menuitem_activate(self, menuitem):
        label = menuitem.get_label()
        select_all = (label == 'All')
        self.change_image(select_all)
        self.emit('select-button-clicked', label.lower())

    def change_image(self, select_all):
        new_pb = (self.checkbox_all_pb, self.checkbox_none_pb)[select_all]
        self.checkbox_image.set_from_pixbuf(new_pb)

    def initialize_menu(self):
        menu = Gtk.Menu()
        for label in ('All', 'None', 'Reverse'):
            menuitem = Gtk.MenuItem.new_with_label(label)
            menuitem.connect('activate', self.on_menuitem_activate)
            menu.append(menuitem)
        menu.show_all()
        self.right_button.set_popup(menu)
        self.show_all()

    def set_state(self, state):
        pb_map = {'none': self.checkbox_none_pb, 'all': self.checkbox_all_pb}
        image = self.left_button.get_image()
        image.set_from_pixbuf(pb_map[state])

