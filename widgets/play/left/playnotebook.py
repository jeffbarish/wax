"""This module displays long metadata."""

import sys
import importlib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject

if __name__ == '__main__':
    from os.path import dirname
    sys.path.insert(0, dirname(dirname(sys.path[0])))
from common.connector import register_connect_request
from common.genrespec import genre_spec
from common.utilities import debug, idle_add

@Gtk.Template.from_file('data/glade/play/notebook.glade')
class PlayNotebook(Gtk.Notebook):
    __gtype_name__ = 'play_notebook'

    @GObject.Signal
    def page(self, up: bool):
        pass

    def __init__(self):
        super().__init__()
        self.set_name('play-notebook')

        self.connect('realize', self.on_playnotebook_realize)
        self.connect('key-press-event', self.on_key_press_event)

        # pages will map the name of the page to the page.
        self.pages = pages = {}

        # Import the modules for pages of the notebook. They are located
        # in the 'pages' subdirectory.
        page_names = ['metadata', 'wikipedia', 'docs', 'properties']
        for page_name in page_names:
            module_name = f'widgets.play.left.pages.{page_name}'
            page = importlib.import_module(module_name)
            pages[page_name] = page
            page_widget = page.page_widget
            self.append_page(page_widget)
            self.set_tab_label_text(page_widget, page_widget.tab_text)
            tab_label = self.get_tab_label(page_widget)
            tab_label.set_size_request(80, -1)

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)

    def on_playnotebook_realize(self, playnotebook):
        self.grab_focus()

    def on_key_press_event(self, playnotebook, eventkey):
        if eventkey.type == Gdk.EventType.KEY_PRESS:
            success, value = eventkey.get_keyval()
            match value:
                case Gdk.KEY_Page_Down:
                    self.emit('page', False)
                case Gdk.KEY_Page_Up:
                    self.emit('page', True)

    @idle_add
    def on_recording_selection_changed(self, selection):
        model_filter, treeiter = selection.get_selected()
        if treeiter is not None:
            # model updates on selection changed, so wait for it to finish
            # (the idle_add above) before reading values.
            model = model_filter.props.child_model
            metadata = model.metadata
            nonce = model.work.nonce
            props = model.recording.props
            uuid = model.recording.uuid
            self.pages['metadata'].page_widget.populate(metadata, nonce, uuid)
            self.pages['wikipedia'].page_widget.populate(metadata)
            if self.pages['docs'].page_widget.has_docs(uuid):
                self.pages['docs'].page_widget.show()
                self.pages['docs'].page_widget.populate(uuid)
            else:
                self.pages['docs'].page_widget.hide()
            self.pages['properties'].page_widget.populate(props)

    def on_recording_saved(self, editnotebook, genre):
        uuid = editnotebook.recording.uuid
        work_long, work_short = editnotebook.get_work_metadata()
        nonce = editnotebook.get_nonce()
        keys = genre_spec.all_keys(genre)
        metadata = list(zip(keys, work_long))
        self.pages['metadata'].page_widget.populate(metadata, nonce, uuid)

        props = editnotebook.get_props()
        self.pages['properties'].page_widget.populate(props)

