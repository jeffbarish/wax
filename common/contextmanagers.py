"""Context managers."""

import os
from contextlib import contextmanager, suppress

import gi
gi.require_version('GObject', '2.0')
from gi.repository import GObject

from .connector import getattr_from_obj_with_name

# These two context managers make it possible to stop emission either with
# the name of an object or with the object itself. If is not unusual to
# use the context to stop emission of a signal from an object in more than
# one place. The first context to exit will delete obj._stop_emission, so
# suppress AttributeError when subsequent ones attempt to delete the same
# attribute.
@contextmanager
def stop_emission_with_name(obj_name, signal):
    obj = getattr_from_obj_with_name(obj_name)
    obj._stop_emission = signal
    yield
    with suppress(AttributeError):
        del obj._stop_emission

@contextmanager
def stop_emission(obj, signal):
    obj._stop_emission = signal
    yield
    with suppress(AttributeError):
        del obj._stop_emission

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

# Time a block of code.
@contextmanager
def timer(message):
    from time import time
    start_time = time()
    yield
    elapsed_time = time() - start_time
    print(f'{message} {elapsed_time * 1000.0:.2f}ms')

