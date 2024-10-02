"""Descriptors."""

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

# QuietProperty emits a changed signal only when the new value is actually a
# change from the current value. To use, assign the QuietProperty instance
# to a variable whose name is the name of the desired signal with a leading
# underscore. For example, _images_changed = QuietProperty(**kwargs) will
# generate a signal images-changed only when the value assigned to
# _images_changed is different from the current value of images_changed.
# kwargs are passed to GObject.Property to specify the properties of the
# signal. It is also permissible to assign a value to images_changed if
# the default behavior is preferable.
class QuietProperty:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __set_name__(self, cls, name):
        if not name.startswith('_'):
            raise TypeError('Name must start with "_"')

        self.name = name.lstrip('_')
        if self.name in vars(cls):
            raise TypeError(f'Name {self.name} already in use')

        setattr(cls, self.name, GObject.Property(**self.kwargs))

    # Getting self._image_changed returns self.image_changed. Getting
    # self.image_changed also returns self.image_changed.
    def __get__(self, instance, cls):
        return getattr(instance, self.name)

    # Setting self._image_changed assigns value to self.image_changed only
    # if it is different from value. self.image_changed is a normal Property,
    # so assigning value will trigger a signal even if the value was already
    # value.
    def __set__(self, instance, value):
        if getattr(instance, self.name) != value:
            setattr(instance, self.name, value)

