"""Utility functions."""

import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

def debug(arg, comment=''):
    if comment:
        comment += ': '
    frame = sys._getframe(1)
    value = eval(arg, frame.f_globals, frame.f_locals)
    print(f'{comment}{arg} = {repr(value)} ({type(value)})')

def make_time_str(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours:2}:{minutes:02}:{seconds:02}'
    return f'{minutes:2}:{seconds:02}'

def css_load_from_data(css_data):
    screen = Gdk.Screen.get_default()
    css_provider = Gtk.CssProvider()
    style_context = Gtk.StyleContext()
    style_context.add_provider_for_screen(screen, css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    css_provider.load_from_data(css_data.encode('utf-8'))

# Extract the TrackTuples corresponding to track_ids.
def playable_tracks(tracks, track_ids):
    track_dict = {t.track_id: t for t in tracks}
    return [track_dict[track_id] for track_id in track_ids]

