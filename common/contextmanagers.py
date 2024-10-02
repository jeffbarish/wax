"""Context managers."""

import os
from contextlib import contextmanager

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

from .connector import getattr_from_obj_with_name

@contextmanager
def cd_context(directory):
    """Change to directory directory before executing some statements
    and then return to the original directory when done."""
    cwd = os.getcwd()
    os.chdir(str(directory))
    yield
    os.chdir(cwd)

# These two context managers make it possible to stop emission either with
# the name of an object or with the object itself.
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

