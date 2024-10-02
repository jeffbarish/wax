"""The rip engine is a subprocess for ripping a CD using GStreamer.
EngineLauncher starts it. It receives commands from EngineLauncher
over stdin and sends messages back over stdout."""

import os
import json
import signal
import sys
from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio
from gi.repository import Gst
from gi.repository import GLib

SOUND = Path('recordings', 'sound')
PRIORITY = GLib.PRIORITY_DEFAULT
STATES = ['VOID_PENDING', 'NULL', 'READY', 'PAUSED', 'PLAYING']

os.sched_setaffinity(os.getpid(), (2,))

# Decorator to register methods that respond to commands from player.
command_map = {}
def command(f):
    command = f.__name__[3:].replace('_', '-')
    command_map[command] = f
    return f


class Ripper:
    def __init__(self):
        Gst.init(None)
        self.timer_id = None

        signal.signal(signal.SIGINT, self.on_signal)

        self.cancellable = Gio.Cancellable()

        cd_src = Gst.ElementFactory.make('cdparanoiasrc', 'cd_src')
        self.cd_src = cd_src
        queue = Gst.ElementFactory.make('queue', 'queue')
        converter = Gst.ElementFactory.make('audioconvert', 'converter')
        encoder = Gst.ElementFactory.make('flacenc', 'encoder')
        self.filesink = Gst.ElementFactory.make('filesink', 'filesink')

        self.pipeline = Gst.ElementFactory.make('pipeline', 'ripper_pipeline')
        self.pipeline.add(cd_src)
        self.pipeline.add(queue)
        self.pipeline.add(converter)
        self.pipeline.add(encoder)
        self.pipeline.add(self.filesink)

        cd_src.link(queue)
        queue.link(converter)
        converter.link(encoder)
        encoder.link(self.filesink)

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message::toc', self.on_toc)
        self.bus.connect('message::eos', self.on_eos)
        self.bus.connect('message::error', self.on_error)

        input_stream = Gio.UnixInputStream.new(0, True)
        self.data_input_stream = Gio.DataInputStream.new(input_stream)
        self.queue_read()

        self.loop = GLib.MainLoop()
        self.loop.run()

    def on_signal(self, signal, frame):
        self.cancellable.cancel()
        try:
            self.loop.quit()
        except AttributeError:
            sys.exit(1)

    def on_toc(self, bus, msg):
        toc, updated = msg.parse_toc()
        self.n_tracks = n_tracks = len(toc.get_entries())
        # self.n_tracks = n_tracks = 1  # for testing

        # I get toc at the start of every track, so there is no easy way
        # to send n_tracks only at the start of a rip session. GStreamer
        # numbers tracks from 1.
        track_num = self.cd_src.get_property('track')
        self.send_reply('rip-track-started', self.uuid, n_tracks,
                track_num - 1)

        # Start the progress timer here to be sure that we get
        # rip-track-started before the first 'rip-track-position'.
        self.start_progress_timer()

    def on_eos(self, bus, msg):
        # Do not tell ripper that we are going to state NULL until we have
        # finished ripping every track.
        GLib.source_remove(self.timer_id)  # stop the progress timer
        self.timer_id = None
        track_num = self.cd_src.get_property('track')
        file_size, mtime = self.get_size_mtime(self.part_file_name)

        self.pipeline.set_state(Gst.State.NULL)

        self.part_file_name.rename(self.file_name)
        self.send_reply('rip-track-finished', self.uuid, self.disc_num,
                track_num - 1)

        next_track = track_num + 1
        if next_track <= self.n_tracks:
            file_name = Path(self.disc_dir, f'{next_track - 1:02d}.flac')
            self.file_name = file_name
            self.part_file_name = Path(str(file_name) + '.part')

            self.pipeline.set_state(Gst.State.NULL)
            self.filesink.set_property('location', self.part_file_name)
            self.cd_src.set_property('track', next_track)
            self.pipeline.set_state(Gst.State.PLAYING)
        else:
            self.send_reply('rip-finished')
            self.send_reply('state', 'NULL')

    def on_error(self, bus, msg):
        self.pipeline.set_state(Gst.State.NULL)
        self.send_reply('state', 'NULL')

        gerror, debug = msg.parse_error()
        *first_lines, message = debug.splitlines()
        self.send_reply('error', message)

    def start_progress_timer(self):
        self.timer_id = GLib.timeout_add(500, self.progress_timer_cb)

    def progress_timer_cb(self):
        success, position = self.pipeline.query_position(Gst.Format.TIME)
        success, duration = self.pipeline.query_duration(Gst.Format.TIME)
        fraction = position / duration
        track_num = self.cd_src.get_property('track')
        if success:
            file_size, mtime = self.get_size_mtime(self.part_file_name)
            self.send_reply('rip-track-position', self.uuid, self.disc_num,
                    track_num - 1, fraction)
        return True

    def queue_read(self):
        self.data_input_stream.read_line_async(PRIORITY, self.cancellable,
                self.on_command_in)

    def send_reply(self, *message):
        text = json.dumps(message)
        print(text, flush=True)

    def get_state(self):
        _, state, _ = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
        return STATES[int(state)]

    def get_size_mtime(self, snd_path):
        stat = snd_path.stat()
        mtime_fmt = '%Y %b %d %H:%M:%S'
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime(mtime_fmt)
        size = f'{stat.st_size / 1e6:.2f}'
        return size, mtime

    # -Command handlers--------------------------------------------------------
    def on_command_in(self, source, result):
        line, length = source.read_line_finish_utf8(result)
        if not line:
            return

        command, *args = json.loads(line)
        command_map[command](self, *args)

        self.queue_read()

    @command
    def on_rip(self, uuid, disc_num):
        self.uuid = uuid
        self.disc_num = disc_num
        self.disc_dir = disc_dir = Path(SOUND, uuid, str(disc_num))
        disc_dir.mkdir(exist_ok=True)

        # If the file already exists we are re-ripping it, so remove the
        # old version.
        self.file_name = file_name = Path(disc_dir, '00.flac')
        self.part_file_name = part_file_name = Path(str(file_name) + '.part')
        self.filesink.set_property('location', str(part_file_name))

        self.cd_src.set_property('track', 1)

        self.pipeline.set_state(Gst.State.PLAYING)
        self.send_reply('state', 'PLAYING')
        self.send_reply('rip-started', uuid, disc_num)

    @command
    def on_stop(self):
        # Ripper could detect activation of the Delete option at a time when
        # engine is not ripping.
        if self.get_state() == 'PLAYING':
            self.pipeline.set_state(Gst.State.NULL)
            # engine could have killed the timer on eos just before getting
            # the stop command.
            if self.timer_id is not None:
                GLib.source_remove(self.timer_id)  # stop the progress timer
            self.part_file_name.unlink(missing_ok=True)
            self.send_reply('state', 'NULL')
            self.send_reply('rip-aborted')


if __name__ == '__main__':
    ripper = Ripper()

