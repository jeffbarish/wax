"""AlphabetScroller is used to scroll the recording selector to a row whose
value in the sort column corresponds to the letter clicked."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

class AlphabetScroller(Gtk.Box):
    @GObject.Signal
    def scroll_to_letter(self, letter: str):
        pass

    def __init__(self):
        super().__init__()
        self.set_name('alphabet-scroller')
        self.set_orientation(Gtk.Orientation.HORIZONTAL)

        for i in range(26):
            character = chr(ord('A') + i)
            button = Gtk.Button()
            # If I set a css name for the button, then I lose the button
            # styling specified by the theme.
            button.set_name('alphabet-scroller-button')
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.set_can_focus(False)
            button.connect('clicked', self.on_button_clicked, character)
            label = Gtk.Label()
            label.set_label(character)
            button.add(label)
            self.pack_start(button, expand=True, fill=True, padding=0)
        self.show_all()

    def on_button_clicked(self, button, character):
        self.emit('scroll-to-letter', character)

