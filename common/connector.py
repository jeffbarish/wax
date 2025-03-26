"""This module is responsible for connecting signals."""

import logging
import itertools
import functools

from .utilities import debug

# object_dict maps object names to objects in the GUI hierarchy. It scans
# the hierarchy of objects from top. There can be more than one top (e.g.,
# wax, control_panel, player, and ripper).
object_dict: dict[str, object] = {}
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

# To register a request for a connection to a signal, call
# register_connect_request with arguments:
#    source    the name of the object that sends the signal (in the form a.b.c)
#    signal    the name of the signal
#    handler   the handler in the receiver object
_connection_requests = []
def register_connect_request(*args):
    _connection_requests.append(args)

def connect_signals():
    for source, signal, handler in _connection_requests:
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

