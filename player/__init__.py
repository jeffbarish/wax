from .player import Player

player = Player()

import signal
import atexit

@atexit.register
def on_exit():
    player.play_engine_launcher.subprocess.send_signal(signal.SIGINT)

