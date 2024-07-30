"""Classes for fields in the metadata form (primary, secondary, and
custom)."""

from pathlib import Path
from unidecode import unidecode

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, Gdk

from common.connector import stop_emission, add_emission_stopper
from common.constants import COMPLETERS, IMAGES_DIR, NOEXPAND
from common.utilities import debug
from widgets import config
from .abbreviators import abbreviator

class WorkMetadataField(Gtk.Grid):
    @GObject.Signal(flags=GObject.SignalFlags.RUN_FIRST)
    def work_metadata_field_changed(self):
        pass

    def __init__(self, group):
        super().__init__()
        self.group = group
        self.entries = []  # list of tuples (which might have len 1) of entries
        self.set_margin_start(3)
        self.set_margin_bottom(3)
        self.set_margin_end(2)
        self.set_row_spacing(3)
        self.set_row_homogeneous(True)

        self.button_right = button_right = ArrowButton(True)
        self.button_down = button_down = ArrowButton(False)
        button_right.connect('clicked', self.on_button_right_clicked)
        button_down.connect('clicked', self.on_button_down_clicked)
        self.connect('work-metadata-field-changed',
                self.on_work_metadata_field_changed)

        self.new_metadata_field()

        # Create models for Gtk.EntryCompletion.
        self.completers = completers = {}
        for completer_fn in COMPLETERS.iterdir():
            completers[completer_fn.name] = model = Gtk.ListStore(str)
            with open(completer_fn, 'rt', encoding='utf-8') as completer_fo:
                for line in completer_fo.read().splitlines():
                    model.append((line,))

    @classmethod
    def get(cls, key):
        return cls.metadata_fields[key]

    @classmethod
    def clear(cls):
        cls.metadata_fields.clear()

    @add_emission_stopper('work-metadata-field-changed')
    def on_work_metadata_field_changed(self, field):
        pass

    def clear_values(self):
        while len(self.entries) > 1:
            self.move_buttons_up()
            with stop_emission(self, 'work-metadata-field-changed'):
                self.remove_last_value_field()
        with stop_emission(self, 'work-metadata-field-changed'):
            self.clear_value_field()

    # Specify the key separately from creation of the field so that it
    # is possible to change the key (for NonceWorkMetadataField).
    def set_key(self, key):
        self.key = key
        self.key_label.set_text(key)

        self.metadata_fields[key] = self

        # Now that this field has a key associated with it, it is possible
        # to attach a completer to the entry.
        self.attach_completer(key)

    def populate(self, values):
        self.clear_values()
        self.set_text_first_value(values[0])
        for value in values[1:]:
            self.move_buttons_down()
            self.append_value_field(value)

    def new_metadata_field(self):
        self.add_key_field()
        self.attach(self.button_right, 1, 0, 1, 1)
        self.append_value_field()

    # Gets overridden in NonceWorkMetadataField.
    def add_key_field(self):
        self.key_label = label = Gtk.Label()
        label.set_xalign(0)
        label.set_size_request(80, -1)
        self.attach(label, 0, 0, 1, 1)
        label.show()

    def move_buttons_down(self):
        button_row = len(self.entries) - 1
        self.remove(self.button_right)
        if button_row != 0:
            self.remove(self.button_down)
        self.attach(self.button_down, 1, button_row, 1, 1)
        self.attach(self.button_right, 1, button_row + 1, 1, 1)
        self.button_down.show()
        self.button_right.set_sensitive(False)

    def move_buttons_up(self):
        button_row = len(self.entries) - 2
        self.remove(self.button_down)
        self.remove(self.button_right)
        if button_row >= 1:
            self.attach(self.button_down, 1, button_row - 1, 1, 1)
        else:
            self.button_down.hide()
        self.attach(self.button_right, 1, button_row, 1, 1)
        self.button_right.set_sensitive(True)
        self.entries[button_row][0].grab_focus_without_selecting()

    def clean(self):
        # Pull out all the values and remove null or incomplete fields.
        values = list(filter(all, self.values()))

        # Write remaining values back into the entries starting at the top.
        # set_text does not trigger the changed signal (only typing into the
        # entry does).
        for entries, value in zip(self.entries, values):
            for entry, val in zip(entries, value):
                entry.set_text(val.strip())

        # If there are more entries than values, remove the excess
        # value fields, but always leave one no matter what.
        for _ in range(max(len(values), 1), len(self.entries)):
            self.on_button_down_clicked(self.button_down)

    def values(self):
        # Convert tuples of entries to tuples of entry.get_text(). Note that
        # the tuples here are (long, short) for primary and (long,) for
        # secondary and nonce.
        for entries in self.entries:
            yield tuple(entry.get_text() for entry in entries)

    def make_completion(self, key):
        model = self.completers.get(key, None)
        if model is None:
            return
        else:
            enabled = config['completers'][key][0]
            if not enabled:
                return

        def normalize(text):
            text = text.lower()
            return unidecode(text)
        def match_func(completion, value, tree_iter):
            model = completion.get_model()
            name = normalize(model[tree_iter][0])
            return any(n.startswith(value) for n in name.split())

        completion = Gtk.EntryCompletion()
        completion.set_model(model)
        completion.set_text_column(0)
        completion.set_match_func(match_func)
        completion.set_popup_completion(True)
        return completion

    def pageupdown_cb(self, entry, up):
        if up:
            self.on_button_down_clicked(self.button_down)
        else:
            # All values (two for primary, one for secondary) of the last
            # entry must be non-nil.
            if all(e.get_text() for e in self.entries[-1]):
                self.on_button_right_clicked(self.button_right)

    def on_button_right_clicked(self, button):
        self.move_buttons_down()
        self.append_value_field()
        self.attach_completer(self.key)

    def on_button_down_clicked(self, button):
        # As I call this method on PageUp, it is possible to come here when
        # there is only one value field.
        if len(self.entries) > 1:
            self.move_buttons_up()
            self.remove_last_value_field()

    def on_entry_changed(self, entry):
        self.emit('work-metadata-field-changed')
        self.button_right.set_sensitive(bool(entry.props.text))

    def set_text_first_value(self, value):
        self.button_right.set_sensitive(any(value))

        for entry, val in zip(self.entries[0], value):
            entry.set_text(val)

    def append_value_field(self, value):
        raise NotImplementedError('Define in subclass')

    def clear_value_field(self):
        raise NotImplementedError('Define in subclass')

    def remove_last_value_field(self):
        raise NotImplementedError('Define in subclass')

    def attach_completer(self, key):
        raise NotImplementedError('Define in subclass')

class PrimaryWorkMetadataField(WorkMetadataField):
    metadata_fields = {}

    def __bool__(self):
        # This PrimaryWorkMetadataField is complete if any value (the pairs
        # of entries listed in self.entries) has both entries (long and short)
        # specified.
        return any(all(bool(e.get_text()) for e in entry)
                for entry in self.entries)

    def set_column_width(self, width):
        for entry_long, entry_short in self.entries:
            entry_short.set_size_request(min(width, 305), -1)
            entry_short.queue_draw()

    def append_value_field(self, value=('', '')):
        self.button_right.set_sensitive(any(value))

        # Put the two entry widgets in a vbox so that they still take
        # up one line.
        row_num = len(self.entries)
        cb = self.pageupdown_cb
        entries = entry_long, entry_short = (Entry(self, cb), Entry(self, cb))
        self.entries.append(entries)
        entry_short.entry_long = entry_long

        # Need hexpand True for entry_long (default) but False for
        # entry_short so that entry_short assumes the assigned width.
        entry_short.set_hexpand(False)

        entry_long.connect('changed', self.on_long_changed)
        for val, entry in zip(value, entries):
            entry.set_text(val)
            entry.connect('changed', self.on_entry_changed)

        if len(self.entries) >= 2:
            prev_entry_long, prev_entry_short = self.entries[-2]
            width, height = prev_entry_short.get_size_request()
            entry_short.set_size_request(width, -1)

        # Put entry_short in an hbox so that it can have its requested width.
        hbox = Gtk.Box()
        hbox.set_orientation(Gtk.Orientation.HORIZONTAL)
        hbox.pack_start(entry_short, *NOEXPAND)

        vbox = Gtk.Box()
        vbox.set_orientation(Gtk.Orientation.VERTICAL)
        vbox.set_spacing(1)
        vbox.pack_start(entry_long, *NOEXPAND)
        vbox.pack_start(hbox, *NOEXPAND)
        vbox.show_all()

        self.attach(vbox, 2, row_num, 1, 1)

        entry_long.grab_focus_without_selecting()

    def attach_completer(self, key):
        completion = self.make_completion(key)

        # Attach a completer to the new entry_long every time we append a
        # value field.
        entry_long, entry_short = self.entries[-1]
        entry_long.set_completion(completion)

    def clear_value_field(self):
        self.set_text_first_value(('', ''))

    def remove_last_value_field(self):
        if any(e.get_text() for e in self.entries[-1]):
            self.emit('work-metadata-field-changed')
        row_num = len(self.entries) - 2
        vbox = self.get_child_at(2, row_num + 1)
        for entry in self.entries.pop():
            entry.destroy()
        vbox.destroy()

    def focus_first_entry(self):
        self.entries[0][0].grab_focus_without_selecting()

    def on_long_changed(self, entry):
        text = entry.get_text()
        # Somewhere in self.entries, there is a tuple whose first value
        # is sender. The companion entry is the one to update.
        d = dict(self.entries)  # {entry_long: entry_short}
        entry_short = d[entry]
        entry_short.set_text(abbreviator(text))

class SecondaryWorkMetadataField(WorkMetadataField):
    metadata_fields = {}

    def append_value_field(self, value=('',)):
        self.button_right.set_sensitive(any(value))

        row_num = len(self.entries)
        entry = Entry(self, self.pageupdown_cb)
        entry.set_text(value[0])
        entry.connect('changed', self.on_entry_changed)

        self.attach(entry, 2, row_num, 1, 1)
        self.entries.append((entry,))
        entry.show()
        self.value_entry = entry

        entry.grab_focus_without_selecting()  # focus the new entry

    def attach_completer(self, key):
        completion = self.make_completion(key)

        # Attach a completer to the new entry_long every time we append a
        # value field.
        entry, = self.entries[-1]
        entry.set_completion(completion)

    def remove_last_value_field(self):
        entry, = self.entries.pop()
        if entry.get_text():
            self.emit('work-metadata-field-changed')
        entry.destroy()

    def focus_first_entry(self):
        self.entries[0][0].grab_focus_without_selecting()

    def clear_value_field(self):
        self.set_text_first_value(('',))

class NonceWorkMetadataField(SecondaryWorkMetadataField):
    metadata_fields = {}

    def __str__(self):
        if not self.key:
            return ''
        return ', '.join(repr(t) for t in self.values())

    def set_key(self, key):
        self.key = key
        with stop_emission(self, 'work-metadata-field-changed'):
            self.key_entry.set_text(key)

        self.metadata_fields[key] = self

    def add_key_field(self):
        self.key_entry = entry = Gtk.Entry()
        entry.set_size_request(80, -1)
        entry.connect('changed', self.on_key_changed)
        self.attach(entry, 0, 0, 1, 1)

    # Override changed handler for value entry.
    def on_entry_changed(self, entry):
        self.button_right.set_sensitive(bool(entry.props.text))

        if getattr(self, 'key', ''):
            self.emit('work-metadata-field-changed')

    def on_key_changed(self, entry):
        first_entry, = self.entries[0]
        all_keys = first_entry.all_keys

        newtext = entry.get_text()
        oldtext = getattr(self, 'key', '')
        self.key = newtext
        if newtext in self.metadata_fields:
            # There is another custom field with this key, so move the
            # values to that field and remove this field.
            alt_metadata_field = self.metadata_fields[newtext]
            for value in self.values():
                alt_metadata_field.move_buttons_down()
                alt_metadata_field.append_value_field(value)
            # Remove the field, but leave the key in metadata_fields
            # because it is still custom metadata.
            self.group.remove_metadata_field(self)
            if oldtext:
                del self.metadata_fields[oldtext]
        elif newtext:
            # Otherwise associate newtext with the same field that used to
            # be associated with oldtext (which is self) or self if this
            # mapping is new. The value of the mapping is always self, but
            # the key keeps changing.
            self.metadata_fields[newtext] = \
                    self.metadata_fields.pop(oldtext, self)

            if oldtext in all_keys:
                all_keys.remove(oldtext)
            all_keys.append(newtext)

            # The nonce is not valid until it has a value. The nonce will be
            # deleted on save if it does not have a value.
            if self.value_entry.get_text():
                self.emit('work-metadata-field-changed')
        else:
            # When newtext is nil, this is no longer a valid metadata field,
            # so just delete the old mapping (as usual, but don't create a
            # new one).
            if oldtext in self.metadata_fields:
                del self.metadata_fields[oldtext]

                all_keys.remove(oldtext)
            self.emit('work-metadata-field-changed')

    def unmap_field(self):
        del self.metadata_fields[self.key]

        # Remove self.key from all_keys so that it does not appear in the
        # popup menu for swapping values.
        first_entry, = self.entries[0]
        first_entry.all_keys.remove(self.key)

class ArrowButton(Gtk.Button):
    # css name of Gtk.Button is 'button' by default.
    def __new__(cls, *args, **kwargs):
        cls.set_css_name('arrow-button')
        return super().__new__(cls)

    def __init__(self, right):
        super().__init__()
        arrow_image_down = Gtk.Image.new_from_icon_name('pan-down-symbolic',
                Gtk.IconSize.BUTTON)
        arrow_image_right = Gtk.Image.new_from_icon_name('pan-end-symbolic',
                Gtk.IconSize.BUTTON)
        arrow_image = (arrow_image_down, arrow_image_right)[right]
        self.set_image(arrow_image)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(False)

        right_gray_fn = str(Path(IMAGES_DIR, 'pan-end-symbolic-gray.png'))
        arrow_image_right_gray = Gtk.Image.new_from_file(right_gray_fn)

        self.right_images = (arrow_image_right_gray, arrow_image_right)

    def set_sensitive(self, sensitive):
        self.set_image(self.right_images[sensitive])
        Gtk.Button.set_sensitive(self, sensitive)

class Entry(Gtk.Entry):
    # All Entry instances need to know the full set of keys and the key with
    # which they are associated to create the popup menu for swapping values.
    # editor writes all_keys on genre changed.
    all_keys = []

    def __init__(self, field, pageupdown_cb):
        super().__init__()
        self.set_hexpand(True)
        self.set_width_chars(0)
        self.pageupdown_cb = pageupdown_cb
        self.connect('changed', self.on_changed)
        self.connect('realize', self.on_realize)
        self.field = field
        self.set_can_focus(False)

    def do_key_press_event(self, eventkey):
        if eventkey.keyval == Gdk.KEY_Page_Down:
            self.pageupdown_cb(self, False)
        elif eventkey.keyval == Gdk.KEY_Page_Up:
            self.pageupdown_cb(self, True)
        elif eventkey.keyval == Gdk.KEY_Right:
            # Override default handling so that right arrow moves one character
            # to the right and shift-right arrow moves with selection.
            extend_selection = eventkey.state & Gdk.ModifierType.SHIFT_MASK
            ctrl = eventkey.state & Gdk.ModifierType.CONTROL_MASK
            movement_step = (Gtk.MovementStep.VISUAL_POSITIONS,
                    Gtk.MovementStep.WORDS)[bool(ctrl)]
            self.do_move_cursor(self, movement_step, 1, extend_selection)
            return True
        else:
            Gtk.Entry.do_key_press_event(self, eventkey)

    def do_populate_popup(self, menu):
        # Remove the "Insert Emoji" item.
        for item in menu.get_children():
            if item.get_label() == 'Insert _Emoji':
                menu.remove(item)
                break

        separator_item = Gtk.SeparatorMenuItem()

        self.clear_item = clear_item = Gtk.MenuItem.new_with_label('Clear')
        clear_item.set_sensitive(bool(self.props.text))
        clear_item.connect('activate', self.on_clear_activated)

        reverse_item = Gtk.MenuItem.new_with_label('Reverse')
        reverse_item.set_sensitive(',' in self.get_text())
        reverse_item.connect('activate', self.on_reverse_activated)

        use_long_item = Gtk.MenuItem.new_with_label('Use long')
        is_short_entry = hasattr(self, 'entry_long')
        sensitive = (is_short_entry and self.entry_long.get_text())
        use_long_item.set_sensitive(sensitive)
        use_long_item.connect('activate', self.on_use_long_activated)

        menu.append(separator_item)
        menu.append(clear_item)
        menu.append(reverse_item)
        menu.append(use_long_item)

        # A nonce might not have a key. Do not provide a swap menu if the
        # nonce is not valid.
        if self.field.key:
            swap_keys = list(Entry.all_keys)
            swap_keys.remove(self.field.key)

            separator_item = Gtk.SeparatorMenuItem()
            swap_with_item = Gtk.MenuItem.new_with_label('Swap with')
            swap_menu = Gtk.Menu()
            for key in swap_keys:
                item = Gtk.MenuItem.new_with_label(key)
                item.connect('activate', self.on_swap_activated)
                swap_menu.append(item)
            swap_with_item.set_submenu(swap_menu)

            menu.append(swap_with_item)

        menu.show_all()

    @add_emission_stopper('changed')
    def on_changed(self, entry):
        if hasattr(self, 'clear_item'):
            self.clear_item.set_sensitive(bool(self.props.text))

    # After starting wax, this widget gets focus. As it has not yet been
    # exposed, it is not realized. As a result, pressing any key generates
    # a critical error. To avoid this problem, I set can-focus to False and
    # then fix it here after the widget has been realized.
    def on_realize(self, widget):
        self.set_can_focus(True)

    def on_clear_activated(self, menuitem):
        super().set_text('')

    def on_reverse_activated(self, menuitem):
        # Reverse the text at the first comma.
        text = self.get_text()
        text_split = text.split(', ', 1)
        super().set_text(' '.join(reversed(text_split)))

    def on_use_long_activated(self, menuitem):
        text = self.entry_long.get_text()
        super().set_text(text)

    def on_swap_activated(self, menuitem):
        editor = self.field.group.editor
        editor.swap_values(self.field, menuitem.get_label())

    # Suppress changed signal when populating the form.
    def set_text(self, text):
        with stop_emission(self, 'changed'):
            super().set_text(text)

