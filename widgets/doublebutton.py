"""DoubleButton is actually two buttons. They are side by side, and styled to
look like two parts of the same button. The button on the left emits a signal
with the label as cargo. The button on the right opens a menu which can be
used to specify the label of the button on the left. It also emits a signal
with the new label as if the button on the left were clicked at the same
time. DoubleButton automatically determines the width it needs to accommodate
either label without resizing.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Pango, GObject

from common.decorators import UniqObjectName
from common.utilities import debug

@UniqObjectName
class DoubleButton(Gtk.Box):
    @GObject.Signal
    def clicked(self, arg: str):
        pass

    @classmethod
    def new_with_labels(cls, label_1, label_2):
        self = cls()
        self.set_labels(label_1, label_2)
        self.config(0, False, False)
        return self

    def __init__(self):
        self.set_orientation(Gtk.Orientation.HORIZONTAL)

        self.left_button = left_button = Gtk.Button()
        style_context = left_button.get_style_context()
        style_context.add_class('double-left')
        left_button.connect('clicked', self.on_left_button_clicked)
        left_button.set_can_focus(False)
        left_button.set_sensitive(False)

        self.right_button = right_button = Gtk.MenuButton()
        style_context = right_button.get_style_context()
        style_context.add_class('double-right')
        right_button.set_can_focus(False)
        right_button.set_sensitive(False)

        self.add(left_button)
        self.add(right_button)

        self.buttons = (left_button, right_button)
        self.labels = ('', '')

        self.show_all()

    def initialize_buttons(self, *labels):
        menu = Gtk.Menu()
        for label in labels:
            menuitem = Gtk.MenuItem.new_with_label(label)
            menuitem.connect('activate', self.on_menuitem_activate)
            menu.append(menuitem)
        menu.show_all()
        self.right_button.set_popup(menu)
        self.config(0, False, False)

        max_width = max(map(self._get_label_pango_width, labels))
        self.left_button.set_size_request(max_width + 14, -1)

    def set_labels(self, *labels):
        self.labels = labels
        self.initialize_buttons(*labels)

    def config(self, label_num, *sensitive):
        if label_num is not None:
            self.left_button.set_label(self.labels[label_num])
        for button, sen in zip(self.buttons, sensitive):
            if sen is not None:
                button.set_sensitive(sen)

    def get_sensitive(self):
        return tuple(button.get_sensitive() for button in self.buttons)

    def get_label(self):
        return self.left_button.get_label()

    def _get_label_pango_width(self, string):
        label = Gtk.Label()
        pango_layout = label.get_layout()
        pango_layout.set_text(string, -1)
        pango_font_desc = Pango.FontDescription()
        pango_layout.set_font_description(pango_font_desc)
        width, height = pango_layout.get_pixel_size()
        return width

    def on_menuitem_activate(self, menuitem):
        label = menuitem.get_label()
        self.left_button.set_label(label)

        # The next statement should not be necessary, but I once saw the
        # label of the left button get changed, but it was not visible.
        self.left_button.show_all()

    def on_left_button_clicked(self, button):
        label = button.get_label()
        self.emit('clicked', label)

