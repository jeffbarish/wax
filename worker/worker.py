"""Launch the function executor, pass it the function, and return the
results."""

import marshal
import pickle
import sys

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

ENGINE = 'worker/engine.py'


class Worker:
    def __init__(self):
        self.cancellable = Gio.Cancellable.new()

    def do_in_subprocess(self, function, reply_handler, *args):
        # Cancel any pending read on stdin. The corresponding worker will
        # get a broken_pipe error and exit. A new worker will be responsible
        # for the current work request.
        self.cancellable.cancel()

        # sys.executable is a string giving the absolute path of the
        # Python interpreter. If the main program is running in a virtual
        # environment, the subprocess will too.
        argv = [sys.executable, ENGINE]
        flags = (Gio.SubprocessFlags.STDOUT_PIPE
                | Gio.SubprocessFlags.STDIN_PIPE)
        subprocess = Gio.Subprocess.new(argv, flags)

        function_spec = (function.__code__, args)
        marshaled_function_spec = marshal.dumps(function_spec)
        out_bytes = GLib.Bytes.new(marshaled_function_spec)

        self.cancellable.reset()
        subprocess.communicate_async(
                stdin_buf=out_bytes,
                cancellable=self.cancellable,
                callback=self.on_communicate_cb,
                user_data=reply_handler)

    def on_communicate_cb(self, source, result, reply_handler):
        try:
            success, out_buf, err_buf = source.communicate_finish(result)
        except GLib.Error as e:
            if e.code == Gio.IOErrorEnum.CANCELLED:
                return

        out_bytes = out_buf.get_data()
        try:
            result = pickle.loads(out_bytes)
        except EOFError as e:
            result = False, str(e)

        # reply_handler takes two arguments: success and result. If success
        # is False, result is a string with the exception.
        reply_handler(*result)

