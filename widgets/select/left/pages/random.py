import pickle
import random
import shelve
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from common.constants import SHORT, LONG
from common.utilities import debug, playable_tracks
from widgets import config
from widgets.select.right import select_right as playqueue_select


@Gtk.Template.from_file('data/glade/select/random.glade')
class Random(Gtk.ScrolledWindow):
    __gtype_name__ = 'random_scrolledwindow'

    random_liststore = Gtk.Template.Child()

    genre_name_treeviewcolumn = Gtk.Template.Child()
    genre_name_treeviewcolumn_label = Gtk.Template.Child()

    genre_weight_treeviewcolumn = Gtk.Template.Child()
    genre_weight_treeviewcolumn_label = Gtk.Template.Child()
    genre_weight_cellrendererspin = Gtk.Template.Child()

    alltracks_treeviewcolumn = Gtk.Template.Child()
    alltracks_treeviewcolumn_label = Gtk.Template.Child()

    random_duration_adjustment = Gtk.Template.Child()

    random_spin_button = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('playqueue_random')
        self.tab_text = 'Random'

        self.genre_name_treeviewcolumn.set_widget(
                self.genre_name_treeviewcolumn_label)
        self.genre_weight_treeviewcolumn.set_widget(
                self.genre_weight_treeviewcolumn_label)
        self.alltracks_treeviewcolumn.set_widget(
                self.alltracks_treeviewcolumn_label)
        self.genre_weight_cellrendererspin.set_alignment(0.5, 0.5)

        for genre, (weight, alltracks) in config.random_config.items():
            self.random_liststore.append((genre, weight, alltracks))

    @Gtk.Template.Callback()
    def on_genre_weight_cellrendererspin_edited(self, renderer, path, text):
        new_weight = int(text)
        self.random_liststore[path][1] = new_weight

        with config.modify('random config') as random_config:
            genre, *spec = self.random_liststore[path]
            random_config[genre] = spec

    @Gtk.Template.Callback()
    def on_alltracks_cellrenderertoggle_toggled(self, renderer, path):
        self.random_liststore[path][2] = not self.random_liststore[path][2]

        with config.modify('random config') as random_config:
            genre, *spec = self.random_liststore[path]
            random_config[genre] = spec

    @Gtk.Template.Callback()
    def on_random_liststore_row_changed(self, model, path, treeiter):
        # If any weight is nonzero, sensitize spin button.
        self.random_spin_button.props.sensitive = (
                any(row[1] for row in model)
                and self.random_duration_adjustment.props.value)

    @Gtk.Template.Callback()
    def on_random_duration_adjustment_value_changed(self, model):
        self.random_spin_button.props.sensitive = (
                any(row[1] for row in model)
                and self.random_duration_adjustment.props.value)

    @Gtk.Template.Callback()
    def on_random_spin_button_clicked(self, button):
        def queue_random_selection():
            nonlocal duration
            if duration <= 0:
                return False

            # Pick a genre randomly according to random config.
            genres, specs = zip(*config.random_config.items())
            weights, alltracks = zip(*specs)
            random_genre = random.choices(genres, weights)[0]

            # Pick a recording randomly from random_genre.
            count, tells = 0, [0]
            short_path = Path(SHORT, random_genre)
            with open(short_path, 'rb') as fo:
                # Count how many pickles there are in random_genre and keep
                # track of where each pickle starts.
                while True:
                    try:
                        pickle.load(fo)
                    except EOFError:
                        break
                    count += 1
                    tells.append(fo.tell())

                index = random.randrange(count)
                fo.seek(tells[index])
                short_metadata, uuid, work_num = pickle.load(fo)

            with shelve.open(LONG, 'r') as recording_shelf:
                recording = recording_shelf[uuid]
            track_ids = recording.works[work_num].track_ids

            weight, alltracks = config.random_config[random_genre]
            play_tracks = playable_tracks(recording.tracks, track_ids)
            if not alltracks:
                play_tracks = [random.choice(play_tracks)]
            recording = recording._replace(tracks=list(play_tracks))
            for track in play_tracks:
                duration -= track.duration
            playqueue_select.enqueue_recording(random_genre, recording,
                    work_num, play_tracks)
            playqueue_select.select_last_set()

            return True

        duration = self.random_duration_adjustment.props.value * 60.0 * 60.0
        queue_random_selection()
        GLib.timeout_add(500, queue_random_selection)


page_widget = Random()

