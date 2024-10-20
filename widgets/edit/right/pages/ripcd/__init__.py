"""This package assembles the widgets for ripping CDs."""

from widgets.doublebutton import DoubleButton
doublebutton = DoubleButton.new_with_labels('Create', 'Add')

from .ripcd import RipCD

page_widget = RipCD()

