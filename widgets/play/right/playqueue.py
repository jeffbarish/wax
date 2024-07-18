"""The view of the play queue that appears in play mode."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject

from common.constants import NOEXPAND
from common.utilities import debug
from widgets.select.right import playqueue_model

@Gtk.Template.from_file('data/glade/play/playqueue.glade')
class Playqueue(Gtk.ScrolledWindow):
    __gtype_name__ = 'queue_scrolledwindow'

    @GObject.Signal
    def playqueue_play_selection_changed(self, genre: object):
        pass

    queue_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('playqueue_play')

        playqueue_model.connect('row-inserted', self.on_row_inserted)
        playqueue_model.connect('row-deleted', self.on_row_deleted)

        self.show_all()

    def on_row_inserted(self, model, path, treeiter):
        image = Gtk.Image.new_from_pixbuf(model.get_value(treeiter, 0))
        eventbox = Gtk.EventBox.new()
        eventbox.add(image)
        eventbox.show_all()
        eventbox.connect('button-press-event', self.on_button_press_event)
        self.queue_box.pack_start(eventbox, *NOEXPAND)
        self.queue_box.reorder_child(eventbox, path[0])

    def on_row_deleted(self, model, path):
        images = self.queue_box.get_children()
        self.queue_box.remove(images[path[0]])

    def on_button_press_event(self, eventbox, eventbutton):
        if eventbutton.type == Gdk.EventType.BUTTON_PRESS \
                and eventbutton.state == 0 \
                and eventbutton.button == 1:
            children = self.queue_box.get_children()
            index = children.index(eventbox)
            treepath = Gtk.TreePath.new_from_string(str(index))
            self.emit('playqueue-play-selection-changed', treepath)

    def update_image(self, index, pb):
        queue_box = self.queue_box
        children = queue_box.get_children()
        eventbox = children[index]
        image = eventbox.get_child()
        image.set_from_pixbuf(pb)

