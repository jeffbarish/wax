"""Notebook for search incremental and search sibling."""

import importlib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

class SearchNotebook(Gtk.Notebook):
    def __init__(self):
        super().__init__()
        self.set_name('search-notebook')
        self.tab_text = 'Search'
        self.show()

        for page_name in ['incremental', 'sibling']:
            qual_name = f'widgets.select.left.pages.search.{page_name}'
            page = importlib.import_module(qual_name)
            page_widget = page.page_widget
            label = Gtk.Label.new(page_widget.tab_text)
            label.set_hexpand(True)
            self.append_page(page_widget, label)

page_widget = SearchNotebook()

