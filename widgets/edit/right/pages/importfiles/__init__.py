"""This package assembles the widgets for importing files."""

from widgets.doublebutton import DoubleButton
doublebutton = DoubleButton.new_with_labels('Create', 'Add')

from .importfiles import ImportFiles
page_widget = ImportFiles()

