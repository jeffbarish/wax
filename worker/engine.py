"""Wait for function to arrive, then execute it and return the result."""

import marshal
import os
import pickle
import sys
import types

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

os.sched_setaffinity(os.getpid(), (1,))

if __name__ == '__main__':
    input_stream = Gio.UnixInputStream.new(0, True)
    output_stream = Gio.UnixOutputStream.new(1, True)

    marshaled_function_spec = b''
    in_buf = input_stream.read_bytes(8192, None)
    while data := in_buf.get_data():
        marshaled_function_spec += data
        in_buf = input_stream.read_bytes(8192, None)

    def func1():
        global bytecode, args
        bytecode, args = marshal.loads(marshaled_function_spec)

    def func2():
        global function
        function = types.FunctionType(bytecode, {'__builtins__': __builtins__})

    def func3():
        global result
        result = True, function(*args)

    for func in [func1, func2, func3]:
        try:
            func()
        except Exception as e:
            result = False, str(e)
            break

    result_pickle = pickle.dumps(result)
    out_bytes = GLib.Bytes.new(result_pickle)

    try:
        output_stream.write_bytes(out_bytes, None)
    except GLib.Error:
        # Give up if it is not possible to communicate with launcher.
        sys.exit(1)

