"""A form (TracksMetadataEditor) for entering and editing track metadata."""

import re
from typing import NamedTuple, List, Tuple

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, GObject

from common.connector import getattr_from_obj_with_name
from common.connector import register_connect_request
from common.constants import NOEXPAND
from common.contextmanagers import signal_blocker
from common.descriptors import QuietProperty
from common.types import TrackTuple, GroupTuple
from common.types import ModelWithAttrs
from common.utilities import debug
from ripper import ripper
from widgets import options_button
from .findcommonprefix import find_commonprefix, stripper
from .selectbutton import SelectButton
from .trackmetadatafield import TrackSecondaryMetadataEditor

class EditTrackRowTuple(NamedTuple):
    save_activatable: bool
    track_tuple: object
    playable: bool

@Gtk.Template.from_file('data/glade/edit/left/track.glade')
class TracksMetadataEditor(Gtk.Box):
    __gtype_name__ = 'edit_track_vbox'

    track_treeview = Gtk.Template.Child()
    track_treestore = Gtk.Template.Child()
    track_treeselection = Gtk.Template.Child()
    track_tuple_column = Gtk.Template.Child()
    track_title_renderer = Gtk.Template.Child()
    top_buttons_box = Gtk.Template.Child()
    group_button = Gtk.Template.Child()
    ungroup_button = Gtk.Template.Child()
    group_box = Gtk.Template.Child()
    group_title_entry = Gtk.Template.Child()
    ungroup_box = Gtk.Template.Child()
    ungroup_title_entry = Gtk.Template.Child()

    playable_tracks_selection_nonnull = \
            GObject.Property(type=bool, default=False)
    _track_metadata_changed = QuietProperty(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.set_name('edit-tracks-page')
        self.tab_text = 'Tracks'

        self.select_button = select_button = SelectButton()
        select_button.connect('select-button-clicked',
                self.on_select_button_clicked)
        self.top_buttons_box.pack_start(select_button, *NOEXPAND)
        self.top_buttons_box.reorder_child(select_button, 0)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        # track_model is the wrapped version of track_treestore which
        # enables access to fields by their name.
        self.track_model = ModelWithAttrs(self.track_treestore,
                EditTrackRowTuple)

        col = self.track_tuple_column
        cell = self.track_title_renderer
        def func(column, cell, model, treeiter, *data):
            track_tuple = model[treeiter][1]
            cell.props.text = track_tuple.title
        col.set_cell_data_func(cell, func)

        # Icons from /usr/share/icons/breeze-dark/actions/24/gtk-clear.svg.
        position = Gtk.EntryIconPosition.SECONDARY
        pb = GdkPixbuf.Pixbuf.new_from_file('data/images/gtk-clear.png')
        self.ungroup_title_entry.set_icon_from_pixbuf(position, pb)
        self.group_title_entry.set_icon_from_pixbuf(position, pb)

        self.track_secondary_metadata_editor = TrackSecondaryMetadataEditor()
        self.track_secondary_metadata_editor.connect(
                'track-secondary-metadata-changed',
                self.on_track_secondary_metadata_changed)
        self.pack_end(self.track_secondary_metadata_editor, *NOEXPAND)

        self.show_all()

        self.connect('notify::track-metadata-changed',
                self.on_track_metadata_changed)

        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)
        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

        # Enable DnD in track_treeview to reorder tracks.
        self.track_treeview.enable_model_drag_source(
                Gdk.ModifierType.BUTTON1_MASK,
                [('track_treeview_row', Gtk.TargetFlags.SAME_WIDGET, 0)],
                Gdk.DragAction.MOVE)
        self.track_treeview.enable_model_drag_dest(
                [('track_treeview_row', Gtk.TargetFlags.SAME_WIDGET, 0)],
                Gdk.DragAction.MOVE)

    # Purge the entries for disc_num.
    def on_abort_button_clicked(self, button):
        if not ripper.rerip:
            if ripper.disc_num == 0:
                self.clear()
            else:
                for row in reversed(self.track_treestore):  # top level only
                    # If the row has children, get track_tuple from the first
                    # child (all children have the same disc_num).
                    row_iter = self.track_treestore.iter_children(row.iter) \
                            or row.iter
                    track_tuple = self.track_model[row_iter].track_tuple
                    if track_tuple.disc_num >= ripper.disc_num:
                        # Note that removing a row with children removes the
                        # children as well.
                        self.track_treestore.remove(row.iter)

    def on_options_edit_clear_activate(self, menuitem):
        self._track_metadata_changed = False

    def do_key_press_event(self, event):
        if event.keyval == Gdk.KEY_g \
                and event.state & Gdk.ModifierType.CONTROL_MASK:
            if self.group_button.is_visible():
                self.on_group_button_clicked(self.group_button)
            elif self.ungroup_button.is_visible():
                self.on_ungroup_button_clicked(self.ungroup_button)

    def on_track_metadata_changed(self, obj, param):
        edit_message_label = getattr_from_obj_with_name('edit-message-label')
        if self.track_metadata_changed:
            edit_message_label.queue_message('track metadata changed')

    def on_save_button_clicked(self, button, label):
        self._track_metadata_changed = False

    @Gtk.Template.Callback()
    def on_track_treeview_drag_motion(self, treeview, drag_context, x, y,
            timestamp):
        model, source_paths = self.track_treeselection.get_selected_rows()
        source_iter = model.get_iter(source_paths[0])

        dest_row = treeview.get_dest_row_at_pos(x, y)
        if dest_row is None:
            return
        path, position = dest_row
        dest_iter = model.get_iter(path)

        # Do not permit a drop from one track group into another.
        def parent_path(i):
            p = model.iter_parent(i)
            if p is None:
                return None
            return model.get_path(p)
        if parent_path(source_iter) == parent_path(dest_iter):
            self.track_treeview.enable_model_drag_dest(
                    [('track_treeview_row', Gtk.TargetFlags.SAME_WIDGET, 0)],
                    Gdk.DragAction.MOVE)
        else:
            self.track_treeview.enable_model_drag_dest(
                    [('invalid-position', Gtk.TargetFlags.SAME_WIDGET, 0)],
                    Gdk.DragAction.MOVE)

    @Gtk.Template.Callback()
    def on_track_treeview_drag_data_received(self, treeview, drag_context,
            x, y, selection, info, timestamp):
        model, source_paths = self.track_treeselection.get_selected_rows()
        source_iter = model.get_iter(source_paths[0])

        drop_info = treeview.get_dest_row_at_pos(x, y)
        if drop_info is None:
            GLib.idle_add(model.move_before, source_iter, None)
        else:
            path, position = drop_info
            dest_iter = model.get_iter(path)
            if position in (Gtk.TreeViewDropPosition.BEFORE,
                    Gtk.TreeViewDropPosition.INTO_OR_BEFORE):
                GLib.idle_add(model.move_before, source_iter, dest_iter)
            else:
                GLib.idle_add(model.move_after, source_iter, dest_iter)
        self._track_metadata_changed = True

    def populate(self,
            all_tracks: List[TrackTuple],
            work_tracks: List[TrackTuple],
            trackgroups: List[Tuple[str, List[Tuple[int, int]]]]) -> None:
        model = self.track_treestore

        self.group_map = group_map = {}
        for g_title, g_tracks, g_metadata in trackgroups:
            g_tuple = GroupTuple(g_title, g_metadata)
            for track_id in g_tracks:
                group_map[track_id] = g_tuple

        track_map = {t.track_id: t for t in all_tracks}
        work_tracks_iter = (track_map[track_id] for track_id in work_tracks)

        current_group = None
        for track_tuple in all_tracks:
            # If track_tuple is in the work, yield tracks in the order
            # specified for the work rather than the original order.
            if track_tuple.track_id in work_tracks:
                track_tuple = next(work_tracks_iter)

            # Remove extraneous spaces from track title.
            new_title = ' '.join(track_tuple.title.split())
            track_tuple = track_tuple._replace(title=new_title)

            group_tuple = group_map.get(track_tuple.track_id, None)
            playable = track_tuple.track_id in work_tracks
            if current_group is not None and group_tuple != current_group:
                # Went from one group to another.
                model[groupiter][0] = group_playable
                current_group = None
            if group_tuple is None:
                # Not in a group.
                if current_group is not None:
                    model[groupiter][0] = group_playable
                current_group = None
                row = (True, track_tuple, playable)
                model.append(None, row)
            elif group_map[track_tuple.track_id] == current_group:
                # Continue a group.
                row = (False, track_tuple, playable)
                model.append(groupiter, row)
                group_playable |= playable
            else:
                # Start a new group.
                group_tuple = group_map[track_tuple.track_id]
                converted_group_tuple = TrackTuple._convert(group_tuple)
                row = (True, converted_group_tuple, playable)
                groupiter = model.append(None, row)
                row = (False, track_tuple, playable)
                model.append(groupiter, row)
                group_playable = playable
                current_group = group_tuple

        self.select_button.set_sensitive(True)
        self.playable_tracks_selection_nonnull = True
        self._track_metadata_changed = False

    # Called from importfiles (in add).
    def append(self, tracks):
        for track in tracks:
            self.track_treestore.append(None, (True, track, True))
        self._track_metadata_changed = True

    def clear(self):
        self.track_treestore.clear()
        self.select_button.set_sensitive(False)

        self._track_metadata_changed = False

    def update_button_sensitivity(self):
        model = self.track_treestore
        sensitive = any(row.playable for row in self.track_model)

        self.select_button.set_sensitive(len(model))
        self.playable_tracks_selection_nonnull = sensitive
        self._track_metadata_changed = True

        # If all rows ticked, then select_button should show checkbox-none;
        # otherwise checkbox-all.
        all_rows_ticked = all(row.playable for row in self.track_model)
        state = ('all', 'none')[all_rows_ticked]
        self.select_button.set_state(state)

    @Gtk.Template.Callback()
    def on_playable_toggle_renderer_toggled(self, renderer, index):
        edit_track_row = self.track_model[index]

        new_value = not edit_track_row.playable
        edit_track_row.playable = new_value

        # If there are children then this track is a group. Set playable
        # of the children to the same value.
        for child_edit_track_row in edit_track_row.iterchildren():
            child_edit_track_row.playable = new_value

        self.update_button_sensitivity()

    def on_select_button_clicked(self, button, select):
        actions = {'all': self.select_all,
                'none': self.select_none,
                'reverse': self.select_reverse}
        actions[select]()
        self._track_metadata_changed = any(row.playable
                for row in self.track_model)

    def select_all(self):
        for edit_track_row in self.track_model:
            edit_track_row.playable = True
            for child_edit_track_row in edit_track_row.iterchildren():
                child_edit_track_row.playable = True

    def select_none(self):
        for edit_track_row in self.track_model:
            edit_track_row.playable = False
            for child_edit_track_row in edit_track_row.iterchildren():
                child_edit_track_row.playable = False

    def select_reverse(self):
        for edit_track_row in self.track_model:
            new_value = not edit_track_row.playable
            edit_track_row.playable = new_value
            for child_edit_track_row in edit_track_row.iterchildren():
                child_edit_track_row.playable = new_value

    @Gtk.Template.Callback()
    def on_text_renderer_edited(self, renderer, index, new_text):
        track_tuple = self.track_model[index].track_tuple
        new_track_tuple = track_tuple._replace(title=new_text)
        self.track_model[index].track_tuple = new_track_tuple
        self._track_metadata_changed = True
        if new_track_tuple.is_group():
            self.ungroup_title_entry.set_text(new_text)

    @Gtk.Template.Callback()
    def on_track_treeselection_changed(self, selection):
        self.track_secondary_metadata_editor.track_metadata_hide()

        model, selected_paths = selection.get_selected_rows()
        # To sensitize group_button, the user must select more than one row,
        # no row can contain a TrackGroup, the row cannot be in a TrackGroup
        # already, and the tracks must be consecutive.
        group_button = self.group_button
        match len(selected_paths):
            case 0:
                group_button.set_sensitive(False)
                self.group_box.hide()
                self.ungroup_box.hide()
            case 1:
                group_button.set_sensitive(False)
                self.group_box.hide()
                # To sensitize ungroup_tracks_button, the user must select
                # only a single row and the row must contain a TrackGroup.
                path, = selected_paths
                treeiter = model.get_iter(path)
                has_children = model.iter_has_child(treeiter)
                self.ungroup_box.set_visible(has_children)
                track_tuple = self.track_model[path].track_tuple
                if has_children:
                    title = track_tuple.title
                    self.ungroup_title_entry.set_text(title)
                self.track_secondary_metadata_editor.track_metadata_show(
                        track_tuple)
            case _:  # any length > 1
                for path in selected_paths:
                    treeiter = model.get_iter(path)
                    if model.iter_has_child(treeiter) or model[path].parent:
                        group_button.set_sensitive(False)
                        self.group_box.hide()
                        break
                else:
                    # The tracks also have to be consecutive.
                    for first_path, next_path in zip(selected_paths[:-1],
                            selected_paths[1:]):
                        first_path.next()  # advance first_path in place
                        try:
                            if first_path.compare(next_path):  # 0 if equal
                                group_button.set_sensitive(False)
                                self.group_box.hide()
                                break
                        finally:
                            # Restore first_path because we have further uses
                            # for selected_paths if the tracks are consecutive.
                            first_path.prev()
                    else:  # the tracks are consecutive
                        titles = [self.track_model[path].track_tuple.title
                                for path in selected_paths]
                        common_prefix = find_commonprefix(titles)

                        group_button.set_sensitive(True)
                        self.group_box.show()
                        self.group_title_entry.set_text(common_prefix)
                self.ungroup_box.hide()

    @Gtk.Template.Callback()
    def on_group_title_entry_icon_press(self, entry, position, eventbutton):
        entry.set_text('')

    @Gtk.Template.Callback()
    def on_ungroup_title_entry_icon_press(self, entry, position, eventbutton):
        entry.set_text('')

    @Gtk.Template.Callback()
    def on_group_button_clicked(self, button):
        model, selected_paths = self.track_treeselection.get_selected_rows()
        with signal_blocker(self.track_treeselection, 'changed'):
            self.group(model, selected_paths)
        self.track_treeselection.unselect_all()
        self.track_treeselection.select_path(selected_paths[0])
        self._track_metadata_changed = True

        common_prefix = self.group_title_entry.get_text().rstrip()
        self.clipboard.set_text(common_prefix, -1)

    @Gtk.Template.Callback()
    def on_ungroup_button_clicked(self, button):
        model, selected_paths = self.track_treeselection.get_selected_rows()
        self.ungroup(model, selected_paths[0])
        self.track_treeselection.unselect_all()
        self.track_treeselection.select_path(selected_paths[0])
        self._track_metadata_changed = True

    def on_track_secondary_metadata_changed(self, editor, metadata):
        model, selected_paths = self.track_treeselection.get_selected_rows()
        edit_track_row = self.track_model[selected_paths[0]]
        track_tuple = edit_track_row.track_tuple
        edit_track_row.track_tuple = track_tuple._replace(metadata=metadata)
        self._track_metadata_changed = True

    def group(self, model, paths):
        child_rows = [EditTrackRowTuple._make(model[path]) for path in paths]
        first_iter = model.get_iter(paths[0])
        for path in paths:
            iter_still_valid = model.remove(first_iter)

        group_title = stripper(self.group_title_entry.get_text())
        parent_track_tuple = TrackTuple._convert(GroupTuple(group_title))
        parent_row = (True, parent_track_tuple, True)
        if iter_still_valid:
            group_iter = model.insert_before(None, first_iter, parent_row)
        else:  # removed last row, so append
            group_iter = model.append(None, parent_row)

        for path, child_row in zip(paths, child_rows):
            track_tuple = child_row.track_tuple

            # Remove 'group_title' from track title, if it is actually there.
            track_title = re.sub(group_title, '', track_tuple.title)
            track_title = stripper(track_title)
            new_track_tuple = track_tuple._replace(title=track_title)

            new_child_row = (False, new_track_tuple, True)
            model.append(group_iter, new_child_row)

    def ungroup(self, model, path):
        group_row = model[path]
        group_title = self.ungroup_title_entry.get_text()

        # Keep actual copies of the child rows before removing the parent.
        # The map object alone does not do that.
        child_rows = list(map(EditTrackRowTuple._make,
                group_row.iterchildren()))

        parent_iter = model.get_iter(path)
        iter_still_valid = model.remove(parent_iter)

        for child in child_rows:
            track_tuple = child.track_tuple
            if group_title:
                new_title = f'{group_title} {track_tuple.title}'
                track_tuple = track_tuple._replace(title=new_title)

            # Remove extraneous punctuation and whitespace.
            new_title = stripper(track_tuple.title)
            track_tuple = track_tuple._replace(title=new_title)

            new_child = (True, track_tuple, child.playable)
            if iter_still_valid:
                model.insert_before(None, parent_iter, new_child)
            else:  # group was last row, so append
                model.append(None, new_child)

    def get_metadata(self):
        tracks, trackids_playable, trackgroups = [], [], []
        for row in self.track_model:
            if self.track_model.row_has_child(row):
                group_track_ids = []
                for child in row.iterchildren():
                    tracks.append(child.track_tuple)
                    group_track_ids.append(child.track_tuple.track_id)
                    if child.playable:
                        trackids_playable.append(child.track_tuple.track_id)
                trackgroups.append((row.track_tuple.title,
                        group_track_ids,
                        row.track_tuple.metadata))
            else:
                tracks.append(row.track_tuple)
                if row.playable:
                    trackids_playable.append(row.track_tuple.track_id)
        return tracks, trackids_playable, trackgroups

