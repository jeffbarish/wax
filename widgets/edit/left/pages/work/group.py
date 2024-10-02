"""Class for groups of metadata fields (for primary, secondary, and
nonce metadata)."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from common.connector import getattr_from_obj_with_name
from common.constants import NOEXPAND
from common.decorators import UniqObjectName
from common.utilities import debug
from .fields import PrimaryWorkMetadataField
from .fields import SecondaryWorkMetadataField
from .fields import NonceWorkMetadataField

@UniqObjectName
class WorkMetadataGroup(Gtk.Frame):
    """A WorkMetadataGroup is a Gtk.Frame for one metadata class (i.e.,
    primary, secondary, or nonce)."""

    @GObject.Signal
    def work_metadata_group_changed(self):
        pass

    def __new__(cls, *args, **kwargs):
        cls.set_css_name('work-metadata-group')
        return super().__new__(cls)

    def __init__(self, editor, metadata_class):
        self.editor = editor
        self.metadata_class = metadata_class

        # The type of fields in this group (e.g., PrimaryWorkMetadataField).
        field_type_name = f'{metadata_class.capitalize()}WorkMetadataField'
        self.field_type = globals()[field_type_name]

        self.label = label = Gtk.Label()
        label.set_markup(f'''<span foreground="gray"
                size="small">{metadata_class}</span>''')
        label.props.margin_start = label.props.margin_end = 1
        self.set_label_widget(label)
        self.set_label_align(0.02, 0.5)
        self.set_margin_end(2)

        vbox = Gtk.VBox()
        vbox.set_spacing(3)
        self.add(vbox)

    def __bool__(self):
        # self.values is self.field_type.metadata_fields.values
        # (fields of the type for the group).
        return all(bool(value) for value in self.values())

    # Delegate to the instance map for the field_type of this group.
    def __getattr__(self, attr):
        # Refer to the metadata_fields dict in the field_type that corresponds
        # to this group (e.g., PrimaryWorkMetadataField) for attr (e.g., keys,
        # values, or items). Asking for values, for example, on this group
        # returns values on metadata_fields, which is an iterator over the
        # fields in this group. To get the values in the fields, ask for
        # values() on the fields.
        return getattr(self.field_type.metadata_fields, attr)

    # Automatic delegation does not work for some special methods.
    def __contains__(self, val):
        return self.field_type.metadata_fields.__contains__(val)

    def __getitem__(self, key):
        return self.field_type.metadata_fields.__getitem__(key)

    def __iter__(self):  # yields keys
        return self.field_type.metadata_fields.__iter__()

    def create(self, keys, widths=None):
        self.field_type.clear()

        vbox = self.get_child()
        for field in vbox.get_children():
            vbox.remove(field)
            field.destroy()

        for key in keys:
            field = self.field_type(self)
            field.connect('work-metadata-field-changed',
                    self.on_work_metadata_field_changed)
            vbox.pack_start(field, *NOEXPAND)

            field.set_key(key)
            field.show_all()

        if self.metadata_class == 'primary':
            self.focus_first_entry()

            recording_view = getattr_from_obj_with_name('recording-view')
            for field, width in zip(self.values(), widths):
                field.set_column_width(width)
                recording_view.connect('column-widths-changed',
                        self.on_column_widths_changed)

    def on_column_widths_changed(self, recording_view, widths):
        vbox = self.get_child()
        fields = vbox.get_children()
        for field, width in zip(fields, widths):
            field.set_column_width(width)

    # Get the metadata field for each key and populate the value fields.
    def populate(self, metadata):
        for key, values in metadata:
            field = self.field_type.get(key)
            field.populate(values)

    def clear(self):
        vbox = self.get_child()
        for field in vbox.get_children():
            field.clear_values()

    def focus_first_entry(self):
        vbox = self.get_child()
        fields = vbox.get_children()
        first_field = fields[0]
        first_field.focus_first_entry()

    def on_work_metadata_field_changed(self, group):
        self.emit('work-metadata-group-changed')

class NonceWorkMetadataGroup(WorkMetadataGroup):
    def populate(self, metadata):
        # Because this group is nonce, the fields do not exist yet.
        keys = [key for key, values in metadata]
        self.create(keys)

        for key, values in metadata:
            field = NonceWorkMetadataField.get(key)
            field.set_key(key)
            field.populate(values)

    def append_field(self):
        vbox = self.get_child()
        for field in vbox.get_children():
            if not field.props.visible:
                break
        else:
            field = NonceWorkMetadataField(self)
            field.connect('work-metadata-field-changed',
                    self.on_work_metadata_field_changed)
            vbox.pack_start(field, *NOEXPAND)
        field.show_all()

    def clear(self):
        vbox = self.get_child()
        for field in vbox.get_children():
            field.set_key('')
            field.clear_values()
            field.hide()
        self.hide()
        NonceWorkMetadataField.clear()

    def remove_metadata_field(self, field):
        vbox = self.get_child()
        vbox.remove(field)
        if not vbox.get_children():
            self.hide()

    # An invalid nonce lacks either a key or a value. If no nonce fields
    # remain after removing invalid ones, hide the nonce group.
    def purge_invalid_nonces(self):
        vbox = self.get_child()
        for field in vbox.get_children():
            # field.values returns a list of tuples with one value for each
            # row of the value. The zip generates a list of tuples with the
            # values for all the rows (there is only one tuple in the list).
            # The next grabs the first (and only) such tuple. If all of the
            # values are nil, remove the field. field will not have attribute
            # key if key was never set. In that case, the field also was not
            # mapped. If it was set but then deleted, then the attribute has
            # value '' and it has already been removed from metadata_fields
            # and all_keys (in fields.on_key_changed), so it is necessary
            # only to remove the field from vbox.
            key = getattr(field, 'key', None)
            if not key or not any(next(zip(*field.values()))):
                self.remove_metadata_field(field)

