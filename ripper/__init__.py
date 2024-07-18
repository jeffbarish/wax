from .ripper import Ripper

ripper = Ripper()

import signal
import atexit

@atexit.register
def on_exit():
    ripper.rip_engine_launcher.subprocess.send_signal(signal.SIGINT)

