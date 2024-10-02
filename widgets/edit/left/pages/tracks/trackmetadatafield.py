"""A field for displaying and entering secondary track metadata."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject

from common.constants import NOEXPAND
from common.config import config
from common.contextmanagers import signal_blocker
from common.contextmanagers import stop_emission_with_name
from common.decorators import emission_stopper
from common.utilities import debug

class TrackSecondaryMetadataEditor(Gtk.Box):
    @GObject.Signal(flags=GObject.SignalFlags.RUN_FIRST)
    def track_secondary_metadata_changed(self, metadata: object):
        pass

    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_name('track-secondary-metadata-editor')

    def do_key_press_event(self, event):
        visible_fields = self.get_visible_fields()
        if event.keyval == Gdk.KEY_Page_Down:
            # Like clicking the arrow in the last field. The last field
            # must be fully specified.
            if bool(visible_fields[-1]):
                self.on_arrow_button_clicked(visible_fields[-1])
        elif event.keyval == Gdk.KEY_Page_Up:
            # Like clicking the arrow in the penultimate field.
            if len(visible_fields) > 1:
                self.on_arrow_button_clicked(visible_fields[-2])

    @emission_stopper('track-secondary-metadata-changed')
    def do_track_secondary_metadata_changed(self, metadata):
        pass

    def track_metadata_show(self, track_tuple):
        if track_tuple.metadata:
            for key, value in track_tuple.metadata:
                field = self.add_field()
                with stop_emission_with_name('track-secondary-metadata-editor',
                            'track-secondary-metadata-changed'):
                    field.set_text(key, value[0])
        else:
            field = self.add_field()
            field.entry_key.grab_focus()
        self.show()

        # Adjust the arrows.
        # The last visible field always has a right arrow.
        visible_fields = self.get_visible_fields()
        visible_fields[-1].set_arrow_image_right()

        # If there are at least 2 rows, then the penultimate row has a
        # down arrow.
        if len(visible_fields) > 1:
            visible_fields[-2].set_arrow_image_down()

        # Any additional rows have no arrow.
        if len(visible_fields) > 2:
            for field in visible_fields[:-2]:
                field.hide_arrow_image()

    def track_metadata_hide(self):
        for field in self.get_children():
            field.hide()
        self.hide()

    def add_field(self):
        for field in self.get_children():
            if not field.get_visible():
                break
        else:
            field = TrackMetadataField()
            field.connect('arrow-button-clicked', self.on_arrow_button_clicked)
            field.connect('entry-changed', self.on_entry_changed)
            field.connect('field-focus-out', self.on_field_focus_out)
            self.add(field)
        field.set_text('', '')
        field.show()
        field.focus()
        field.arrow_button.set_sensitive(False)
        return field

    def on_arrow_button_clicked(self, field):
        visible_fields = self.get_visible_fields()
        if self.is_last(field):
            if (prev_field := self.get_prev_field(field)) is not None:
                prev_field.hide_arrow_image()
            field.set_arrow_image_down()
            self.add_field()
        else:  # this must be the penultimate field.
            last_field = visible_fields[-1]
            last_field.hide()
            last_field.set_text('', '')
            visible_fields.remove(last_field)
            field.set_arrow_image_right()
            if (prev_field := self.get_prev_field(field)) is not None:
                prev_field.show_arrow_image()
                prev_field.set_arrow_image_down()

    def on_entry_changed(self, field):
        # metadata contains only complete fields.
        metadata = [f.get_text() for f in self.get_visible_fields()
                if bool(f)]
        self.emit('track-secondary-metadata-changed', metadata)

    def on_field_focus_out(self, field):
        # Is there another field with the same key?
        if visible_fields := self.get_visible_fields():
            visible_fields.remove(field)
            for other_field in visible_fields:
                if other_field.key == field.key:
                    other_field.entry_value.grab_focus()
                    other_field.entry_value.set_position(-1)
                    field.hide()
                    visible_fields.remove(field)
                    break

    def get_visible_fields(self):
        return [f for f in self.get_children() if f.get_visible()]

    def get_prev_field(self, field):
        visible_fields = self.get_visible_fields()
        index = visible_fields.index(field) - 1
        if index < 0:
            return None
        return visible_fields[index]

    def is_last(self, field):
        visible_fields = self.get_visible_fields()
        return field == visible_fields[-1]

class TrackMetadataField(Gtk.Box):
    @GObject.Signal
    def arrow_button_clicked(self):
        pass

    @GObject.Signal
    def entry_changed(self):
        pass

    @GObject.Signal
    def field_focus_out(self):
        pass

    # One ListStore for all instances of TrackMetadataField.
    key_liststore = Gtk.ListStore(str)
    for key in config.trackmetadata_keys:
        key_liststore.append((key,))

    def __init__(self):
        super().__init__()
        self.set_orientation(Gtk.Orientation.HORIZONTAL)

        self.arrow_button = arrow_button = Gtk.Button()
        arrow_button.set_relief(Gtk.ReliefStyle.NONE)
        arrow_button.set_can_focus(False)
        arrow_button.set_sensitive(False)
        arrow_button.connect('clicked', self.on_button_clicked)
        arrow_button.show()
        style_context = arrow_button.get_style_context()
        style_context.add_class('arrow-button-track')

        self.arrow_image_down = Gtk.Image.new_from_icon_name(
                'pan-down-symbolic', Gtk.IconSize.BUTTON)
        self.arrow_image_right = Gtk.Image.new_from_icon_name(
                'pan-end-symbolic', Gtk.IconSize.BUTTON)
        self.set_arrow_image_right()

        self.blank_label = blank_label = Gtk.Label.new('')
        blank_label.set_size_request(23, -1)
        blank_label.hide()

        self.entry_key = entry_key = Gtk.Entry()
        entry_key.set_size_request(90, -1)
        entry_key.set_margin_top(1)
        entry_key.set_margin_bottom(2)
        entry_key.set_placeholder_text('key')
        entry_key.show()
        entry_key.connect('changed', self.on_entry_changed)
        entry_key.connect('focus-out-event', self.on_focus_out_event)

        self.entry_value = entry_value = Gtk.Entry()
        entry_value.set_margin_top(1)
        entry_value.set_margin_bottom(2)
        entry_value.set_placeholder_text('value')
        entry_value.show()
        entry_value.connect('changed', self.on_entry_changed)

        self.pack_start(arrow_button, *NOEXPAND)
        self.pack_start(blank_label, *NOEXPAND)
        self.pack_start(entry_key, *NOEXPAND)
        self.pack_start(entry_value, True, True, 1)

        self.hide()

        self.key_completion = Gtk.EntryCompletion.new()
        self.key_completion.set_model(self.key_liststore)
        self.key_completion.set_text_column(0)
        self.key_completion.set_inline_completion(True)
        self.key_completion.set_popup_single_match(False)

        self.entry_key.set_completion(self.key_completion)

    def __bool__(self):
        return bool(self.entry_key.get_text() and self.entry_value.get_text())

    def on_button_clicked(self, button):
        self.emit('arrow-button-clicked')

    def on_entry_changed(self, entry, *args):
        sensitive = self.entry_key.props.text and self.entry_value.props.text
        self.arrow_button.set_sensitive(sensitive)

        key, value = self.get_text()
        self.emit('entry-changed')

    def on_focus_out_event(self, entry, event):
        text = entry.get_text()
        if text:
            for row in self.key_liststore:
                if text == row[0]:
                    self.key_liststore.remove(row.iter)
            else:
                if len(self.key_liststore) > 6:
                    treeiter = self.key_liststore.get_iter_first()
                    self.key_liststore.remove(treeiter)
            self.key_liststore.append((text,))
        self.emit('field-focus-out')

    def set_arrow_image_right(self):
        self.arrow_button.set_image(self.arrow_image_right)

    def set_arrow_image_down(self):
        self.arrow_button.set_image(self.arrow_image_down)

    def hide_arrow_image(self):
        self.arrow_button.hide()
        self.blank_label.show()

    def show_arrow_image(self):
        self.blank_label.hide()
        self.arrow_button.show()

    def set_text(self, key, value):
        # Programmatic setting should not emit changed.
        with signal_blocker(self.entry_key, 'changed'):
            self.entry_key.set_text(key)
        with signal_blocker(self.entry_value, 'changed'):
            self.entry_value.set_text(value)
        self.set_arrow_image_right()
        self.show_arrow_image()
        self.arrow_button.set_sensitive(True)

    def get_text(self):
        return self.entry_key.get_text(), [self.entry_value.get_text()]

    def focus(self):
        self.entry_key.grab_focus()

    @property
    def key(self):
        return self.entry_key.get_text()

