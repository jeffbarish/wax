from .cddrivewatcher import CDDriveWatcher
from .ripper import Ripper

ripper = Ripper()
cd_drive_watcher = CDDriveWatcher()

import signal
import atexit

@atexit.register
def on_exit():
    ripper.rip_engine_launcher.subprocess.send_signal(signal.SIGINT)

