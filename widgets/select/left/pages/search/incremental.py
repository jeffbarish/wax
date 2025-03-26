"""Incremental search."""

import os
import shelve
import string
import bisect
from itertools import product
from typing import Iterator

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, GObject

from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import LONG, IMAGES, IMAGES_DIR
from common.contextmanagers import signal_blocker
from common.decorators import emission_stopper
from common.decorators import idle_add
from common.types import GroupTuple, TrackID
from common.utilities import debug
from common.utilities import playable_tracks
from unidecode import unidecode
from widgets import control_panel

N_MATCHES_MAX = 299

type WorkID = tuple[str, int]  # (uuid, work_num)
type MatchValues = list[str]
type TrackMatchValues = dict[TrackID, MatchValues]

# str is 'work' or 'tracks'.
type MatchValuesDict = dict[str, MatchValues | TrackMatchValues]

def normalize(text:str) -> str:
    text = text.strip()
    text = text.strip(string.punctuation)
    text = text.lower()
    # return unicodedata.normalize('NFKD', text)
    # Slightly slower, but unidecode will find étude when the user types etude.
    return unidecode(text)

# Normalize text, split it, and discard short values and numbers.
def splitter(text: str) -> list:
    return [t.strip(string.punctuation) for t in normalize(text).split()
            if len(t) > 2 and not t.isdigit()]

@Gtk.Template.from_file('data/glade/select/search/incremental.glade')
class SearchIncremental(Gtk.Box):
    __gtype_name__ = 'incremental_box'

    @GObject.Signal
    def selection_changed(self, genre: str, uuid: str, work_num: int,
            tracks: object):
        pass

    incremental_flowbox = Gtk.Template.Child()
    incremental_entry = Gtk.Template.Child()
    incremental_overflow_image = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('search-incremental')
        self.tab_text = 'Incremental'

        self.match_values: MatchValuesDict = {}
        self.flowboxchild_map: dict[Gtk.FlowBoxChild, WorkID] = {}

        self.incremental_flowbox.connect('selected-children-changed',
                self.on_flowbox_selected_children_changed)

        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)
        register_connect_request('edit-left-notebook', 'work-deleted',
                self.on_work_deleted)
        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('search-sibling', 'selection-changed',
                self.on_search_sibling_selection_changed)
        register_connect_request('playqueue_select.playqueue_treeselection',
                'changed', self.on_playqueue_select_selection_changed)

        # Each FlowBoxChild is hidden (along with the enclosed image) until
        # it is needed.
        for _ in range(N_MATCHES_MAX):
            image = Gtk.Image.new()
            image.show()
            eventbox = Gtk.EventBox.new()
            eventbox.show()
            eventbox.add(image)
            self.incremental_flowbox.add(eventbox)
            flowboxchild = eventbox.props.parent
            flowboxchild.hide()

            flags = Gtk.TargetFlags.SAME_APP
            flowboxchild.drag_source_set(
                    Gdk.ModifierType.BUTTON1_MASK,
                    [Gtk.TargetEntry.new('recording', flags, 0)],
                    Gdk.DragAction.COPY)
            flowboxchild.connect('drag-begin', self.on_drag_begin)
            flowboxchild.connect('drag-data-get', self.on_drag_data_get)
            flowboxchild.connect('button-press-event',
                    self.on_button_press_event)

        filename = os.path.join(IMAGES_DIR, 'noimage_thumbnail.png')
        self.noimage_thumbnail_pb = GdkPixbuf.Pixbuf.new_from_file(filename)

        filename = os.path.join(IMAGES_DIR, 'overflow.png')
        self.incremental_overflow_image.set_from_file(filename)

    # If a recording is saved or deleted, redo the search.
    def on_recording_saved(self, editnotebook, genre):
        text = normalize(self.incremental_entry.props.text)
        if text:
            self.match_text = text
            self.match_values = self.start(text)

    def on_work_deleted(self, editnotebook, genre, uuid, work_num):
        text = normalize(self.incremental_entry.props.text)
        if text:
            self.match_text = text
            self.match_values = self.start(text)

    def on_flowbox_selected_children_changed(self, flowbox):
        children = flowbox.get_selected_children()
        if not children:
            return
        flowboxchild = children[0]

        uuid, work_num = self.flowboxchild_map[flowboxchild]
        recording = self.get_recording(uuid)  # read recording from  long
        work = recording.works[work_num]
        id_map = {t.track_id: t for t in recording.tracks}

        values = self.match_values[(uuid, work_num)]

        # First do a work match.
        search_text_values = splitter(self.incremental_entry.props.text)
        search_text_values = [v for v in search_text_values
                if not self.match(values['work'], [v])]

        # Keep tracks that also pass a track match.
        tracks = [id_map[t_id] for t_id, vals in values['tracks'].items()
                if self.match(vals, search_text_values)]

        self.emit('selection-changed', work.genre, uuid, work_num, tracks)

    def on_search_sibling_selection_changed(self, searchsibling,
            genre, uuid, work_num, tracks):
        self.select_matching_flowboxchild()

    def on_recording_selection_changed(self, recording_selection):
        self.select_matching_flowboxchild()

    @emission_stopper()
    def on_playqueue_select_selection_changed(self, selection):
        self.select_matching_flowboxchild()

    @idle_add
    def select_matching_flowboxchild(self):
        recording_selection = getattr_from_obj_with_name(
                'selector.recording_selection')
        model_filter, selected_row_iter = recording_selection.get_selected()
        if selected_row_iter is None:
            self.incremental_flowbox.unselect_all()
            return

        def finish():
            model = model_filter.props.child_model
            recording = model.recording

            # When responding to a change in selection (recording, playqueue,
            # or sibling), matching is agnostic to track selection. However,
            # when driving a selection, the flowboxchild delegates selection
            # to selector, which accounts for track selection.
            for child, (uuid, work_num) in self.flowboxchild_map.items():
                if (uuid, work_num) == (recording.uuid, model.work_num):
                    with signal_blocker(self.incremental_flowbox,
                            'selected-children-changed'):
                        self.incremental_flowbox.select_child(child)
                    break
            else:
                with signal_blocker(self.incremental_flowbox,
                        'selected-children-changed'):
                    self.hide_images()
                    self.incremental_entry.set_text('')
        GLib.idle_add(finish)

    def on_drag_begin(self, flowboxchild, context):
        # It is possible to drag a recording without first selecting it, so
        # set the selection here, if necessary.
        if not flowboxchild.is_selected():
            self.incremental_flowbox.select_child(flowboxchild)

            # Process all events associated with child selection to be sure
            # that the recordingselector model gets updated before playqueue
            # receives the drag.
            while Gtk.events_pending():
                Gtk.main_iteration()

        event = Gtk.get_current_event()
        success, x, y = event.get_coords()

        if success:
            image = self.get_image(flowboxchild)
            pb = image.get_pixbuf()
            Gtk.drag_set_icon_pixbuf(context, pb, int(x), int(y))

    def on_drag_data_get(self, flowboxchild, context, data, info, time):
        # Delegate to selector.on_recording_selector_drag_data_get.
        selector = getattr_from_obj_with_name('selector')
        treeview = selector.recording_selector.view
        selector.on_recording_selector_drag_data_get(treeview,
                context, data, info, time)

    def on_button_press_event(self, flowboxchild, event):
        if event.type == Gdk.EventType._2BUTTON_PRESS \
                and event.state == 0 \
                and event.button == 1:
            control_panel.set_mode('Play')

    @Gtk.Template.Callback()
    def on_incremental_entry_changed(self, incremental_entry):
        # The search starts here: The user just started entering text in the
        # incremental_entry. Initially there is no match_values, so we call
        # start. It returns nothing until search_text is sufficient to reduce
        # the number of matches to below N_MATCHES_MAX. At that point, we set
        # match_text and match_values. The start method called create images
        # to display covers of all the works that matched. Subsequent updates
        # to search_text merely winnow that set of covers by applying the
        # updated search_text to match_values (which never changes).
        search_text = normalize(incremental_entry.props.text)
        search_text_values = splitter(search_text)

        if not search_text:
            self.hide_images()
            self.show_incremental_overflow_image(False)
            self.match_text, self.match_values = '', {}
        elif self.match_values:
            # Once self.match_values is set, it changes only if search_text
            # no longer starts with match_text.
            if search_text.startswith(self.match_text):
                # If there is a match_values and search_text starts with
                # it, then search_text just got extended so just winnow
                # the set of matches on display.
                self.winnow(search_text_values)
                if self.incremental_flowbox.get_selected_children():
                    flowbox = self.incremental_flowbox
                    self.on_flowbox_selected_children_changed(flowbox)
            else:
                # If match_text does not start with search_text, restart
                # the search with search_text to find a new match_values
                # and then winnow.
                self.match_text, self.match_values = \
                        self.restart(search_text)
                if self.match_values:
                    self.winnow(search_text_values)
                self.incremental_flowbox.unselect_all()
        else:
            # match_text is the search_text that produced the set of matches
            # on display. match_values is a dict that maps the (uuid, work_num)
            # of each matching work to a dict with a list of values that
            # matched work metadata and a dict that maps disc_id to a list
            # of track values for tracks that matched. winnow uses that set
            # of values to refine the match as search_text gets extended.
            self.match_text = search_text
            self.match_values = self.start(search_text)
            self.incremental_flowbox.unselect_all()

    def start(self, text: str) -> MatchValuesDict:
        '''Find the "match" -- i.e., the first set of matches whose size
        does not exceed N_MATCHES_MAX. Extending search_text does not change
        the match, it winnows the set of visible matches. If search_text no
        longer starts with match_text, then restart to generate a new match.'''
        self.hide_images()

        match_values = {}
        for uuid, work_num, values in self.yield_matches(text):
            match_values[(uuid, work_num)] = values
            if len(match_values) > N_MATCHES_MAX:
                self.show_incremental_overflow_image(True)
                return {}

        self.show_incremental_overflow_image(False)
        self.create_images(match_values)

        return match_values

    def restart(self, text:str) -> tuple[str, MatchValuesDict]:
        # Simulate typing in the new text.
        for i in range(len(text)):
            new_text = text[:i + 1]
            match_values = self.start(new_text)
            if match_values:
                return new_text, match_values
        return '', {}

    # winnow hides flowbox children that do not match search_text_values.
    def winnow(self, search_text_values: list):
        for flowbox_child, (uuid, work_num) in self.flowboxchild_map.items():
            values_dict = self.match_values[(uuid, work_num)]
            visible = self.full_match(values_dict, search_text_values)
            flowbox_child.set_visible(visible)

    def full_match(self, values_dict: MatchValuesDict,
                search_text_values:list) -> bool:
        search_text_values = [v for v in search_text_values
                if not self.match(values_dict['work'], [v])]
        if not search_text_values:
            return True

        for disc_id, vals in values_dict['tracks'].items():
            if self.match(vals, search_text_values):
                return True
        return False

    def match(self, values: list, search_text_values: list) -> bool:
        def bin_search(values, text):
            i = bisect.bisect_left(values, text)
            if i == len(values):
                return False
            if values[i].startswith(text):
                return True
            return False

        # Every word in search_text_values must match the start of some word
        # in values.
        return all(bin_search(values, text) for text in search_text_values)

    def create_images(self, match_values: MatchValuesDict):
        self.flowboxchild_map = {}
        for (uuid, work_num), flowbox_child \
                in zip(match_values, self.incremental_flowbox.get_children()):
            image = self.get_image(flowbox_child)
            self.show_cover(uuid, image)

            # When the user clicks on an image, we need to select the
            # appropriate work in select mode and update the sibling
            # selection, if the work has siblings. To that end, we
            # need to know the (uuid, work_num) of the selected cover.
            # flowboxchild_map provides the necessary mapping from
            # flowbox_child to (uuid, work_num).
            values = match_values[(uuid, work_num)]
            self.flowboxchild_map[flowbox_child] = uuid, work_num

        # Now that all the tasks for creating an image have been queued,
        # add a task to show surviving recordings based on the search text
        # present at the time this task runs.
        def show_visible_images():
            self.winnow(splitter(self.incremental_entry.props.text))
        GLib.idle_add(show_visible_images)

    # Run show_cover from the idle loop to read an image file and set the
    # pixbuf of an image.
    @idle_add
    def show_cover(self, uuid, image):
        # Open the thumbnail version of the cover image.
        filename = os.path.join(IMAGES, uuid, 'thumbnail-00.jpg')
        if os.path.exists(filename):
            pb = GdkPixbuf.Pixbuf.new_from_file(filename)
        else:
            pb = self.noimage_thumbnail_pb
        image.set_from_pixbuf(pb)

    def show_incremental_overflow_image(self, visible):
        self.incremental_overflow_image.props.visible = visible

    def hide_images(self):
        for child in self.incremental_flowbox.get_children():
            child.hide()
            self.incremental_flowbox.unselect_child(child)
        self.flowboxchild_map = {}

    def yield_matches(self, search_text: str
            ) -> Iterator[tuple[str, int, MatchValuesDict]]:
        with shelve.open(LONG, 'r') as recording_shelf:
            for uuid, recording in recording_shelf.items():
                for work_num, work in recording.works.items():
                    # Assemble values from long work metadata. Any name in
                    # short metadata will also be in long metadata.
                    work_values = {name for namegroup in work.metadata
                            for name in namegroup}

                    # work.metadata has only primary and secondary. Add nonce
                    # names to work_values.
                    for key, namegroup in work.nonce:
                        work_values.update(namegroup)

                    work_values = self.prepare_values(work_values)

                    # Assemble values for individual tracks.
                    group_map = {t: GroupTuple(g_title, g_metadata)
                        for g_title, track_ids, g_metadata in work.trackgroups
                            for t in track_ids}

                    track_values = {}
                    for track in recording.tracks:
                        values = set()
                        track_ids = []
                        if track.track_id in work.track_ids:
                            values.add(track.title)
                            if track.metadata:
                                values.update(v for k, vals in track.metadata
                                        for v in vals)

                            # If track in track group, append values for
                            # track group.
                            group_tuple = group_map.get(track.track_id, None)
                            if group_tuple:
                                values.add(group_tuple.title)
                                for key, val in group_tuple.metadata:
                                    values.update(val)

                            values = self.prepare_values(values)
                            track_values[track.track_id] = values

                    # Perform work match test.
                    search_text_values = splitter(search_text)
                    search_text_values = [v for v in search_text_values
                            if not self.match(work_values, [v])]

                    if not search_text_values:
                        # All values in search_text_values matched work_values.
                        # Select all tracks.
                        values_dict = {'work': work_values,
                                'tracks': track_values}
                        yield uuid, work_num, values_dict
                    else:
                        track_matches = {}
                        for t_id, t_vals in track_values.items():
                            if self.match(t_vals, search_text_values):
                                track_matches[t_id] = t_vals
                        if track_matches:
                            values_dict = {'work': work_values,
                                    'tracks': track_matches}
                            yield uuid, work_num, values_dict

    def prepare_values(self, values):
        values_str = ' '.join(values)

        # Normalize names and discard short values and numbers; remove
        # redundancies; and sort values to permit binary search for matches.
        values = splitter(values_str)
        values = list(set(values))
        values.sort()

        return values

    def get_recording(self, uuid):
        with shelve.open(LONG, 'r') as recording_shelf:
            return recording_shelf[uuid]

    def get_image(self, flowboxchild):
        eventbox = flowboxchild.get_child()
        return eventbox.get_child()


page_widget = SearchIncremental()

