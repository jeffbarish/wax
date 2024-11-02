"""
The play engine is a subprocess for playing a sound file using GStreamer.
PlayEngineLauncher starts it. It receives commands from PlayEngineLauncher
over stdin and sends messages back over stdout.
"""

import os
import sys
import json
import random
import signal
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio
from gi.repository import Gst
from gi.repository import GLib

os.sched_setaffinity(os.getpid(), (3,))

class Track(NamedTuple):
    uuid: str
    trackid: tuple
    duration: int

SOUND = Path('recordings', 'sound')

# Decorator to register methods that respond to commands from player.
command_map = {}
def command(f):
    command = f.__name__.removeprefix('on_').replace('_', '-')
    command_map[command] = f
    return f


class PlayEngine:
    def __init__(self):
        Gst.init(None)
        self.tracks = []
        self.random = False
        self.track_position = -1
        self.about_to_finish = False
        self.timer_id = None

        signal.signal(signal.SIGINT, self.on_signal)

        self.cancellable = Gio.Cancellable()

        self.playbin = playbin = Gst.ElementFactory.make('playbin', None)
        playbin.connect('about-to-finish', self.on_about_to_finish)

        # Create bus to get events from GStreamer pipeline
        self.bus = self.playbin.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message::eos', self.on_eos)
        self.bus.connect('message::error', self.on_error)

        input_stream = Gio.UnixInputStream.new(0, True)
        self.data_input_stream = Gio.DataInputStream.new(input_stream)
        self.queue_read()

        self.loop = GLib.MainLoop()
        self.loop.run()

    def on_signal(self, signal, frame):
        self.cancellable.cancel()
        self.loop.quit()

    def on_error(self, bus, msg):
        print('on_error():', msg.parse_error(), file=sys.stderr)
        self.playbin.set_state(Gst.State.NULL)
        self.set_state('NULL')

    def on_eos(self, bus, msg):
        self.stop_progress_timer()
        self.set_state('NULL')
        self.send_reply('track-finished', len(self.tracks),
                *self.track.trackid)
        self.send_reply('set-finished')
        self.about_to_finish = False

    def on_about_to_finish(self, playbin):
        # about-to-finish occurs about 1.3s before the end of the track.
        self.about_to_finish = True
        try:
            next_track = self.pop_track()
        except (IndexError, ValueError):
            next_track = None

        self.set_uri_for_track(next_track)

    def pop_track(self):
        pop_index = 0 if not self.random \
                else random.randrange(0, len(self.tracks))
        return self.tracks.pop(pop_index)

    def set_uri_for_track(self, track):
        if track is None:
            self.next_track = None
            return

        try:
            file_name = self.best_version(track.uuid, track.trackid)
        except FileNotFoundError:
            file_name = str(Path('data', 'alert.ogg'))

            # Flag the track as invalid by setting uuid = -1, but preserve
            # trackid and duration so that track-started and track-finished
            # replies can provide information required to update the display.
            track = track._replace(uuid=-1)

        fo = Gio.File.new_for_path(file_name)
        self.playbin.set_property('uri', fo.get_uri())

        self.next_track = track

    def best_version(self, uuid, trackid):
        disc_num, track_num = trackid

        # Exclude *.part files from glob.
        paths = Path(SOUND, uuid, str(disc_num)).glob(f'{track_num:02d}.*')
        paths = [str(p) for p in paths if p.suffix != '.part']

        # Choose the highest quality sound file available.
        codecs = ['wav', 'flac', 'ogg', 'm4a', 'mp3']
        paths = sorted(paths,
                key=lambda p: codecs.index(p.rsplit('.', 1)[1]))

        if not paths:
            raise FileNotFoundError

        return paths[0]

    # The progress timer runs continuously as long as there are tracks to
    # play except when seeking.
    def start_progress_timer(self):
        def on_progress_timer():
            track_position = self.get_position()

            # Detect the actual transition to the next track by comparing the
            # current track position to the previous one after getting the
            # about to finish signal (otherwise, we could be setting the
            # position to an earlier time in the track).
            if self.about_to_finish and track_position < self.track_position:
                self.start_new_track()
            else:
                self.send_position(track_position)
            self.track_position = track_position
            return True
        self.timer_id = GLib.timeout_add(500, on_progress_timer)

    def stop_progress_timer(self):
        if self.timer_id is not None:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

    def send_position(self, track_position):
        if self.track.uuid != -1:
            track_position = min(track_position, self.track.duration)
        else:
            # We are not interested in displaying progress through the
            # alert sound, so force track position to 0.
            track_position = 0
        set_position = self.segment_start + track_position

        self.send_reply('position', *self._convert_to_secs(
                track_position, self.track.duration,
                set_position, self.set_duration))

    def start_new_track(self):
        self.segment_start += self.track.duration
        self.send_reply('track-finished', len(self.tracks),
                *self.track.trackid)

        self.track = self.next_track
        self.send_reply('track-started',
                *self._convert_to_secs(self.track.duration),
                bool(self.tracks), *self.track.trackid)

        self.about_to_finish = False

    def get_state(self):
        _, state, _ = self.playbin.get_state(Gst.CLOCK_TIME_NONE)
        return state

    def set_state(self, state):
        self.playbin.set_state(getattr(Gst.State, state))
        self.send_reply('state', state)

    def get_position(self):
        success, position = self.playbin.query_position(Gst.Format.TIME)
        return position

    def queue_read(self):
        self.data_input_stream.read_line_async(GLib.PRIORITY_DEFAULT,
                self.cancellable, self.on_command_in)

    def send_reply(self, *message):
        text = json.dumps(message)
        print(text, flush=True)

    # -Command handlers--------------------------------------------------------
    def on_command_in(self, source, result):
        line, length = source.read_line_finish_utf8(result)
        if not line:
            return

        command, *args = json.loads(line)
        command_map[command](self, *args)

        self.queue_read()

    @command
    def on_append_queue(self, uuid, trackid, duration):
        self.tracks.append(Track(uuid, trackid, duration))

    @command
    def on_ready_play(self):
        self.set_duration = sum(map(attrgetter('duration'), self.tracks))
        set_duration = self._convert_to_secs(self.set_duration)
        self.send_reply('set-ready', *set_duration)

        self.track = self.pop_track()
        self.send_reply('track-started',
                *self._convert_to_secs(self.track.duration),
                bool(self.tracks), *self.track.trackid)

    @command
    def on_random(self, state):
        if state == self.random:
            return

        self.random = state

        if state and self.get_state() != Gst.State.PLAYING:
            # Restore self.track to self.tracks and then redo on_ready_play.
            # With self.random set, the self.pop_track will make a random
            # selection for the first track to play (and for subsequent
            # tracks).
            self.tracks.insert(0, self.track)
            self.on_ready_play()

    @command
    def on_play(self):
        if self.get_state() == Gst.State.NULL:
            self.set_uri_for_track(self.track)
        self.set_state('PLAYING')
        self.start_progress_timer()

    @command
    def on_next_track(self):
        init_playbin_state = self.get_state()

        # The element must be in state NULL before changing the uri.
        self.set_state('NULL')
        self.send_reply('track-finished', len(self.tracks),
                *self.track.trackid)

        self.about_to_finish = True
        self.segment_start += self.track.duration
        self.track = track = self.pop_track()
        self.set_uri_for_track(track)
        self.send_reply('track-started',
                *self._convert_to_secs(track.duration),
                bool(self.tracks), *track.trackid)

        if init_playbin_state == Gst.State.PLAYING:
            self.set_state('PLAYING')
        else:
            self.send_reply('position', *self._convert_to_secs(
                    0, track.duration,
                    self.segment_start, self.set_duration))
            # Seek triggers a flush event which in turn triggers preroll.
            # The preroll minimizes the delay that otherwise occurs on the
            # transition to PLAYING.
            flag = Gst.SeekFlags.FLUSH
            self.playbin.seek_simple(Gst.Format.TIME, flag, 0)
            self.set_state('PAUSED')

    @command
    def on_pause(self):
        if self.get_state() == Gst.State.PLAYING:
            self.stop_progress_timer()
        self.set_state('PAUSED')

    @command
    def on_stop(self):
        if self.get_state() == Gst.State.PLAYING:
            self.stop_progress_timer()
        self.set_state('NULL')

    @command
    def on_clear_queue(self):
        self.tracks = []
        self.segment_start = 0

    @command
    def on_volume(self, value):
        self.playbin.set_property('volume', float(value))

    @command
    def on_get_state(self):
        STATES = ['VOID_PENDING', 'NULL', 'READY', 'PAUSED', 'PLAYING']
        state = self.get_state()
        self.send_reply('state', STATES[int(state)])

    @command
    def on_set_ratio(self, ratio):
        # Once we start transitioning to the next track, it is too late to
        # set the position.
        if self.about_to_finish:
            return

        match self.get_state():
            case Gst.State.NULL:
                # If we have not started playing yet, go into PLAYING long
                # enough to set the position and then pause.
                self.set_uri_for_track(self.track)
                self.set_state('PLAYING')
                self.get_state()  # this statement is necessary
                self._do_seek(ratio)
                self.set_state('PAUSED')
            case Gst.State.PAUSED:
                self._do_seek(ratio)
            case Gst.State.PLAYING:
                self._do_seek(ratio)

    def _do_seek(self, ratio):
        # Stop the progress timer to be sure that the seek is actually done
        # by the time the timer sends a progress signal.
        self.stop_progress_timer()

        track_duration = self.track.duration
        track_position = round(track_duration * float(ratio))

        flag = Gst.SeekFlags.FLUSH
        self.playbin.seek_simple(Gst.Format.TIME, flag, track_position)

        self.send_position(track_position)
        self.track_position = track_position

        self.start_progress_timer()

    # Convert to seconds in engine so that handlers can apply values directly.
    def _convert_to_secs(self, *args):
        return tuple(arg / Gst.SECOND for arg in args)


if __name__ == '__main__':
    play_engine = PlayEngine()

