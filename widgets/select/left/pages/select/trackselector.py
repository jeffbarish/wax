"""This module contains the model, view, and controller for the track
selector."""

from functools import singledispatchmethod
from operator import itemgetter

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib, Pango, Gdk

from common.connector import add_emission_stopper
from common.connector import stop_emission, stop_emission_with_name
from common.connector import register_connect_request
from common.types import TrackTuple, GroupTuple
from common.utilities import debug
from common.utilities import ModelWithAttrs
from common.utilities import playable_tracks
from widgets import options_button
from widgets.select.right import playqueue_model_with_attrs

class TrackSelector(GObject.Object):
    def __init__(self):
        super().__init__()
        self.model = track_model = TrackModel()
        self.view = TrackView(track_model)

        options_button.connect_menuitem('Play', 'Restart',
                self.on_options_play_restart)
        register_connect_request('playqueue_select.restart_menuitem',
                'activate', self.on_options_play_restart)

    def populate(self, tracks, work_track_ids, trackgroups):
        with stop_emission(self.view.selection, 'changed'):
            self.model.populate_track_model(
                    tracks, work_track_ids, trackgroups)

        self.view.select_all()

    def on_options_play_restart(self, menuitem):
        first_set = playqueue_model_with_attrs[0]
        self.view.set_selected_tracks(first_set.tracks)

class TrackModel(Gtk.TreeStore):
    def __init__(self):
        # Columns: disc_num, track_num, title, duration, metadata
        _types = TrackTuple.__annotations__.values()
        super().__init__(*_types)

    def clear(self):
        with stop_emission_with_name('track-view.selection', 'changed'):
            super().clear()

    def populate_track_model(self, tracks, work_track_ids, trackgroups):
        self.clear()

        # group_map is a mapping from a track_id (disc_num, track_num)
        # to a group tuple.
        self.group_map = group_map = {t: GroupTuple(g_name, g_metadata)
                for g_name, g_tracks, g_metadata in trackgroups
                    for t in g_tracks}

        current_group = None
        duration_index = TrackTuple._fields.index('duration')
        tracks_playable = playable_tracks(tracks, work_track_ids)
        for track_tuple in tracks_playable:
            group_tuple = group_map.get(track_tuple.track_id, None)

            if current_group is not None and group_tuple != current_group:
                # Went from one group to another.
                self.set_value(groupiter, duration_index, group_duration)
                current_group = None

            if group_tuple is None:
                # Not in a group.
                current_group = None
                self.append(None, track_tuple)
            elif group_map[track_tuple.track_id] == current_group:
                # Continue a group.
                self.append(groupiter, track_tuple)
                group_duration += track_tuple.duration
            else:
                # Start a new group.
                current_group = group_map[track_tuple.track_id]
                group_row = TrackTuple._convert(current_group)
                groupiter = self.append(None, group_row)
                self.append(groupiter, track_tuple)
                group_duration = track_tuple.duration
                current_group = group_tuple
        else:
            # If we finish in a group, update the group duration.
            if current_group is not None:
                self.set_value(groupiter, duration_index, group_duration)

        # track_map maps every track in model from its track_id.
        self.track_map = track_map = {}
        for track in ModelWithAttrs(self, TrackTuple):
            if track.is_group():
                for child in track.iterchildren():
                    track_map[child.track_id] = child
            else:
                track_map[track.track_id] = track

class TrackView(Gtk.TreeView):
    def __init__(self, track_model):
        super().__init__()
        self.set_name('track-view')
        self.set_model(track_model)
        self.set_headers_visible(False)
        self.set_rubber_banding(True)

        self.create_trk_treeview()

        self.connect('row-expanded', self.on_trk_row_expanded)
        self.connect('row-collapsed', self.on_trk_row_collapsed)
        self.connect('test-collapse-row',
                self.on_trk_treeview_test_collapse_row)

        self.selection = selection = self.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        selection.connect('changed', self.on_selection_changed)

    @singledispatchmethod
    def get_index(self, arg: Gtk.TreeModelRow):
        return arg.path[-1]

    @get_index.register
    def _(self, arg: Gtk.TreePath):
        return arg[-1]

    @get_index.register
    def _(self, arg: Gtk.TreeIter):
        model = self.get_model()
        path = model.get_path(arg)
        return path[-1]

    def create_trk_treeview(self):
        title_index = TrackTuple._fields.index('title')
        duration_index = TrackTuple._fields.index('duration')

        cell = Gtk.CellRendererText.new()
        cell.set_property('ellipsize', Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn.new()
        col.set_expand(True)
        col.pack_start(cell, True)
        def func1(column, cell, model, treeiter, val):
            title = model.get_value(treeiter, title_index)
            n_children = model.iter_n_children(treeiter)
            if n_children:
                title = "%s (%d)" % (title, n_children)
            cell.set_property('text', title)
        col.set_cell_data_func(cell, func1)
        self.append_column(col)

        cell = Gtk.CellRendererText.new()
        cell.set_property('xalign', 1.0)
        col = Gtk.TreeViewColumn()
        col.pack_start(cell, True)
        def func2(column, cell, model, treeiter, val):
            duration = model.get_value(treeiter, duration_index)
            minutes, seconds = duration // 60, duration % 60
            cell.set_property('text', f'{minutes:.0f}:{seconds:02.0f}')
        col.set_cell_data_func(cell, func2)
        self.append_column(col)

    def select_all(self):
        model = self.get_model()

        self.child_selections = {}
        for row in model:
            if model.iter_has_child(row.iter):
                n_children = model.iter_n_children(row.iter)
                self.child_selections[row.path[-1]] = [True] * n_children
        self.simple_selections = [True
                for row in model if not model.iter_has_child(row.iter)]

        self.selection.select_all()

    # After expanding a parent, select its child tracks according to
    # self.child_selections.
    def on_trk_row_expanded(self, treeview, treeiter, treepath):
        model = self.get_model()
        for child in model[treeiter].iterchildren():
            parent_index = self.get_index(treepath)
            child_index = self.get_index(child)
            is_selected = self.child_selections[parent_index][child_index]
            self.set_child_selection(child.iter, is_selected)
            if is_selected:
                with stop_emission(self.selection, 'changed'):
                    self.selection.select_path(treepath)

    # Keep track of row selections so that we can restore the selections
    # at appropriate points (e.g., when we expand the row again).
    def on_trk_treeview_test_collapse_row(self, treeview, treeiter, treepath):
        model, self.pre_collapse_selection = self.selection.get_selected_rows()
        parent_index = self.get_index(treepath)
        self.child_selections[parent_index] = [
                self.selection.path_is_selected(child.path)
                        for child in model[treepath].iterchildren()]

        # Simple rows are neither parent nor child.
        self.simple_selections = [self.selection.path_is_selected(row.path)
                for row in model if not model.iter_has_child(row.iter)]

    def on_trk_row_collapsed(self, treeview, treeiter, treepath):
        # After the row is collapsed, unselect the parent if all children
        # are not selected.
        parent_index = self.get_index(treepath)
        if not any(self.child_selections[parent_index]):
            with stop_emission(self.selection, 'changed'):
                self.selection.unselect_iter(treeiter)

        # Also affirm the selection of all children (although only those in
        # uncollapsed groups are visible).
        model = self.get_model()
        for parent_index, child_selections in self.child_selections.items():
            if any(child_selections):
                parent = model[parent_index]
                with stop_emission(self.selection, 'changed'):
                    self.selection.select_iter(parent.iter)
                    for i, child in enumerate(parent.iterchildren()):
                        if child_selections[i]:
                            self.selection.select_iter(child.iter)
                        else:
                            self.selection.unselect_iter(child.iter)

    @add_emission_stopper('changed')
    def on_selection_changed(self, selection):
        # We need to know whether the selection occurred because of a click
        # on a parent or on a child, or whether there was no click at all.
        # Note that selection has MULTIPLE set, so get_selected does not
        # work for getting the row that was just clicked.
        event = Gtk.get_current_event()
        if not event:
            return

        valid, x, y = event.get_coords()
        if not valid:
            return

        valid, button = event.get_button()
        if not (valid and button == 1):
            return

        valid, state = event.get_state()
        if not valid:
            return

        event_type = event.get_event_type()

        # The event can be clicking in recordingselector, in which case
        # valid will be True and button will be 1. However, path_t will
        # be None because the click was not in trackselector
        path_t = self.get_path_at_pos(int(x), int(y))
        if path_t is None:
            return
        path, col, x_cell, y_cell = path_t

        # If the row is not selected, it stays unselected on opening and
        # closing the row and we do not come here. If the row is selected,
        # we do not come here on opening the row (by clicking on the arrow),
        # but we do come here on closing the row (which is a GTK bug).
        if x_cell < 18:  # arrow clicked
            with stop_emission(self.selection, 'changed'):
                model = self.get_model()
                simple_rows = [row for row in model
                        if not model.iter_has_child(row.iter)]
                for row, selected in zip(simple_rows, self.simple_selections):
                    if selected:
                        selection.select_iter(row.iter)
            return

        # The selection has already been made at this point. Normally,
        # clicked_row_is_selected is True. For ctrl-leftclick on a selected
        # row, clicked_row_is_selected is False. When the user sweeps a
        # selection, there are two events, one for the starting row and a
        # second for the ending row. clicked_row_is_selected is True in
        # both cases.
        model = self.get_model()
        clicked_row = model[path]

        def make_selections(row):
            row_is_selected = selection.iter_is_selected(row.iter)
            if model.iter_has_child(row.iter):  # has child
                parent_index = self.get_index(row)
                child_selections = self.child_selections[parent_index]
                for child in row.iterchildren():
                    child_index = self.get_index(child)
                    child_selections = self.child_selections[parent_index]
                    if row_is_selected:
                        selection.select_path(child.path)
                        child_selections[child_index] = True
                    else:
                        selection.unselect_path(child.path)
                        child_selections[child_index] = False
            elif parent_iter := model.iter_parent(row.iter):  # has parent
                parent_index = self.get_index(parent_iter)
                child_index = self.get_index(row)
                self.child_selections[parent_index][child_index] = \
                        row_is_selected

                # Also select parent if first child just selected.
                if not selection.iter_is_selected(parent_iter):
                    selection.select_iter(parent_iter)

        # Clear all selections if no ctrl and then update them with the
        # new selections.
        if event_type == Gdk.EventType.BUTTON_PRESS \
                and state != Gdk.ModifierType.CONTROL_MASK:
            self.simple_selections = []
            for row in model:
                n_children = model.iter_n_children(row.iter)
                if n_children:
                    self.child_selections[self.get_index(row)] = \
                            [False] * n_children
                else:
                    self.simple_selections.append(False)

        if event_type == Gdk.EventType.BUTTON_PRESS:
            self.button_press_row = clicked_row
            with stop_emission(selection, 'changed'):
                make_selections(clicked_row)
        else:  # event_type == Gdk.EventType.BUTTON_RELEASE
            bump_up = (clicked_row.path > self.button_press_row.path)
            bump_method = ('previous', 'next')[bump_up]

            # If we ctrl-sweep from a simple into a group, then the
            # clicked_row will be a tuple with two elements. Terminate
            # when the first elements match. Otherwise, row will cycle
            # through top-level rows without ever matching the child.
            row = self.button_press_row
            while row.path[:1] != clicked_row.path[:1]:
                # button_press_row got updated in response to the
                # BUTTON_PRESS event (which preceded this one), so
                # advance to the "next" row immediately.
                if row.path is None:
                    return
                row_index = row.path[0]
                row = getattr(row, bump_method)
                if row is None:
                    # If bumping the row yielded None, then we must have
                    # been dealing with child rows. Any remaining rows in
                    # the selection must be at the top level. (Any other
                    # parent rows in the selection would have been closed
                    # on selection of a child of a different parent.)
                    row_index += (-1, 1)[bump_up]
                    row = model[row_index]
                with stop_emission(selection, 'changed'):
                    make_selections(row)

        self.simple_selections = [self.selection.path_is_selected(row.path)
                for row in model if not model.iter_has_child(row.iter)]

        # Collapse any parent whose children are all unselected.
        for row_index, child_selections in self.child_selections.items():
            if not any(child_selections):
                self.collapse_row(model[row_index].path)

    def set_child_selection(self, child_iter, select):
        # Set child_selections as well as actual selections.
        model = self.get_model()
        parent_iter = model.iter_parent(child_iter)

        parent_index = self.get_index(parent_iter)
        child_index = self.get_index(child_iter)
        self.child_selections[parent_index][child_index] = select

        if select:
            self.selection.select_iter(child_iter)
        else:
            self.selection.unselect_iter(child_iter)

    # Child rows are not selected when a parent row is collapsed. This method
    # takes account of self.child_selections.
    def yield_child_selections(self, parent_row):
        parent_expanded = self.row_expanded(parent_row.path)
        parent_index = self.get_index(parent_row)
        for child in parent_row.iterchildren():
            if parent_expanded:
                if self.selection.iter_is_selected(child.iter):
                    yield TrackTuple._make(child)
            else:
                child_index = self.get_index(child)
                if self.child_selections[parent_index][child_index]:
                    yield TrackTuple._make(child)

    def get_selected_tracks(self):
        selection = self.selection
        model = self.get_model()

        # Don't put selected rows with children in selected_rows.
        selected_rows = []
        for row in model:  # top level only
            if selection.iter_is_selected(row.iter):
                if not model.iter_has_child(row.iter):
                    selected_rows.append(TrackTuple._make(row))
                else:
                    selected_rows.extend(self.yield_child_selections(row))
        return selected_rows

    def set_selected_tracks(self, track_tuples):
        for key, values in self.child_selections.items():
            self.child_selections[key] = [False for v in values]
        model = self.get_model()

        # Using the track_id of each track in track_tuples (the list of
        # track_tuples in the playqueue selection), look up in track_map
        # the corresponding track in the model and then select that track.
        track_map = model.track_map

        with stop_emission(self.selection, 'changed'):
            self.selection.unselect_all()
            for track_tuple in track_tuples:
                # If a row got deleted then there might not be an entry in
                # track_map for a track in the playqueue item.
                if model_track := track_map.get(track_tuple.track_id, None):
                    self.selection.select_path(model_track.path)
                    if parent := model_track.get_parent():
                        parent_index = self.get_index(parent)
                        child_index = self.get_index(model_track.row)
                        self.child_selections[parent_index][child_index] = True
                        with stop_emission(self.selection, 'changed'):
                            self.expand_row(parent.path, False)
                            self.selection.select_path(parent.path)
        GLib.idle_add(self.selection.emit, 'changed')

        # Scroll the first selected track into view.
        self.scroll_first_selected_track(track_tuples)

    def unselect_track(self, track_id):
        selection = self.selection
        model, treepaths = selection.get_selected_rows()
        for track in ModelWithAttrs(model, TrackTuple):
            if track.is_group():
                for child in track.iterchildren():
                    if child.track_id == track_id:
                        track_index = self.get_index(track)
                        child_index = self.get_index(child)
                        self.child_selections[track_index][child_index] = False
                        with stop_emission(selection, 'changed'):
                            selection.unselect_path(child.path)

                        if not any(self.yield_child_selections(track)):
                            self.collapse_row(track.path)
                            selection.unselect_path(track.path)
                        return
            else:
                if track.track_id == track_id:
                    selection.unselect_path(track.path)
                    return

    def scroll_first_selected_track(self, track_tuples):
        model = self.get_model()
        for track_tuple in track_tuples:
            if model_track := model.track_map.get(track_tuple.track_id, None):
                if parent := model_track.parent:
                    model_track = parent
                self.scroll_to_cell(model_track.path, None, True, 0.5, 0.0)
                break

    def scroll_playing_track(self, track_id):
        model = self.get_model()
        getter = itemgetter(0, 1)
        for row in model:
            if getter(row) == track_id:
                GLib.idle_add(self.scroll_to_cell,
                        row.path, None, True, 0.5, 0.0)
                break

