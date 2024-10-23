"""A label that queues messages for display. Each message displays for
INTERVAL seconds."""

import queue
from string import ascii_letters

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango

from common.decorators import UniqObjectName

INTERVAL = 3

@UniqObjectName
class MessageLabel(Gtk.Label):
    def __init__(self):
        self.set_can_focus(False)
        self.restore_cb = None
        self.maxlen = None

        # Set color to #dcdc14143c3c.
        attr = Pango.attr_foreground_new(0xdcdc, 0x1414, 0x3c3c)
        attrs = Pango.AttrList.new()
        attrs.insert(attr)
        font_description = Pango.FontDescription.from_string('Monospace 9')
        attr = Pango.attr_font_desc_new(font_description)
        attrs.insert(attr)
        self.set_attributes(attrs)
        self.set_xalign(0.0)

        # Determine the width per character in the selected monospace font.
        label = Gtk.Label()
        pango_layout = label.get_layout()
        pango_layout.set_text(ascii_letters, -1)
        pango_layout.set_font_description(font_description)
        width, height = pango_layout.get_pixel_size()
        self.char_width = width / len(ascii_letters)

        self.message_queue = queue.Queue()
        self.timer_is_running = False

    # Setting ellipsize to Pango.EllipsizeMode.END does not work. The label
    # is configured to expand as necessary to fill the space it occupies.
    # (Surrounding widgets have fixed widths.) Instead, whenever the label
    # resizes we compute a maximum number of characters to allow and then
    # ellipsize manually.
    def do_size_allocate(self, alloc):
        self.maxlen = int(alloc.width / self.char_width)
        Gtk.Label.do_size_allocate(self, alloc)

    # If multiple messages get queued, only the first expose_cb and the first
    # non-None restore_cb matter. If neither is specified, MessageLabel shows
    # itself when a message is queued and clears itself when no messages
    # remain in the queue. NB: clear, do not hide, the label. Hiding the
    # label prevents GTK from resizing it when the main window resizes.
    def queue_message(self, message, expose_cb=None, restore_cb=None):
        # If the message is already displayed, simply restart the timer so
        # that INTERVALs of display do not accumulate.
        if self.timer_is_running and message == self.get_label():
            GLib.source_remove(self.timer_is_running)
            self.timer_is_running = GLib.timeout_add_seconds(INTERVAL,
                    self.message_queue_consumer)
        else:
            self.message_queue.put_nowait(message)
        if self.restore_cb is None:
            self.restore_cb = restore_cb
        if not self.timer_is_running:
            self.show()
            if expose_cb is not None:
                expose_cb()
            self.message_queue_consumer()
            self.timer_is_running = GLib.timeout_add_seconds(INTERVAL,
                    self.message_queue_consumer)

    def message_queue_consumer(self):
        try:
            message = self.message_queue.get_nowait()
        except queue.Empty:
            self.set_text('')
            if self.restore_cb is not None:
                self.restore_cb()
                self.restore_cb = None
            self.timer_is_running = False
            return False

        # If maxlen is still None then MessageLabel has not been realized
        # yet, so do not set the message.
        if self.maxlen is not None:
            if len(message) > self.maxlen:
                message = message[:self.maxlen - 1] + '…'
            self.set_markup(message)
        return True

