"""Notebook for right panel of Select mode."""

"""Since removing the move operation, it is no longer necessary to have a
notebook on the right panel of select mode."""

import importlib

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.utilities import debug

@Gtk.Template.from_file('data/glade/edit/right/notebook.glade')
class EditNotebook(Gtk.Notebook):
    __gtype_name__ = 'edit_right_notebook'

    def __init__(self):
        super().__init__()
        self.set_name('edit-right-notebook')
        self.show()

        # pages will map the name of the page to the page.
        self.pages = pages = {}.fromkeys(['ripcd', 'importfiles'])

        # Import the modules for pages of the notebook. They are located
        # in the 'pages' subdirectory.
        size_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
        for page_module_name in pages:
            qual_name = f'widgets.edit.right.pages.{page_module_name}'
            page = importlib.import_module(qual_name)
            pages[page_module_name] = page
            page_widget = page.page_widget
            self.append_page(page_widget)
            self.set_tab_label_text(page_widget, page_widget.tab_text)
            tab_label = self.get_tab_label(page_widget)
            tab_label.set_padding(6, 0)
            size_group.add_widget(tab_label)

