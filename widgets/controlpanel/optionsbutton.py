"""OptionsButton widget."""

import logging

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.utilities import debug

class OptionsButton(Gtk.MenuButton):
    def __init__(self):
        super().__init__(label='Options')
        self.set_name('options-button')

        self.option_menus = option_menus = {
            'Select': ['Remove set', 'Clear queue'],
            'Play': ['Restart'],
            'Edit': ['Show unicode keyboard', 'Query MB', 'Clear', 'Delete'],
            'Config': ['Help', 'About']
        }
        for mode, options in option_menus.items():
            option_menu = Gtk.Menu()
            for option in options:
                menuitem = Gtk.MenuItem.new_with_label(option)
                option_menu.append(menuitem)
            option_menu.show_all()
            option_menus[mode] = option_menu

        # Add CheckMenuItem to Play.
        checkmenuitem = Gtk.CheckMenuItem.new_with_label('Stop on track done')
        checkmenuitem.show()
        option_menus['Play'].append(checkmenuitem)

        self.set_options_menu('Select')

        self.sensitize_menuitem('Select', 'Clear queue', False)
        self.sensitize_menuitem('Select', 'Remove set', False)
        self.sensitize_menuitem('Play', 'Restart', False)
        self.sensitize_menuitem('Edit', 'Clear', False)
        self.sensitize_menuitem('Edit', 'Delete', False)
        self.sensitize_menuitem('Edit', 'Query MB', False)

    def connect_menuitem(self, mode, option, handler):
        option_menu = self.option_menus[mode]
        for menuitem in option_menu.get_children():
            if menuitem.get_label() == option:
                menuitem.connect('activate', handler)
                break
        else:
            logging.error(f'Option {option} in options menu for mode {mode} '
                    f'does not exist')

    def sensitize_menuitem(self, mode, option, sensitive):
        option_menu = self.option_menus[mode]
        for menuitem in option_menu.get_children():
            if menuitem.get_label() == option:
                menuitem.set_sensitive(sensitive)
                break
        else:
            logging.error(f'Option {option} in options menu for mode {mode} '
                    f'does not exist')

    def set_options_menu(self, mode):
        option_menu = self.option_menus[mode]
        self.set_popup(option_menu)

    def get_menuitem(self, mode, option):
        option_menu = self.option_menus[mode]
        for menuitem in option_menu.get_children():
            if menuitem.get_label() == option:
                return menuitem

