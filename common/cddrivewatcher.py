"""Poll the disc drive and set a flag when a disc is present. Get the
disc id."""

import fcntl
import os

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib

CDROM_DRIVE = '/dev/cdrom'

CDROM_DRIVE_STATUS = 0x5326

class CDDriveWatcher(GObject.Object):
    disc_ready = GObject.Property(type=bool, default=False)

    def __init__(self):
        super().__init__()

        # 0x5326 = CDROM_DRIVE_STATUS (see linux/cdrom.h).
        # Status values:
        #   1 = no disc
        #   2 = tray open
        #   3 = drive getting ready
        #   4 = disc ready
        def poll_status():
            try:
                fd = os.open(CDROM_DRIVE, os.O_RDONLY | os.O_NONBLOCK)
            except FileNotFoundError:
                self.disc_ready = False
                return True

            try:
                status = fcntl.ioctl(fd, CDROM_DRIVE_STATUS)
            except OSError:
                self.disc_ready = False
                return True

            try:
                os.close(fd)
            except OSError:
                pass

            # Writing to self.disc_ready triggers notify even if the value
            # does not change, so write only if the value actually changes.
            # I could use QuietProperty here except that I need to be sure
            # that get_discid is called before disc_ready changes.
            disc_ready = (status == 4)
            if self.disc_ready != disc_ready:
                if disc_ready:
                    self.get_discid()
                self.disc_ready = disc_ready

            return True

        GLib.timeout_add_seconds(1, poll_status)

    def get_name(self):
        return 'cd-drive-watcher'

    def get_discid(self):
        import os
        import sys
        cwd = os.getcwd()
        packages = os.path.join(cwd, '.venv/lib/python3.8/site-packages/')
        sys.path.extend((cwd, packages))

        import discid
        disc = discid.read()
        self.disc_id = disc.id


cd_drive_watcher = CDDriveWatcher()

