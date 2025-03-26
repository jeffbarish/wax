"""ControlPanel widget."""

from pathlib import Path
from enum import Enum

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, GObject, GdkPixbuf

from common.config import config
from common.connector import register_connect_request
from common.constants import IMAGES_DIR
from common.utilities import debug
import widgets
from widgets import options_button
from widgets.select.right import playqueue_model

class State(Enum):
    STOP, PLAY = range(2)

    def __init__(self, state):
        self._state = state

    def __bool__(self):
        return bool(self._state)

class ControlPanel(GObject.Object):
    mode = GObject.Property(type=str, default='Select')

    def __init__(self):
        super().__init__()
        self.view = ControlPanelView(self)

        # Set the volume before connecting the handler for value-changed so
        # that we can initialize the volume from config without triggering
        # an update to config.
        self.set_volume(config.volume)

        self.view.play_button.connect('clicked', self.on_play_button_clicked)

        playqueue_model.connect('row-inserted',
                self.on_playqueue_model_row_inserted)
        playqueue_model.connect('row-deleted',
                self.on_playqueue_model_row_deleted)

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('playqueue_select.playqueue_treeselection',
                'changed',
                self.on_playqueue_select_playqueue_treeselection_changed)

        self.view.volume_button.connect('value-changed',
                self.on_volume_value_changed)

        for menu_item in self.view.mode_menu.get_children():
            menu_item.connect('activate', self.mode_menu_item_handler)

    def get_name(self):
        return 'control-panel'

    def set_volume(self, value):
        self.view.volume_button.set_value(value)

    def on_volume_value_changed(self, volume_button, value):
        config.volume = value

    def on_play_button_clicked(self, button):
        button.state = State(not button.state)
        self.view.set_pixbuf(button)

    def on_recording_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        sensitivity = bool(treeiter)
        self.view.play_menuitem_set_sensitive(sensitivity)

    def on_playqueue_model_row_inserted(self, model, path, treeiter):
        self.set_play_button_visible(True)
        options_button.sensitize_menuitem('Select', 'Clear queue', True)
        options_button.sensitize_menuitem('Select', 'Remove set', True)

    def on_playqueue_model_row_deleted(self, model, path):
        if not len(model):
            self.set_play_button_visible(False)
            self.view.play_button.state = State.PLAY
            self.view.set_pixbuf(self.view.play_button)
            options_button.sensitize_menuitem('Select', 'Clear queue', False)

    def on_playqueue_select_playqueue_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()
        visible = bool(treeiter)
        options_button.sensitize_menuitem('Select', 'Remove set', visible)

    def set_play_button_visible(self, visible):
        self.view.play_button.props.visible = visible

    def set_mode(self, new_mode):
        for side in ('left', 'right'):
            widgets.top_widget.stacks[side].set_visible_child_full(new_mode,
                    Gtk.StackTransitionType.NONE)
            options_button.set_options_menu(new_mode)
        self.mode = new_mode

        # Focus the left panel. It is important to focus the left panel in
        # Play mode so that Page Up/Page Down will work.
        visible_child = widgets.top_widget.stacks['left'].get_visible_child()
        visible_child.grab_focus()

    def mode_menu_item_handler(self, menu_item):
        new_mode = menu_item.get_label()
        self.set_mode(new_mode)

class ControlPanelView(Gtk.Grid):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.set_column_spacing(24)
        self.set_size_request(-1, 76)

        self.mode_button = mode_button = Gtk.MenuButton(label='Mode')
        mode_button.set_relief(Gtk.ReliefStyle.NONE)
        mode_button.set_valign(Gtk.Align.START)
        mode_button.set_can_focus(False)
        options_button.set_relief(Gtk.ReliefStyle.NONE)
        options_button.set_valign(Gtk.Align.START)
        options_button.set_can_focus(False)
        self.mode_menu = mode_menu = Gtk.Menu()
        self.volume_button = volume_button = Gtk.VolumeButton()
        volume_button.set_valign(Gtk.Align.START)
        volume_button.set_margin_top(2)
        volume_button.set_can_focus(False)
        volume_button.set_has_tooltip(False)
        adjustment = volume_button.get_adjustment()
        adjustment.set_step_increment(0.01)
        adjustment.set_page_increment(0.10)

        # Adjust height of scale in volume button and remove up/down buttons.
        popup = volume_button.get_popup()
        box, = popup.get_children()
        button_up, scale, button_down = box.get_children()
        box.remove(button_up)
        box.remove(button_down)
        scale.set_size_request(-1, 250)

        def get_pixbuf(name):
            pixbuf_fname = Path(f'data/images/playback-{name}.png')
            pixbuf_fname = Path(IMAGES_DIR, f'playback-{name}.png')
            return GdkPixbuf.Pixbuf.new_from_file(str(pixbuf_fname))
        self.play_button_pixbufs = (get_pixbuf('stop'), get_pixbuf('play'))

        self.play_button = play_button = Gtk.Button()
        play_button_pixbuf = self.play_button_pixbufs[State.PLAY.value]
        play_button_image = Gtk.Image.new_from_pixbuf(play_button_pixbuf)
        play_button.set_image(play_button_image)
        play_button.set_name('play-button')
        play_button.set_halign(Gtk.Align.END)
        play_button.set_hexpand(True)
        play_button.state = State.PLAY
        play_button.set_no_show_all(True)
        play_button.set_can_focus(False)

        for label, separate in [('Select', False),
                    ('Play', False),
                    ('Edit', False)]:
            menuitem = Gtk.MenuItem.new_with_label(label)
            mode_menu.append(menuitem)
        mode_menu.show_all()
        mode_button.set_popup(mode_menu)

        self.play_menuitem_set_sensitive(False)

        self.attach(mode_button, 0, 0, 1, 1)
        self.attach(options_button, 1, 0, 1, 1)
        self.attach(volume_button, 2, 0, 1, 1)
        self.attach(play_button, 3, 0, 1, 1)

        self.show_all()

    def set_pixbuf(self, button):
        image = button.get_image()
        image.set_from_pixbuf(self.play_button_pixbufs[button.state.value])

    def play_menuitem_set_sensitive(self, sensitivity):
        play_menuitem = self.mode_menu.get_children()[1]
        play_menuitem.set_sensitive(sensitivity)

