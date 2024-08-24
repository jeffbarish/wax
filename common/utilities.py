import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from inspect import currentframe, getframeinfo
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

def debug(arg, comment=''):
    if comment:
        comment += ': '
    frame = sys._getframe(1)
    value = eval(arg, frame.f_globals, frame.f_locals)
    print(f'{comment}{arg} = {repr(value)} ({type(value)})')

# Decorator to trace execution of methods -- handlers, typically. Note that
# tracer should come after add_emission_stopper because the latter might
# prevent the function from running.
def tracer(f):
    @wraps(f)
    def new_f(*args, **kwargs):
        frameinfo = getframeinfo(currentframe().f_back)
        filename = Path(frameinfo.filename).name
        lineno = frameinfo.lineno
        print(f'TRACER: Executing function {f.__name__} '
                f'at {filename}:{lineno}')
        try:
            return f(*args, **kwargs)
        finally:
            print(f'TRACER: Done executing function {f.__name__}')
    return new_f

# Decorator to execute a function when the event loop becomes idle.
def idle_add(f):
    @wraps(f)
    def new_f(*args, **kwargs):
        GLib.idle_add(f, *args, **kwargs)
    return new_f

# Decorator to execute a function after a delay.
def timeout_add(delay):
    def inner(f):
        @wraps(f)
        def new_f(*args, **kwargs):
            GLib.timeout_add(delay, f, *args, **kwargs)
        return new_f
    return inner

@contextmanager
def cd_context(directory):
    """Change to directory directory before executing some statements
    and then return to the original directory when done."""
    cwd = os.getcwd()
    os.chdir(str(directory))
    yield
    os.chdir(cwd)

def css_load_from_data(css_data):
    screen = Gdk.Screen.get_default()
    css_provider = Gtk.CssProvider()
    style_context = Gtk.StyleContext()
    style_context.add_provider_for_screen(screen, css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    css_provider.load_from_data(css_data.encode('utf-8'))

# Wrap a treemodel in a class with a __getitem__ to return a row wrapped
# in a class that knows about field names. The wrapped row has __getattr__
# and __setattr__ to convert named attributes to the appropriate numeric
# index into the row. I use a NamedTuple to specify the fields because
# it provides self-documentation of the fields. Also, I use the NamedTuple
# by itself in situations where I only read from the model.
class ModelWithAttrs:
    def __init__(self, model, row_tuple):
        self.model = model
        self.row_tuple = row_tuple

    def __getattr__(self, attr):
        return getattr(self.model, attr)

    def __getitem__(self, index):
        row = self.model[index]
        return ModelRowWithAttrs(self.row_tuple, row)

    def __iter__(self):
        return (ModelRowWithAttrs(self.row_tuple, row) for row in self.model)

    def __len__(self):
        return len(self.model)

    def row_has_child(self, row):
        return self.model.iter_has_child(row.iter)

class ModelRowWithAttrs:
    def __init__(self, row_tuple, row):
        self.__dict__['row'] = row
        self.__dict__['row_tuple'] = row_tuple._make(row)
        self.__dict__['fields'] = row_tuple._fields

    def __iter__(self):
        return iter(self.__dict__['row_tuple'])

    def __getattr__(self, attr):
        # Look first in the row_tuple for attr and then in the row (e.g.,
        # for iter or path).
        try:
            return getattr(self.row_tuple, attr)
        except AttributeError:
            try:
                return getattr(self.row, attr)
            except AttributeError:
                message = f'{type(self).__name__} ' \
                    f'(based on {type(self.row_tuple).__name__}) ' \
                    f'has no attribute \'{attr}\''
                raise AttributeError(message) from None

    def __setattr__(self, attr, value):
        self.__dict__['row_tuple'] = self.row_tuple._replace(**{attr: value})

        index = self.fields.index(attr)
        self.row[index] = value

    def __repr__(self):
        return repr(self.row_tuple)

    def iterchildren(self):
        return (ModelRowWithAttrs(self.row_tuple, row)
                for row in self.row.iterchildren())

def make_time_str(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours:2}:{minutes:02}:{seconds:02}'
    return f'{minutes:2}:{seconds:02}'

# Extract the TrackTuples corresponding to track_ids.
def playable_tracks(tracks, track_ids):
    track_dict = {t.track_id: t for t in tracks}
    return [track_dict[track_id] for track_id in track_ids]

