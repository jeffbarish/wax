"""Incremental search."""

import os
import shelve
import string
import bisect
from itertools import groupby
from itertools import product
from time import time

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
from common.types import GroupTuple
from common.utilities import debug
from common.utilities import playable_tracks
from unidecode import unidecode
from widgets import control_panel

N_MATCHES_MAX = 299

def normalize(text):
    text = text.strip()
    text = text.strip(string.punctuation)
    text = text.lower()
    # return unicodedata.normalize('NFKD', text)
    # Slightly slower, but unidecode will find étude when the user types etude.
    return unidecode(text)

# Normalize text, split it, and discard short values and numbers.
def splitter(text):
    return [t.strip(string.punctuation) for t in normalize(text).split()
            if len(t) > 3 and not t.isdigit()]

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
        self.first_match = {}
        self.flowboxchild_map = {}

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
            self.first_match_text, self.first_match = self.start(text)

    def on_work_deleted(self, editnotebook, genre, uuid, work_num):
        text = normalize(self.incremental_entry.props.text)
        if text:
            self.first_match_text, self.first_match = self.start(text)

    def on_flowbox_selected_children_changed(self, flowbox):
        children = flowbox.get_selected_children()
        if not children:
            return
        flowboxchild = children[0]

        # Find the recording that corresponds with flowboxchild.
        recording, uuid, work_num = self.get_recording(flowboxchild)

        match_text_l = splitter(self.incremental_entry.props.text)

        def yield_metadata_names(metadata):
            keys, m_vals = zip(*metadata)

            # m_vals is a tuple of all metadata values (irrespective of key).
            for m_val in m_vals:
                for val in m_val:
                    yield val

        # Tracks match if any word in text matches any word in match_text. The
        # other words in match_text must have matched some other track or work
        # metadata, else the recording would not appear in the search results.
        def match(text):
            text_l = splitter(text)
            return any(t.startswith(m)
                    for t, m in product(text_l, match_text_l))

        values_str = ' '.join(s for work in recording.works.values()
                for val in work.metadata for s in val)
        values_l = splitter(values_str)

        # For a match to work metadata, every word in match_text must
        # match some word in values_str.
        work = recording.works[work_num]
        if all(any(v.startswith(m) for v in values_l) for m in match_text_l):
            # tracks is a list of tracktuples of playable tracks.
            tracks = playable_tracks(recording.tracks, work.track_ids)
        else:
            group_map = {t: GroupTuple(g_name, g_metadata)
                    for g_name, g_track_ids, g_metadata in work.trackgroups
                    for t in g_track_ids}
            # Create a list of tracks that match the track title or a value
            # in the metadata for the track. If the track is in a track
            # group, also check for a match with the title of the group
            # or a value in the metadata for the group.
            tracks = []
            for track in recording.tracks:
                if match(track.title):
                    tracks.append(track)
                elif track.metadata:
                    if any(map(match, yield_metadata_names(track.metadata))):
                        tracks.append(track)
                elif group := group_map.get(track.track_id, None):
                    if match(group.title):
                        tracks.append(track)
                    elif group.metadata:
                        if any(map(match,
                                yield_metadata_names(group.metadata))):
                            tracks.append(track)

        genre = recording.works[work_num].genre
        self.emit('selection-changed', genre, uuid, work_num, tracks)

        # Retain matching tracks for on_drag_begin (which sends matching_tracks
        # to selector by way of selection-changed, which then sends them on to
        # trackselector in set_selection).
        self.matching_tracks = tracks

    def on_search_sibling_selection_changed(self, searchsibling,
            genre, uuid, work_num, tracks):
        self.select_matching_flowboxchild()

    @idle_add
    def on_recording_selection_changed(self, recording_selection):
        self.select_matching_flowboxchild()

    @emission_stopper()
    def on_playqueue_select_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return
        self.select_matching_flowboxchild()

    @idle_add
    def select_matching_flowboxchild(self):
        recording_selection = getattr_from_obj_with_name(
                'selector.recording_selection')
        model_filter, selected_row_iter = recording_selection.get_selected()
        if selected_row_iter is None:
            return

        def finish():
            model = model_filter.props.child_model
            recording = model.recording

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
        recording, uuid, work_num = self.get_recording(flowboxchild)

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
        new_text = normalize(incremental_entry.props.text)

        if not new_text:
            self.hide_images()
            self.show_incremental_overflow_image(False)
            self.first_match_text, self.first_match = '', {}
        elif self.first_match:
            # Once self.first_match is set, it changes only if new_text no
            # longer starts with first_match_text.
            if new_text.startswith(self.first_match_text):
                # If there is a first_match and new_text starts with it,
                # then just winnow. winnow adjusts the visibility of the
                # set of images corresponding to first_match_text.
                self.winnow(new_text)
            else:
                # If first_match_text does not start with new_text, restart
                # the search with new_text to find a new first_match and then
                # winnow.
                self.first_match_text, self.first_match = \
                        self.restart(new_text)
                if self.first_match:
                    self.winnow(new_text)
        else:
            self.first_match_text, self.first_match = self.start(new_text)

    def start(self, text):
        self.hide_images()

        # Create a dict of recordings that match the search string.
        first_match = {}
        for uuid, work_num, values in self.yield_matches(text):
            first_match[(uuid, work_num)] = values
            if len(first_match) > N_MATCHES_MAX:
                self.show_incremental_overflow_image(True)
                return '', {}

        self.show_incremental_overflow_image(False)
        self.create_images(first_match)

        return text, first_match

    def restart(self, text):
        # Simulate typing in the new text.
        for i in range(len(text)):
            new_text = text[:i + 1]
            first_match_text, first_match = self.start(new_text)
            if first_match:
                return first_match_text, first_match
        return '', {}

    # winnow hides flowbox children that do not match text.
    def winnow(self, text):
        for flowbox_child, (uuid, work_num) in self.flowboxchild_map.items():
            vals = self.first_match[(uuid, work_num)]
            flowbox_child.props.visible = self.match(vals, text)

    def match(self, values, search_text):
        def bin_search(values, text):
            i = bisect.bisect_left(values, text)
            if i == len(values):
                return False
            if values[i].startswith(text):
                return True
            return False
        # Every word in search_text must match the start of some word
        # in values.
        search_text_l = splitter(search_text)
        return all(bin_search(values, text) for text in search_text_l)

    def create_images(self, matches):
        self.flowboxchild_map = {}
        incremental_flowbox = self.incremental_flowbox
        for (uuid, work_num), flowbox_child \
                in zip(matches, incremental_flowbox.get_children()):
            image = self.get_image(flowbox_child)
            self.show_cover(uuid, image)

            self.flowboxchild_map[flowbox_child] = uuid, work_num

        # Now that all the tasks for creating an image have been queued, add
        # a task to show surviving recordings based on the search text present
        # at the time this task runs.
        def show_visible_images():
            self.winnow(normalize(self.incremental_entry.props.text))
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

    def yield_matches(self, search_text):
        with shelve.open(LONG, 'r') as recording_shelf:
            for uuid, recording in recording_shelf.items():
                for work_num, work in recording.works.items():
                    # Start with values in long work metadata. Any name in
                    # short metadata will also be in long metadata. val is
                    # a tuple which can have multiple names (name group).
                    values = [s for val in work.metadata for s in val]

                    # Add values from track titles.
                    for track in recording.tracks:
                        if track.track_id in work.track_ids:
                            values.append(track.title)
                            if track.metadata:
                                keys, m_vals = zip(*track.metadata)
                                values.extend(v for m_val in m_vals
                                        for v in m_val)

                    # Add values from trackgroup titles and trackgroup
                    # metadata.
                    for g_name, g_track_ids, g_metadata in work.trackgroups:
                        if not set(g_track_ids).isdisjoint(work.track_ids):
                            values.append(g_name)
                            values.extend(v for key, vals in g_metadata
                                    for v in vals)

                    values_str = ' '.join(values)

                    # Normalize names and discard short values and numbers.
                    values = splitter(values_str)

                    values.sort()

                    # Remove redundancies.
                    values = [k for k, g in groupby(values)]

                    # Every word in search_text must match the start of
                    # some word in values.
                    if self.match(values, search_text):
                        yield uuid, work_num, values

    def get_recording(self, flowboxchild):
        uuid, work_num = self.flowboxchild_map[flowboxchild]

        with shelve.open(LONG, 'r') as recording_shelf:
            return recording_shelf[uuid], uuid, work_num

    def get_image(self, flowboxchild):
        eventbox = flowboxchild.get_child()
        return eventbox.get_child()


page_widget = SearchIncremental()

