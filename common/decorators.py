"""Decorators."""

import logging
from functools import wraps
from inspect import currentframe, getframeinfo
from pathlib import Path

import gi
gi.require_version('GLib', '2.0')
gi.require_version('GObject', '2.0')
from gi.repository import GObject, GLib

# Decorator to trace execution of methods. Note that tracer should come
# after add_emission_stopper because the latter might prevent the function
# from running.
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

# Decorator to detect the _stop_emission flag and stop emission if its
# value corresponds to signal_name. The default handler still runs, but
# custom handlers are blocked.
def emission_stopper(signal_name=None):
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
        @wraps(f)
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

# Instances of subclasses of widgets all get assigned the same object name
# by default. It might not matter, but for the sake of tidiness (and for
# suppressing the warning messages from GTK), this class decorator creates
# unique object names by appending the cardinal number of the instance.
def UniqObjectName(cls):
    cls.inst_num = -1
    orig_init = cls.__init__

    def new_init(self, *args, **kwargs):
        # Note that the superclass is initialized here (so that get_name will
        # work), so be sure that the original __init__ does not contain the
        # same call to the superclass.
        super(cls, self).__init__()

        cls.inst_num += 1
        self.set_name(f'{self.get_name()}-{cls.inst_num}')
        orig_init(self, *args, **kwargs)

    cls.__init__ = new_init
    return cls

