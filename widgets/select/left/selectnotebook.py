"""This module provides a notebook in Select mode for choosing between
the selector and search."""

import importlib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.utilities import debug

@Gtk.Template.from_file('data/glade/select/notebook.glade')
class SelectNotebook(Gtk.Notebook):
    __gtype_name__ = 'select_notebook'

    def __init__(self):
        super().__init__()
        self.set_name('select-notebook')

        # pages will map the name of the page to the page.
        page_names = ['select', 'search', 'random', 'queuefiles']
        self.pages = pages = {}.fromkeys(page_names)

        # Import the modules for pages of the notebook. They are located
        # in the 'pages' subdirectory.
        for page_module_name in pages:
            module_name = f'widgets.select.left.pages.{page_module_name}'
            page = importlib.import_module(module_name)
            page_widget = page.page_widget
            self.append_page(page_widget)
            self.set_tab_label_text(page_widget, page_widget.tab_text)
            label = self.get_tab_label(page_widget)
            label.set_size_request(80, -1)
            pages[page_module_name] = page

