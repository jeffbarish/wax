"""Specify the sections of the main display."""

# Control panel.
from .controlpanel import optionsbutton
options_button = optionsbutton.OptionsButton()

from .controlpanel import controlpanel
control_panel = controlpanel.ControlPanel()


# Select mode.
from .select.left import select_left
from .select.right import select_right


# Play mode.
from .play.left import play_left
from .play.right import play_right


# Edit mode.
from .edit.left import edit_left
from .edit.right import edit_right


# Create the top widget using the preceding imports.
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.config import config
RIGHT_PANEL_VBOX_WIDTH = config.geometry['right_panel_width']

class TopWidget(Gtk.Grid):
    def __init__(self):
        super().__init__()
        self.set_name('top-widget')

        # There are two stacks, one for the left side and one for the right.
        self.stacks = stacks = {'left': Gtk.Stack(), 'right': Gtk.Stack()}
        for mode in ('Select', 'Play', 'Edit'):
            for side in ('left', 'right'):
                section = globals()[f'{mode.lower()}_{side}']
                stacks[side].add_named(section, mode)
                stacks[side].show()

        # The right side gets the control panel and then the right stack.
        right_grid = Gtk.Grid()
        right_grid.set_size_request(RIGHT_PANEL_VBOX_WIDTH, -1)
        right_grid.set_hexpand(False)
        right_grid.set_orientation(Gtk.Orientation.VERTICAL)
        right_grid.add(control_panel.view)
        right_grid.add(stacks['right'])
        right_grid.show()

        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.add(stacks['left'])
        self.add(right_grid)
        self.set_column_spacing(3)
        self.show()

top_widget = TopWidget()

