"""This module assembles the right panel of Play mode."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from .coverartviewer import CoverArtViewer
from .playqueue import Playqueue
from widgets import config

RIGHT_PANEL_VBOX_WIDTH = config.geometry['right_panel_width']

class PlayRight(Gtk.Box):
    def __init__(self):
        super().__init__()
        self.set_name('play-right')
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)
        self.set_spacing(6)
        self.set_size_request(RIGHT_PANEL_VBOX_WIDTH, -1)
        self.show()

        coverartviewer = CoverArtViewer()
        playqueue = Playqueue()
        self.add(coverartviewer)
        self.add(playqueue)

play_right = PlayRight()

