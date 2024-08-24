"""This module is responsible for signals: connecting, blocking, and stopping.

Connecting:

To register a request for a connection, call register_connect_request
with arguments:
    source    the name of the object that sends the signal (in the form a.b.c)
    signal    the name of the signal
    handler   the handler in the receiver object
"""

import logging
import itertools
import functools
from contextlib import contextmanager

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject

from common.utilities import debug

# object_dict maps object names to objects in the GUI hierarchy. It scans
# the hierarchy of objects from top. There can be more than one top (e.g.,
# wax and player).
object_dict = {}
def traverse_widgets(tops):
    ignored_names = []
    def get_children(obj):
        if hasattr(obj, 'get_name'):
            name = obj.get_name()
            # The default name is 'Gtk' followed by the type of the object. I
            # am not interested in objects to which I have not assigned a name.
            if not name.startswith('Gtk'):
                if name in ignored_names:
                    return
                if name in object_dict:
                    ignored_names.append(name)
                    del object_dict[name]
                    return
                object_dict[name] = obj
        if hasattr(obj, 'get_children'):
            for child in obj.get_children():
                get_children(child)
    for top in tops:
        get_children(top)

    # Ignore object names that are used more than once, but list them in
    # the warning only once. Names might be used more than once for css.
    if ignored_names:
        ignored_names.sort()
        for name, g in itertools.groupby(ignored_names):
            logging.warning(f'Ignoring object name \'{name}\' '
                    f'(used for more than one object)')

_connection_requests = []
def register_connect_request(*args):
    _connection_requests.append(args)

def connect_signals():
    for args in _connection_requests:
        source, signal, handler = args
        obj_name, *attr_names = source.split('.')
        try:
            obj = object_dict[obj_name]
        except KeyError:
            raise ValueError(f'Cannot connect signal \'{signal}\' from '
                    f'\'{obj_name}\' to '
                    f'\'{handler.__qualname__}\': '
                    f'Source object not found') from None
        try:
            obj = functools.reduce(getattr, attr_names, obj)
        except AttributeError:
            raise ValueError(f'Cannot connect signal \'{signal}\' from '
                    f'\'{source}\' to '
                    f'\'{handler.__qualname__}\''
                    f': Some attribute in {attr_names} does not exist') \
                from None
        try:
            obj.connect(signal, handler)
        except TypeError:
            raise ValueError(f'Object \'{source}\' does not produce signal '
                    f'\'{signal}\' sought by '
                    f'\'{handler.__qualname__}\'') \
                from None
        logging.info(f'Connected signal \'{signal}\' '
                f'from object \'{obj_name}\' to '
                f'\'{handler.__qualname__}\'')

# The qual_name is obj_name.attr_name1.attr_name2... Replace obj_name with
# the actual object and then apply the attr_names to its attributes.
def getattr_from_obj_with_name(qual_name):
    obj_name, *attr_names = qual_name.split('.')
    return functools.reduce(getattr, attr_names, object_dict[obj_name])

# These two functions make it possible to stop emission either with the name
# of an object or with the object itself.
@contextmanager
def stop_emission_with_name(obj_name, signal):
    obj = getattr_from_obj_with_name(obj_name)
    obj._stop_emission = signal
    yield
    try:
        del obj._stop_emission
    except AttributeError:
        pass

@contextmanager
def stop_emission(obj, signal):
    obj._stop_emission = signal
    yield
    try:
        del obj._stop_emission
    except AttributeError:
        pass

# Decorator to detect the _stop_emission flag and stop emission if its
# value corresponds to signal_name. The default handler still runs, but
# custom handlers are blocked.
def add_emission_stopper(signal_name=None):
    def wrapper(f):
        nonlocal signal_name
        if signal_name is None:
            if f.__name__.startswith(('do_', 'on_')):
                signal_name = f.__name__[3:].replace('_', '-')
            else:
                raise ValueError(f'Cannot find default name for signal from'
                        f' handler name {f.__name__}')
        logging.info(f'Added emission stopper for signal \'{signal_name}\' '
                f'to handler \'{f.__name__}\'')
        @functools.wraps(f)
        def new_f(self, obj, *args, **kwargs):
            try:
                if obj._stop_emission == signal_name:
                    GObject.signal_stop_emission_by_name(obj, signal_name)
                    # from gi.repository import Gtk
                    # if isinstance(obj, Gtk.TreeSelection):
                    #     treeview = obj.get_tree_view()
                    #     print(f'Stopped emission of signal \'{signal_name}\''
                    #             f' from object'
                    #             f' \'{treeview.get_name()}.selection\'')
                    # else:
                    #     print(f'Stopped emission of signal \'{signal_name}\''
                    #             f' from object \'{obj.get_name()}\'')
                    # # print(f'Stopped emission of signal \'{signal_name}\''
                    # #         f' from object \'{obj}\'')
            except AttributeError:
                return f(self, obj, *args, **kwargs)
        return new_f
    return wrapper

# Block the default handler for signal in gtk_object. Custom handlers
# still run.
@contextmanager
def signal_blocker(gtk_object, signal):
    signal_id = GObject.signal_lookup(signal, type(gtk_object))
    handler_id = GObject.signal_handler_find(gtk_object,
            GObject.SignalMatchType.ID, signal_id, 0, None, None, None)
    GObject.signal_handler_block(gtk_object, handler_id)
    yield
    GObject.signal_handler_unblock(gtk_object, handler_id)

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

