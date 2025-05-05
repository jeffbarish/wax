"""Provide play functionality for recordings in the Wax database from a
web page, thereby enabling control from any platform with a browser."""

import os
import pickle
import shelve
import string
from functools import partial
from nicegui import ui, run
from pathlib import Path
from typing import NamedTuple, Iterator
from unidecode import unidecode

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gio, Gst

from common.config import config
from common.constants import LONG, IMAGES, SHORT, SOUND
from common.genrespec import genre_spec

type NameGroup = tuple[str, ...]  # could be only 1 str

class ShortMetadata(NamedTuple):
    names: tuple[str, ...]
    uuid: str
    work_num: int

def normalize(text: str) -> str:
    text = text.strip()
    text = text.strip(string.punctuation)
    text = text.lower()
    return unidecode(text)

def joiner(name_group: tuple) -> str:
    return ', '.join(name_group)

def sort_key(short_metadata: ShortMetadata) -> tuple[str, ...]:
    return tuple(normalize(name) for name in short_metadata.names)

def ellipsize(val: str, max_len: int) -> str:
    return val if len(val) < max_len else f'{val[:max_len-1]}\u2026'

class MiniWax:
    def __init__(self):
        Gst.init(None)
        self.position = 0

        # Initialize volume control from .miniwax file.
        with open('.minimax', 'r') as fo:
            volume_value = int(fo.read())

        # Page layout.
        ui.query('body').style('background-color: #444444; color: #eeeeee')

        with ui.row():
            self.cover_image = ui.image().classes('w-80')
            self.long_metadata_label = \
                    ui.label('').style('white-space: pre-wrap')

        with ui.row(align_items='center'):
            with ui.card().tight().props('flat bordered').classes(
                    'p-0').style('background-color: #777777'):
                with ui.row():
                    self.play_button = ui.button(icon='play_circle',
                            color='#777777',
                            on_click=self.do_play).classes(
                                    'p-2 m-0').props('flat')
                    self.pause_button = ui.button(icon='pause_circle',
                            color='#777777',
                            on_click=self.do_pause).classes(
                                    'p-2 m-0').props('flat')
                    self.slider = ui.slider(min=0, max=100, value=volume_value,
                            on_change=self.do_volume).classes('w-64 p-2 m-0')
                self.progressbar = ui.linear_progress(value=0.0,
                            show_value=False).props('instant-feedback')
        self.track_title = ui.label('').style('white-space: pre-wrap')

        with ui.button_group():
            with ui.dropdown_button('', auto_close=True, color='#777777'
                        ).classes('mt-4').props('no-caps size=13px'
                        ) as self.genre_button:
                for genre_name in genre_spec:
                    func = partial(self.on_genre_button_click, genre=genre_name)
                    ui.item(genre_name, on_click=func).style(
                            'background-color: #777777; font-size: 12px;'
                            ).props('dense')
            self.subgenre_button = ui.dropdown_button('Subgenre',
                        auto_close=True, color='#777777'
                    ).classes('mt-4').props('no-caps size=13px')

        with ui.scroll_area().classes('-ms-4 -my-2') as self.scroll_area:
            self.table = ui.table(rows=[]).props('dense').classes('-mt-4')
            self.table.style('background-color: #777777; color: #eeeeee')
            self.table.on('rowClick', self.on_table_row_click)

        # Initialize the display by pretending that the user selected a
        # genre and a work.
        self.on_genre_button_click('Anthology')
        self.details_view(0)

        self.pause_button.disable()

    def get_progress(self) -> float:
        success, position = self.playbin.query_position(Gst.Format.TIME)
        success, duration = self.playbin.query_duration(Gst.Format.TIME)

        if not success:
            # If the user clicks play while play is in progress, both
            # queries are unsuccessful.
            return 0.0
        elif position == duration and not self.track_ids:
            # Detect EOS. Normally, we would get an EOS message from the
            # bus, but running the bus requires a GLib.mainloop.
            self.playbin.set_state(Gst.State.NULL)
            del self.playbin

            self.timer.cancel()
            self.pause_button.disable()
            self.track_title.text = ''
            return 0.0
        else:
            return float(position) / float(duration)

    def start_gstreamer(self):
        try:
            file_name = self.next_track()
        except (IndexError, ValueError):
            self.play_button.disable()
            return
        fo = Gio.File.new_for_path(file_name)

        self.playbin = playbin = Gst.ElementFactory.make('playbin', None)
        playbin.set_property('uri', fo.get_uri())
        playbin.set_property('volume', float(self.slider.value)/100.0)
        playbin.connect('about-to-finish', self.on_about_to_finish)

        playbin.set_state(Gst.State.PLAYING)

        self.timer = ui.timer(1.0,
            callback=lambda: self.progressbar.set_value(self.get_progress()))
        self.pause_button.enable()

    def on_about_to_finish(self, playbin):
        # about-to-finish occurs about 1.3s before the end of the track.
        try:
            file_name = self.next_track()
        except (IndexError, ValueError):
            self.play_button.disable()
            return

        fo = Gio.File.new_for_path(file_name)
        self.playbin.set_property('uri', fo.get_uri())

    def next_track(self) -> str:
        disc_num, track_num = track_id = self.track_ids.pop(0)

        self.track_title.text = f'{track_num+1}: {self.trackid_map[track_id]}'

        # Choose the highest quality sound file available.
        root = os.path.join(SOUND, self.uuid, str(disc_num),
                f'{track_num:02d}')
        for ext in ['.wav', '.flac', '.ogg', '.m4a', '.mp3']:
            file_name = root + ext
            if os.path.exists(file_name):
                return file_name
        else:
            raise ValueError

    def do_play(self):
        if hasattr(self, 'playbin'):
            self.playbin.set_state(Gst.State.NULL)
            del self.playbin
            self.timer.cancel()
            self.progressbar.set_value(0.0)
            self.pause_button.disable()
            self.track_title.text = ''

        ui.timer(0.1, self.start_gstreamer, once=True)

    def do_pause(self):
        if not self.playbin:
            return
        _, state, _ = self.playbin.get_state(Gst.CLOCK_TIME_NONE)
        if state == Gst.State.PAUSED:
            if self.position:
                flag = Gst.SeekFlags.FLUSH
                self.playbin.seek_simple(Gst.Format.TIME, flag, self.position)
            self.playbin.set_state(Gst.State.PLAYING)
        else:
            gst_format = Gst.Format.TIME
            success, self.position = self.playbin.query_position(gst_format)
            self.playbin.set_state(Gst.State.PAUSED)

    def do_volume(self, slider):
        if hasattr(self, 'playbin'):
            self.playbin.set_property('volume', float(slider.value)/100.0)

        with open('.minimax', 'wt') as fo:
            fo.write(str(slider.value))

    def get_short_metadata_for_index(self, index):
        if self.genre_has_subgenre:
            subgenre = self.subgenre_button.text
            i = -1
            for short_metadata in self.short_metadata:
                if short_metadata.names[0] == subgenre:
                    i += 1
                    if i == index:
                        return short_metadata
        else:
            return self.short_metadata[index]

    def details_view(self, index):
        short_metadata = self.get_short_metadata_for_index(index)
        with shelve.open(LONG, 'r') as recording_shelf:
            recording = recording_shelf[short_metadata.uuid]

        work = recording.works[short_metadata.work_num]
        metadata = work.metadata

        self.track_ids = work.track_ids
        self.uuid = short_metadata.uuid

        self.trackid_map = {
                tracktuple.track_id: ellipsize(tracktuple.title, 58)
                    for tracktuple in recording.tracks}

        cover_path = Path(IMAGES, short_metadata.uuid, 'image-00.jpg')
        if not cover_path.is_file():
            cover_path = Path('noimage.png')
        self.cover_image.source = cover_path

        lines = [', '.join(val) for val in metadata if val != ('',)]
        primary_vals_str = '\n'.join(ellipsize(line, 35) for line in lines)
        self.long_metadata_label.text = primary_vals_str

        disc_num, track_num = track_id = self.track_ids[0]
        self.track_title.text = f'{track_num+1}: {self.trackid_map[track_id]}'

    def yield_short_metadata(self, genre
            ) -> Iterator[tuple[tuple[str, ...], str, int]]:
        short_path = Path(SHORT, genre)
        with open(short_path, 'rb') as fo:
            while True:
                try:
                    name_groups, uuid, work_num = pickle.load(fo)
                    # Transform (('name1',), ('name2a', 'name2b'), ('name3',))
                    # to ('name1', 'name2a, name2b', 'name3') and ellipsize
                    # the resulting name strings.
                    names = tuple(ellipsize(joiner(name_group), 30) \
                            for name_group in name_groups)
                    yield ShortMetadata(names, uuid, work_num)
                except EOFError:
                    return

    def on_genre_button_click(self, genre):
        self.genre_button.text = genre
        self.primary_keys = primary_keys = config.genre_spec[genre]['primary']
        self.genre_has_subgenre = (self.primary_keys[0] == 'subgenre')

        # short_data is a list of ShortMetadata tuples.
        self.short_metadata = list(self.yield_short_metadata(genre))
        self.short_metadata.sort(key=sort_key)

        # If the first key is subgenre, leave that value out of the table.
        first_index = int(self.genre_has_subgenre)
        columns = [{'name': col_name,
                'label': col_name.capitalize(),
                'field': col_name,
                'required': True,
                'align': 'left'}
                        for col_name in primary_keys[first_index:]]
        self.table.columns = columns

        if self.genre_has_subgenre:
            self.activate_subgenre_button()
            self.subgenre_button.visible = True
        else:
            self.subgenre_button.visible = False

            rows = [dict(zip(primary_keys, short_metadata.names))
                    for short_metadata in self.short_metadata]
            self.table.rows = rows

            self.details_view(0)
            self.scroll_area.scroll_to(pixels=0)

    def activate_subgenre_button(self):
        # Remove all values from the subgenre_button.
        for element in reversed(list(self.subgenre_button.descendants())):
            self.subgenre_button.remove(element)

        # Collect and order all the subgenre names.
        subgenres = set()
        subgenres.update(short_metadata.names[0]
                for short_metadata in self.short_metadata)
        subgenres = list(subgenres)
        subgenres.sort()

        # Populate the subgenre menu with the subgenres in the genre.
        with self.subgenre_button:
            for subgenre in subgenres:
                func = partial(self.on_subgenre_button_click,
                        subgenre=subgenre)
                ui.item(subgenre, on_click=func).style(
                        'background-color: #777777; font-size: 12px;'
                        ).props('dense')

        self.on_subgenre_button_click(subgenres[0])

    def on_subgenre_button_click(self, subgenre):
        self.subgenre_button.text = subgenre

        rows = [dict(zip(self.primary_keys, short_metadata.names))
                for short_metadata in self.short_metadata
                    if short_metadata.names[0] == subgenre]
        self.table.rows = rows

        self.details_view(0)
        self.scroll_area.scroll_to(pixels=0)

    def on_table_row_click(self, msg):
        self.details_view(msg.args[2])
        self.play_button.enable()
        if hasattr(self, 'playbin'):
            self.playbin.set_state(Gst.State.NULL)
            del self.playbin
            self.timer.cancel()

        self.pause_button.disable()
        self.progressbar.set_value(0.0)


if __name__ in {"__main__", "__mp_main__"}:
    miniwax = MiniWax()
    ui.run()

