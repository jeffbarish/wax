"""A form for entering and editing properties."""

import itertools
from datetime import datetime
from typing import List

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib

from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.connector import QuietProperty
from common.constants import PROPS_REC, PROPS_WRK, NOEXPAND
from common.utilities import debug
from ripper import ripper
from widgets import config
from widgets import options_button

try:
    USER_PROPS = config.user_props
except KeyError:
    USER_PROPS = []

class PropertiesEditor(Gtk.ScrolledWindow):
    _properties_changed = QuietProperty(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.set_name('edit-properties-page')
        self.tab_text = 'Props'
        self.set_margin_top(3)

        vbox = Gtk.Box()
        vbox.set_orientation(Gtk.Orientation.VERTICAL)
        vbox.set_spacing(1)

        self.entries = {}
        categories = (PROPS_REC, PROPS_WRK, USER_PROPS)
        for key in itertools.chain.from_iterable(categories):
            hbox = Gtk.Box()
            hbox.set_orientation(Gtk.Orientation.HORIZONTAL)

            markup = f'<span font="monospace" size="8000">{key}</span>'
            key_label = Gtk.Label()
            key_label.set_markup(markup)
            key_label.set_size_request(100, -1)
            key_label.set_alignment(0, 0.5)
            hbox.pack_start(key_label, False, False, 6)

            value_entry = Gtk.Entry()
            value_entry.connect('changed',
                    self.on_entry_changed)
            hbox.pack_start(value_entry, True, True, 6)

            self.entries[key] = value_entry
            vbox.pack_start(hbox, *NOEXPAND)
        self.add(vbox)
        self.show_all()

        self.connect('notify::properties-changed',
                self.on_properties_changed)

        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)
        register_connect_request('edit-ripcd', 'rip-create-clicked',
                self.on_rip_create_clicked)
        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

    def on_abort_button_clicked(self, button):
        if ripper.disc_num == 0 and not ripper.rerip:
            self.clear()

    def on_options_edit_clear_activate(self, menuitem):
        self._properties_changed = False

    def on_properties_changed(self, obj, param):
        edit_message_label = getattr_from_obj_with_name('edit-message-label')
        if self.properties_changed:
            edit_message_label.queue_message('properties changed')

    def on_entry_changed(self, entry):
        self._properties_changed = True

    def on_save_button_clicked(self, button, label):
        self._properties_changed = False

    def on_rip_create_clicked(self, button):
        # The create button initiates a rip from a CD. We know the properties
        # of a rip, so specify them here.
        now = datetime.now()
        props_rec = [('date created', (now.strftime("%Y %b %d"),)),
            ('codec', ('FLAC',)),
            ('sample rate', ('44.1 kHz',)),
            ('resolution', ('16',)),
            ('source', ('CD',))]
        props_wrk = [('times played', ('0',))]

        # Call populate from the idle loop to assure that the clear initiated
        # by editnotebook.clear_all_forms runs first.
        GLib.idle_add(self.populate, props_rec, props_wrk)

    def populate(self, props_rec: List, props_wrk: List):
        signal_id = GObject.signal_lookup('changed', Gtk.Entry)
        for key, value in itertools.chain(props_rec, props_wrk):
            entry = self.entries[key]
            handler_id = GObject.signal_handler_find(entry,
                    GObject.SignalMatchType.ID, signal_id,
                    0, None, None, None)
            with GObject.signal_handler_block(entry, handler_id):
                entry.set_text(str(value[0]))
        self._properties_changed = False

    def clear(self):
        signal_id = GObject.signal_lookup('changed', Gtk.Entry)
        for entry in self.entries.values():
            handler_id = GObject.signal_handler_find(entry,
                    GObject.SignalMatchType.ID, signal_id,
                    0, None, None, None)
            with GObject.signal_handler_block(entry, handler_id):
                entry.set_text('')
        self._properties_changed = False

    def get_props(self):
        props = {key: (entry.get_text(),)
                for key, entry in self.entries.items()}
        props_rec = [(key, props.pop(key)) for key in PROPS_REC]
        props_wrk = list(props.items())
        return props_rec, props_wrk


page_widget = PropertiesEditor()
