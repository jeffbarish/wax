"""This module displays properties."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.constants import AUTO_PROPS_1, AUTO_PROPS_2
from common.utilities import debug

@Gtk.Template.from_file('data/glade/play/properties.glade')
class PropertiesView(Gtk.Grid):
    __gtype_name__ = 'properties_grid'

    auto_props_1_liststore = Gtk.Template.Child()
    auto_props_1_cellrenderer_value = Gtk.Template.Child()
    auto_props_1_treeviewcolumn_value = Gtk.Template.Child()

    auto_props_2_liststore = Gtk.Template.Child()
    auto_props_2_cellrenderer_value = Gtk.Template.Child()
    auto_props_2_treeviewcolumn_value = Gtk.Template.Child()

    user_props_liststore = Gtk.Template.Child()
    user_props_cellrenderer_value = Gtk.Template.Child()
    user_props_treeviewcolumn_value = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.tab_text = 'Properties'
        self.set_name('play-properties-page')

        def func(column, cell, model, treeiter, user):
            val = model.get_value(treeiter, 1)
            val_str = str(val[0])
            cell.set_property('text', val_str)
        for cat in ['auto_props_1', 'auto_props_2', 'user_props']:
            treeviewcolumn = getattr(self, f'{cat}_treeviewcolumn_value')
            cellrenderer = getattr(self, f'{cat}_cellrenderer_value')
            treeviewcolumn.set_cell_data_func(cellrenderer, func)

    def populate(self, props):
        prop_dict = dict(props)
        for prop_category, liststore in [
                (AUTO_PROPS_1, self.auto_props_1_liststore),
                (AUTO_PROPS_2, self.auto_props_2_liststore)]:
            liststore.clear()
            for prop in prop_category:
                value = prop_dict.pop(prop)
                liststore.append((prop, value))

        # Any remaining items must be user properties.
        self.user_props_liststore.clear()
        for prop, value in prop_dict.items():
            self.user_props_liststore.append((prop, value))


page_widget = PropertiesView()
