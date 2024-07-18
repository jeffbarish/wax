"""A label that queues messages for display. Each message displays for
INTERVAL seconds."""

import queue

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Pango

INTERVAL = 3

class MessageLabel(Gtk.Label):
    def __init__(self):
        super().__init__()
        self.set_can_focus(False)
        self.restore_cb = None
        self.maxlen = None

        # Set color to #dcdc14143c3c.
        attr = Pango.attr_foreground_new(0xdcdc, 0x1414, 0x3c3c)
        attrs = Pango.AttrList.new()
        attrs.insert(attr)
        self.set_attributes(attrs)

        self.message_queue = queue.Queue()
        self.timer_is_running = False

    # Setting ellipsize to Pango.EllipsizeMode.END does not work. The label
    # gets wider to accommodate a long string and forces the main window to
    # get wider. Setting a size request does not help as that request sets
    # a minimum size. Instead, I set maxlen (a maximum length for the
    # message in characters) and handle the ellipsizing myself.
    def set_maxlen(self, maxlen):
        self.maxlen = maxlen

    # If multiple messages get queued, only the first expose_cb and the first
    # non-None restore_cb matter. If neither is specified, MessageLabel shows
    # itself when a message is queued and hides itself when no messages
    # remain in the queue.
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
            self.hide()
            if self.restore_cb is not None:
                self.restore_cb()
                self.restore_cb = None
            self.timer_is_running = False
            return False
        if self.maxlen and len(message) > self.maxlen:
            message = message[:self.maxlen-1] + '…'
        self.set_markup(message)
        return True

