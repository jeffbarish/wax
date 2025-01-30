"""This widget creates a table of Unicode characters which behaves like a
keyboard.  Clicking on one of the characters creates a key press event, so
the character appears at the cursor, wherever it is."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

from common.connector import register_connect_request
from common.utilities import debug
from widgets import options_button, control_panel

uni_chars = 'À Á Â Ã Ä Å Ā Ă Ǎ Æ à á â ã ä å ă ǎ ā æ ' \
    'Ç Ć Ĉ Ċ Č č ć ĉ ċ ç ' \
    'Ď ' \
    'È É Ê Ë Ē Ĕ Ė Ě ě è é ê ë ē ĕ ė ' \
    'Ĝ Ğ Ġ Ģ ĝ ğ ġ ģ ' \
    'Ĥ ĥ ' \
    'Ì Í Î Ï Ĩ Ĭ Ǐ İ Ī ĩ ĭ ǐ ì í î ï ī ' \
    'Ĵ ĵ ' \
    'Ķ ķ ' \
    'Ĺ Ł Ļ Ŀ ĺ ł ļ ŀ ' \
    'Ń Ņ Ň Ñ ń ň ñ ņ ' \
    'Ō Ŏ Ő Ò Ó Ô Õ Ö Ø Œ ŏ ő ò ó ô õ ö ø œ ' \
    'Ŕ Ř ŕ ř ' \
    'Ś Ŝ Š Ş ś ŝ š ş ß ' \
    'Ţ Ť Ŧ ţ ť ŧ ' \
    'Ũ Ū Ŭ Ů Ű Ù Ú Û Ü Ų ũ ŭ ů ű ù ú û ü ų ' \
    'Ŵ ŵ ' \
    'Ŷ Ÿ Ý ŷ ý ÿ ' \
    'Ź Ż Ž Ƶ ź ż ž ƶ © ® ♭ ♯'.split()

class UnicodeKbd(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_name('unicode-kbd')
        self.set_title('Wax Unicode keyboard')
        self.connect('delete-event', self.on_close_button_clicked)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        grid = Gtk.Grid()
        grid.show_all()
        for i, uni_char in enumerate(uni_chars):
            button = Gtk.Button.new_with_label(uni_char)
            button.set_size_request(24, 24)
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_can_focus(False)
            button.set_focus_on_click(False)
            style_context = button.get_style_context()
            style_context.add_class('unicode-kbd-button')
            button.show()
            button.connect('clicked', self.on_button_clicked)
            top, left = divmod(i, 15)
            grid.attach(button, left, top, 1, 1)

        options_button.connect_menuitem('Edit', 'Show unicode keyboard',
                self.on_options_button_activate)

        register_connect_request('edit-left-notebook', 'realize',
                self.on_realize)
        register_connect_request('top-widget', 'key-press-event',
                self.on_key_press_event)
        self.connect('key-press-event', self.on_key_press_event)

        self.add(grid)

    def on_realize(self, edit_metadata_notebook):
        self.gdk_window = edit_metadata_notebook.get_window()

    def on_close_button_clicked(self, button, event):
        self.position = self.get_position()
        self.hide()
        return True

    # ctrl-k typed either to the main window (in edit mode) or the
    # unicode keyboard toggles the visibility of the unicode keyboard.
    # Do not use ctrl-u because it clears the content of entries.
    def on_key_press_event(self, top_widget, event):
        if event.type == Gdk.EventType.KEY_PRESS:
            if event.keyval == Gdk.KEY_k \
                    and event.state & Gdk.ModifierType.CONTROL_MASK \
                    and control_panel.mode == 'Edit':
                self.on_options_button_activate(None)

    def on_options_button_activate(self, menuitem):
        if not self.props.visible:
            # The first time self appears use the default position.
            if hasattr(self, 'position'):
                self.move(*self.position)
            self.show()
        else:
            # Remember the position when hiding self and move to that
            # position the next time self is shown.
            self.position = self.get_position()
            self.hide()

    def on_button_clicked(self, button):
        """Copy the unicode character to the clipboard and send a key press
        event to type the character at the cursor."""
        char = button.get_label()
        self.clipboard.set_text(char, -1)

        current_event = Gtk.get_current_event()
        device = current_event.get_device()

        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.keyval = Gdk.unicode_to_keyval(ord(char))
        event.set_device(device)
        event.window = self.gdk_window
        event.put()

