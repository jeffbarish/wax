"""MenuButton for selecting the genre. Populates the menu with the genre
names found by genrespec. This module appears here because both
widgets.select.left.pages.select and widgets.edit.left.pages.work import
it."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from common.genrespec import genre_spec
from common.utilities import debug

default_genre, *other_genres = genre_spec

class GenreButton(Gtk.MenuButton):
    @GObject.Signal
    def genre_changing(self, genre: str):
        pass

    @GObject.Signal
    def genre_changed(self, genre: str):
        pass

    def __init__(self):
        super().__init__()
        self._xalign = 0.0
        self.set_size_request(100, -1)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(False)
        self.set_margin_top(3)
        self.set_margin_left(3)
        self.label = default_genre
        self.show()

        self.genre_menu = genre_menu = Gtk.Menu()
        for genre_name in genre_spec:
            menuitem = Gtk.MenuItem.new_with_label(genre_name)
            menuitem.connect('activate', self.on_genre_menuitem_activated)
            genre_menu.append(menuitem)
        self.set_popup(genre_menu)
        genre_menu.show_all()

    def on_genre_menuitem_activated(self, menuitem):
        new_genre = menuitem.get_label()
        self.genre = new_genre  # emits signals

    @property
    def genre(self):
        return self.label

    @genre.setter
    def genre(self, new_genre):
        if new_genre != self.label:
            self.emit('genre-changing', self.label)
            self.label = new_genre
            self.emit('genre-changed', self.label)

    @property
    def label(self):
        return self.props.label

    @label.setter
    def label(self, label):
        self.set_label(label)
        label_widget = self.get_children()[0]
        label_widget.set_xalign(self._xalign)

    def set_xalign(self, xalign):
        self._xalign = xalign
        label_widget = self.get_children()[0]
        label_widget.set_xalign(xalign)

    # This method is for changing the genre programmatically, in which case
    # we do not want signals.
    def set_genre(self, new_genre):
        self.label = new_genre

    # Called from wax to initialize the genre setting.
    def init(self):
        self.set_genre(default_genre)
        self.emit('genre-changed', self.label)
