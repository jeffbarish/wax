"""A widget for viewing wikipedia pages."""

import re
from itertools import groupby

import gi
gi.require_version('Gtk', '3.0')
try:
    gi.require_version('WebKit2', '4.1')
except ValueError:
    gi.require_version('WebKit2', '4.0')
from gi.repository import Gtk, WebKit2

from common.connector import register_connect_request
from common.constants import EXPAND
from common.utilities import debug
from worker import worker

WIKIPEDIA_URL = 'https://en.m.wikipedia.org/wiki/special:search/'

@Gtk.Template.from_file('data/glade/play/wikipedia.glade')
class WikipediaView(Gtk.Box):
    __gtype_name__ = 'wikipedia_box'

    wikipedia_search_menu = Gtk.Template.Child()
    wikipedia_page_next_button = Gtk.Template.Child()
    wikipedia_page_prev_button = Gtk.Template.Child()
    wikipedia_search_menubutton = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('play-wikipedia-page')
        self.tab_text = 'Wikipedia'
        self.show()

        self.webview = webview = WebKit2.WebView()
        webview.connect('notify::uri', self.on_uri_prop_changed)
        webview.show()
        self.pack_end(webview, *EXPAND)

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)

    def on_recording_selection_changed(self, selection):
        self.wikipedia_page_next_button.set_sensitive(False)
        self.wikipedia_page_prev_button.set_sensitive(False)

    def on_uri_prop_changed(self, webview, param):
        sensitive = self.webview.can_go_back()
        self.wikipedia_page_prev_button.props.sensitive = sensitive

    def on_genre_menuitem_activated(self, menuitem):
        if menuitem.props.label.isdigit():
            self.search(f'{menuitem.props.label} in music')
        else:
            self.search(menuitem.props.label)

    @Gtk.Template.Callback()
    def on_wikipedia_page_prev_button_clicked(self, button):
        self.webview.go_back()
        self.wikipedia_page_next_button.set_sensitive(True)

    @Gtk.Template.Callback()
    def on_wikipedia_page_next_button_clicked(self, button):
        self.webview.go_forward()

    def populate(self, metadata):
        self.clear_menu()

        self.wikipedia_search_menubutton.props.sensitive = bool(metadata)
        if not metadata:
            return

        # Populate the menu with all values in metadata so that the user does
        # not have to wait for the menu to become valid. If the user selects
        # a name for which there is no Wikipedia page, then he will wind up
        # at a search page. However, as soon as we finish populating the menu,
        # we immediately launch a worker task for purging invalid names.
        # Unless the user moves very quickly, such names will already have
        # been purged by the time the user gets to the menu.
        values_text = sorted(v for key, values in metadata for v in values
                if not v.isdigit() and not key == 'subgenre')
        values_text = [k for k, g in groupby(values_text)]  # uniq
        for value in values_text:
            paren_re = re.compile(r'\s\(.*\)')
            clean_value = paren_re.sub('', value)
            menuitem = Gtk.MenuItem.new_with_label(clean_value)
            menuitem.connect('activate', self.on_genre_menuitem_activated)
            self.wikipedia_search_menu.append(menuitem)
            menuitem.show()

        self.menuitems = self.wikipedia_search_menu.get_children()
        self.menuitem = self.menuitems[0]
        self.menuitem.activate()

    def search(self, name):
        self.webview.load_uri(WIKIPEDIA_URL + name)

    def clear_menu(self):
        for menuitem in self.wikipedia_search_menu.get_children():
            self.wikipedia_search_menu.remove(menuitem)
        self.wikipedia_page_next_button.set_sensitive(False)
        self.wikipedia_page_prev_button.set_sensitive(False)


page_widget = WikipediaView()

