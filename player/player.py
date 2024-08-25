'''Player is the interface to the rest of the program for play
functionality.'''

# Consider proxy object
# (https://docs.python.org/3/library/multiprocessing.html#proxy-objects)

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GObject', '2.0')
from gi.repository import Gtk, GObject, GLib

from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.enginelauncher import EngineLauncher
from common.utilities import debug
from widgets import options_button, control_panel
from widgets.controlpanel.controlpanel import State
from widgets.select.right import playqueue_model_with_attrs as playqueue_model

# Decorator to register methods that respond to replies from engine.
reply_map = {}
# This version of the decorator provides tracing information.
# def reply(f):
#     reply = f.__name__[3:].replace('_', '-')
#     def new_f(self, *args):
#         if reply != 'track-position':
#             print('received reply', reply, args)
#         return f(self, *args)
#     reply_map[reply] = new_f
#     return new_f
def reply(f):
    reply = f.__name__[3:].replace('_', '-')
    reply_map[reply] = f
    return f

glong = GObject.TYPE_LONG


class Player(GObject.Object):
    @GObject.Signal
    def set_ready(self, duration: glong):
        pass

    @GObject.Signal
    def set_started(self, uuid: str, work_num: int):
        pass

    @GObject.Signal
    def set_finished(self):
        pass

    @GObject.Signal
    def position(self,
            track_position: glong, track_duration: glong,
            set_position: glong, set_duration: glong):
        pass

    @GObject.Signal
    def track_started(self, tracktuple: object, grouptuple: object,
            track_duration: glong, more_tracks: bool, uuid: str):
        pass

    @GObject.Signal
    def track_finished(self, n_tracks: int, track_id: object, uuid: str):
        pass

    def __init__(self):
        super().__init__()
        self.play_engine_launcher = EngineLauncher('player/engine.py',
                self.reply_handler)
        self.do = self.play_engine_launcher.send_command
        self.state = 'NULL'
        self.set_ready = False

        playqueue_model.connect('row-inserted',
                self.on_playqueue_model_row_inserted)
        playqueue_model.connect('row-deleted',
                self.on_playqueue_model_row_deleted)
        playqueue_model.connect('row-changed',
                self.on_playqueue_model_row_changed)
        register_connect_request('control-panel.view.play_button',
                'clicked', self.on_play_button_clicked)
        register_connect_request('control-panel.view.volume_button',
                'value-changed', self.on_volume_button_value_changed)
        register_connect_request('track-next-button',
                'clicked', self.on_track_next_button_clicked)
        register_connect_request(
                'play-metadata-page.track_progressbar_eventbox',
                'button-press-event',
                self.on_track_progressbar_button_press_event)

        options_button.connect_menuitem('Play', 'Restart',
                self.on_options_play_restart)

    # Connector calls get_name to get the name of the object. As Player is
    # not a widget, there is no set/get_name.
    def get_name(self):
        return 'player'

    def on_playqueue_model_row_inserted(self, liststore, path, treeiter):
        # If this is the first set in the play queue, get ready to play it.
        # Otherwise, wait until we finish with the first set.
        if path == Gtk.TreePath.new_first():
            self.on_options_play_restart(None)

    def on_playqueue_model_row_deleted(self, liststore, path):
        if path == Gtk.TreePath.new_first():
            self.do('stop')
            self.do('clear-queue')

            if len(liststore) >= 1:
                # The first set got deleted and len(liststore) >= 1, so
                # we have a new set in the play position.
                self.queue_tracks_of_first_set()

                # Engine sets state to NULL on eos, so we need to reactivate
                # play if the play button asserts that we are playing. Note
                # that we might be here because we deleted the first set in
                # the playqueue when play was not active.
                play_button = getattr_from_obj_with_name('play-button')
                if play_button.state == State.STOP:
                    self.do('play')

    def on_playqueue_model_row_changed(self, liststore, path, treeiter):
        # Send the random value to engine in case the random value was the
        # change in the metadata for the first set in the play queue.
        treeiter_first = liststore.get_iter_first()
        path_first = liststore.get_path(treeiter_first)
        if path_first.compare(path) == 0:
            self.do('random', playqueue_model[0].random)

    def on_play_button_clicked(self, button):
        if button.state == State.STOP:
            self.do('play')
        else:
            self.do('pause')

    def on_volume_button_value_changed(self, volumebutton, value):
        self.do('volume', value)

    def on_track_next_button_clicked(self, button):
        self.do('next-track')

    def on_track_progressbar_button_press_event(self, eventbox, event):
        track_progressbar, = eventbox.get_children()
        allocation = track_progressbar.get_allocation()
        width = allocation.width
        if event.x < 10.0:
            event.x = 0.0  # close to beginning -> beginning
        ratio = event.x / width
        self.do('set-ratio', ratio)

    # Restart play at the beginning of the set.
    def on_options_play_restart(self, menuitem):
        self.do('stop')
        self.do('clear-queue')

        self.queue_tracks_of_first_set()

        if self.state == 'PLAYING':
            self.do('play')

    # When the engine starts playing a track, it sends us the trackid of the
    # track.
    def queue_tracks_of_first_set(self):
        self.do('clear-queue')

        self.do('random', playqueue_model[0].random)

        # The engine provides the trackid in on_track_started, but we
        # need the corresponding tracktuple for the track-started signal.
        # trackid_map provides the necessary mapping.
        self.trackid_map = {tracktuple.track_id: tracktuple
                for tracktuple in playqueue_model[0].tracks}

        for tracktuple in playqueue_model[0].play_tracks:
            self.uuid = uuid = playqueue_model[0].uuid
            self.work_num = playqueue_model[0].work_num
            track_id = tracktuple.track_id
            duration = round(tracktuple.duration*1e9)
            self.do('append-queue', uuid, track_id, duration)

        self.do('ready-play')

    # -Reply handlers----------------------------------------------------------
    def reply_handler(self, command, args):
        reply_map[command](self, *args)

    @reply
    def on_position(self, track_position, track_duration,
            set_position, set_duration):
        self.emit('position', track_position, track_duration,
                set_position, set_duration)

    @reply
    def on_state(self, state):
        self.state = state

        # If we get state == 'PLAYING' while set_ready is True, then we just
        # started playing a set.
        if self.state == 'PLAYING' and self.set_ready:
            GLib.idle_add(self.emit, 'set-started', self.uuid, self.work_num)
            self.set_ready = False

    @reply
    def on_track_started(self, track_duration, more_tracks, *trackid):
        # Engine is playing the alert sound.
        if trackid == (-1, -1):
            return

        grouptuple = playqueue_model[0].group_map.get(trackid, None)
        tracktuple = self.trackid_map[trackid]
        self.emit('track-started', tracktuple, grouptuple,
                track_duration, more_tracks, self.uuid)

    @reply
    def on_track_finished(self, n_tracks, *trackid):
        self.emit('track-finished', n_tracks, trackid, self.uuid)

        for menuitem in options_button.option_menus['Play']:
            if menuitem.get_label() == 'Stop on track done':
                if menuitem.get_active():
                    self.do('pause')

                    play_button = control_panel.view.play_button
                    control_panel.on_play_button_clicked(play_button)

                    menuitem.set_active(False)
                break

    @reply
    def on_set_ready(self, set_duration):
        self.emit('set-ready', set_duration)

        # set_ready means the engine is ready to play. It happens once per
        # set. The tracks in the set were queued and the first track was
        # popped. The engine is waiting for a play command.
        self.set_ready = True

    @reply
    def on_set_finished(self):
        self.emit('set-finished')

