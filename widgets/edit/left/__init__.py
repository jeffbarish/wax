"""This package assembles the left panel of Edit mode."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from .editnotebook import EditNotebook
from .savebutton import SaveButton
from .unicodekbd import UnicodeKbd
from common.constants import NOEXPAND
from widgets.messagelabel import MessageLabel

class EditLeft(Gtk.Box):
    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.VERTICAL)

        self.edit_message_label = edit_message_label = MessageLabel()
        edit_message_label.set_margin_start(6)
        edit_message_label.set_maxlen(55)
        edit_message_label.set_name('edit-message-label')

        save_button = SaveButton()
        save_button.set_labels('Save new', 'Save revision')

        hbox = Gtk.Box()
        hbox.set_orientation(Gtk.Orientation.HORIZONTAL)
        hbox.set_spacing(3)
        hbox.pack_start(edit_message_label, *NOEXPAND)
        hbox.pack_end(save_button, *NOEXPAND)

        self.pack_end(hbox, False, False, 3)
        self.show_all()


edit_notebook = EditNotebook()

edit_left = EditLeft()
edit_left.pack_end(edit_notebook, True, True, 0)

