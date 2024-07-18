"""Launch the engine subprocess with path engine_path and communicate with
it."""

import json
import sys

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

PRIORITY = GLib.PRIORITY_DEFAULT

class EngineLauncher:
    def __init__(self, engine_path, reply_handler):
        self.reply_handler = reply_handler

        self.cancellable = Gio.Cancellable()
        try:
            flags = (Gio.SubprocessFlags.STDOUT_PIPE |
                    Gio.SubprocessFlags.STDIN_PIPE)
            args = [sys.executable, engine_path]
            self.subprocess = subprocess = Gio.Subprocess.new(args, flags)

            stream_in = subprocess.get_stdout_pipe()
            self.data_stream_in = Gio.DataInputStream.new(stream_in)
            self.queue_read()

            stream_out = subprocess.get_stdin_pipe()
            self.data_stream_out = Gio.DataOutputStream.new(stream_out)
        except GLib.GError as e:
            print(e, file=sys.stderr)

    def send_command(self, *args):
        arg_str = json.dumps(args)
        self.data_stream_out.put_string(arg_str, self.cancellable)
        self.data_stream_out.put_string('\n', self.cancellable)
        self.data_stream_out.flush(self.cancellable)

    def queue_read(self):
        self.data_stream_in.read_line_async(
            io_priority=PRIORITY,
            cancellable=self.cancellable,
            callback=self.on_message_received)

    def cancel_read(self):
        self.cancellable.cancel()

    def on_message_received(self, source, result):
        try:
            message, length = source.read_line_finish_utf8(result)
            command, *args = json.loads(message)
            self.reply_handler(command, args)
        except GLib.GError as e:
            print('error: ', e, file=sys.stderr)
            self.reply_handler('error', e)

        # Any messages sent while we are busy in this handler will be
        # buffered in stream_in.
        self.queue_read()

