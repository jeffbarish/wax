"""Main program for Wax."""

import os
import sys
import signal

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio

import common.initlogging
from common.config import config
from common.connector import traverse_widgets, connect_signals
from common.connector import getattr_from_obj_with_name
from common.utilities import debug

# Top widgets:
from common.cddrivewatcher import cd_drive_watcher
from player import player
from ripper import ripper
from widgets import top_widget
from widgets import control_panel

# Make pickle happy:
from common.types import RecordingTuple, WorkTuple, TrackTuple

MAIN_WINDOW_SIZE = (config.geometry['window_width'],
        config.geometry['window_height'])

class Wax(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_title('Wax')
        self.set_default_size(*MAIN_WINDOW_SIZE)
        self.connect_after('destroy', self.on_destroy)
        self.show()

        signal.signal(signal.SIGINT, self.on_signal)

        screen = Gdk.Screen.get_default()
        gtk_provider = Gtk.CssProvider()
        gtk_context = Gtk.StyleContext()
        gtk_context.add_provider_for_screen(screen, gtk_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        css_file = Gio.File.new_for_path('data/wax.css')
        gtk_provider.load_from_file(css_file)

        self.add(top_widget)

        traverse_widgets([self, control_panel, player, ripper,
                cd_drive_watcher])
        connect_signals()

        # Do not initialize the genre selector until we finish configuring
        # the entire GUI.
        getattr_from_obj_with_name('genre-button.init')()

    def on_destroy(self, window):
        self.quit()

    def on_signal(self, signal, frame):
        self.quit()

    def quit(self):
        Gtk.main_quit()

if len(sys.argv) > 1 and sys.argv[1] == '--version':
    os.system('hg identify --num --rev .')
else:
    wax = Wax()
    Gtk.main()

