"""This module assembles the right panel of Select mode."""

from typing import NamedTuple

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository.GdkPixbuf import Pixbuf

class PlayqueueModelRow(NamedTuple):
    image: Pixbuf          # image of cover
    long_metadata: object  # [str] (list of strings with long names)
    tracks: object         # [TrackTuple] (tracks selected for play)
    group_map: object      # {(track_num, disc_num): GroupTuple}
    genre: str
    uuid: str
    work_num: int
    random: bool           # whether to play tracks in this set in random order
    props: object          # [(str, (str, ...)), ...] (key, values)
    playable: bool         # whether this recording is playable
    play_tracks: object    # [TrackTuple] (tracks remaining for play)

    @property
    def duration(self):
        return sum(track.duration for track in self.play_tracks)

_types = list(PlayqueueModelRow.__annotations__.values())
playqueue_model = Gtk.ListStore.new(_types)

from common.types import ModelWithAttrs
playqueue_model_with_attrs = ModelWithAttrs(playqueue_model, PlayqueueModelRow)

from .playqueue import Playqueue
select_right = Playqueue()

