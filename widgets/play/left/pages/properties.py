"""This module displays properties."""

from typing import List

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.constants import PROPS_WRK
from common.types import MetadataItem
from common.utilities import debug

@Gtk.Template.from_file('data/glade/play/properties.glade')
class PropertiesView(Gtk.Grid):
    __gtype_name__ = 'properties_grid'

    props_rec_liststore = Gtk.Template.Child()
    props_rec_cellrenderer_value = Gtk.Template.Child()
    props_rec_treeviewcolumn_value = Gtk.Template.Child()

    props_wrk_liststore = Gtk.Template.Child()
    props_wrk_cellrenderer_value = Gtk.Template.Child()
    props_wrk_treeviewcolumn_value = Gtk.Template.Child()

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
        for cat in ['props_rec', 'props_wrk', 'user_props']:
            treeviewcolumn = getattr(self, f'{cat}_treeviewcolumn_value')
            cellrenderer = getattr(self, f'{cat}_cellrenderer_value')
            treeviewcolumn.set_cell_data_func(cellrenderer, func)

    def populate(self, props_rec: List[MetadataItem],
            props_wrk: List[MetadataItem]):
        self.props_rec_liststore.clear()
        self.props_wrk_liststore.clear()
        self.user_props_liststore.clear()

        for row in props_rec:
            self.props_rec_liststore.append(row)

        for prop, value in props_wrk:
            if prop in PROPS_WRK:
                self.props_wrk_liststore.append((prop, value))
            elif value != ('',):
                self.user_props_liststore.append((prop, value))


page_widget = PropertiesView()
