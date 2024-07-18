"""Filter buttons appear at the top of the selector alongside the genre
selector. They provide menus for filtering the contents of the recording
list."""

import pickle

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject

from common.utilities import debug, css_load_from_data

class FilterButton(Gtk.MenuButton):
    def __init__(self, menuitem_activated_cb, restore_activated_cb):
        super().__init__()
        self.menuitem_activated_cb = menuitem_activated_cb
        self.restore_activated_cb = restore_activated_cb

        self.set_size_request(100, -1)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(False)

        # Materia-Manjaro-Dark-gtk theme provides a dark separator which is
        # not visible against a dark background.
        css_data = """separator {
            background-color: #545454;
        }"""
        css_load_from_data(css_data)

    # If the current selection is still in column_data, do not update.
    def update_menu(self, column_data):
        self.menu = menu = Gtk.Menu()
        for filter_item in column_data:
            menuitem = Gtk.MenuItem.new_with_label(filter_item)
            menuitem.connect('activate', self.menuitem_activated_cb, self)
            menu.append(menuitem)
        menu.append(Gtk.SeparatorMenuItem())
        restore_menuitem = Gtk.MenuItem.new_with_label('Restore')
        restore_menuitem.connect('activate', self.restore_activated_cb, self)
        menu.append(restore_menuitem)
        menu.show_all()
        self.set_popup(menu)

    def set_label_to_first_menuitem(self):
        first_menuitem = self.menu.get_children()[0]
        label = first_menuitem.get_label()
        self.label = label

    @property
    def label(self):
        return self.props.label

    @label.setter
    def label(self, label):
        self.set_label(label)
        label_widget = self.get_children()[0]
        label_widget.set_xalign(0.5)

class FilterButtonBox(Gtk.Box):
    @GObject.Signal
    def filter_button_created(self, button: object):
        pass

    @GObject.Signal
    def filter_button_activated(self):
        pass

    @GObject.Signal
    def filter_button_deactivated(self, index: int):
        pass

    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.set_hexpand(True)
        self.set_name('filter-button-box')
        self.show()

        self.drag_dest_set(
                Gtk.DestDefaults.ALL,
                [Gtk.TargetEntry.new('column', Gtk.TargetFlags.SAME_APP, 0)],
                Gdk.DragAction.COPY)
        self.connect('drag-data-received', self.on_drag_data_received)

    # Interate over visible buttons.
    def __iter__(self):
        return (button for button in self.get_children()
                if button.props.visible)

    def on_drag_data_received(self, widget, drag_context,
                x, y, data, info, time):
        index = pickle.loads(data.get_data())
        button = self.show_button(index)
        self.emit('filter-button-created', button)

    def on_menuitem_activated(self, menuitem, button):
        new_label = menuitem.get_label()
        if new_label == button.label:
            return
        button.label = new_label

        # Tell selector to refilter the recording model.
        self.emit('filter-button-activated')

    def on_restore_activated(self, menuitem, button):
        button.hide()

        # Tell selector to make the corresponding column visible.
        self.emit('filter-button-deactivated', button.index)

    def show_button(self, index):
        for button in self.get_children():
            if not button.get_visible():
                break
        else:
            button = FilterButton(self.on_menuitem_activated,
                    self.on_restore_activated)
            self.add(button)
        button.index = index
        button.show()
        return button

    def clear(self):
        for button in self:
            button.hide()

    def init_buttons(self):
        if any(self):
            for button in self:
                button.set_label_to_first_menuitem()
            self.emit('filter-button-activated')

    def get_config(self):
        return [button.index for button in self]

