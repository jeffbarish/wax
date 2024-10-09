"""This module displays long metadata."""

import os
import importlib
import pickle
import shutil
import shelve
from enum import Enum, auto
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, GObject

from common.config import config
from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.constants import SHORT, LONG
from common.constants import SOUND, DOCUMENTS, IMAGES
from common.constants import COMPLETERS
from common.descriptors import QuietProperty
from common.types import RecordingTuple, WorkTuple
from common.utilities import debug
from ripper import ripper
from widgets import options_button
from widgets import edit
from widgets.select.left.pages.select.recordingselector \
        import RecordingModelRow

class Action(Enum):
    NONE = auto()
    REVISE = auto()
    READCD = auto()
    IMPORT = auto()

@Gtk.Template.from_file('data/glade/edit/left/notebook.glade')
class EditNotebook(Gtk.Notebook):
    __gtype_name__ = 'edit_left_notebook'

    @GObject.Signal
    def recording_saved(self, genre: str):
        pass

    @GObject.Signal
    def work_deleted(self, genre: str, uuid: str, work_num: int):
        pass

    @GObject.Signal
    def recording_deleted(self, uuid: str):
        pass

    _changed = QuietProperty(type=bool, default=False)
    _revise_mode = QuietProperty(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.set_name('edit-left-notebook')
        self.recording = None

        self.select_genre = None
        self.work_num = 0
        self.action = Action.NONE

        # pages will map the name of the page to the page.
        self.pages = pages = {}

        # Import the modules for pages of the notebook. They are located
        # in the 'pages' subdirectory.
        size_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.VERTICAL)
        page_names = \
                ['work', 'tracks', 'images', 'docs', 'properties', 'files']
        for page_name in page_names:
            qual_name = f'widgets.edit.left.pages.{page_name}'
            page = importlib.import_module(qual_name)
            pages[page_name] = page
            page_widget = page.page_widget
            self.append_page(page_widget)
            self.set_tab_label_text(page_widget, page_widget.tab_text)
            tab_label = self.get_tab_label(page_widget)
            tab_label.set_angle(270)
            size_group.add_widget(tab_label)

        self.set_sensitive(False)

        self.connect('notify::changed', self.on_changed)
        self.connect('notify::revise_mode', self.on_revise_mode)

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('genre-button', 'genre-changed',
                self.on_select_genre_changed)
        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)

        # All changes get funneled to the same handler.
        register_connect_request('edit-work-page',
                'notify::edit-genre-changed',
                self.on_something_changed)
        register_connect_request('edit-work-page',
                'notify::work-metadata-changed',
                self.on_something_changed)
        register_connect_request('edit-tracks-page',
                'notify::track-metadata-changed',
                self.on_something_changed)
        register_connect_request('edit-properties-page',
                'notify::properties-changed',
                self.on_something_changed)
        register_connect_request('edit-images-page',
                'notify::images-changed',
                self.on_something_changed)
        register_connect_request('edit-docs-page',
                'notify::docs-changed',
                self.on_something_changed)

        register_connect_request('edit-ripcd', 'rip-create-clicked',
                self.on_rip_create_clicked)
        register_connect_request('edit-importfiles', 'import-create-clicked',
                self.on_import_create_clicked)
        register_connect_request('tags-metadata', 'import-started',
                self.on_import_started)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)
        options_button.connect_menuitem('Edit', 'Delete',
                self.on_options_edit_delete_activate)

        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)

    def on_rip_create_clicked(self, button):
        self.clear_all_forms()
        self.set_sensitive(True)
        self._revise_mode = False
        self.recording = None

        options_button.sensitize_menuitem('Edit', 'Delete', False)

        self.action = Action.READCD

    def on_import_create_clicked(self, importfiles):
        self.clear_all_forms()
        self._revise_mode = False
        self.recording = None

        self.action = Action.IMPORT

    def on_import_started(self, importer, uuid, disc_num):
        # Setting sensitive to True in the handler for import-create-clicked
        # does not work if it is necessary to abort a rip as the handler for
        # rip-aborted (which occurs after import-create-clicked) sets sensitive
        # to False. import-started occurs later because it is produced as
        # a consequence of the following sequence of events:
        # ripper responds to import-create-clicked by telling engine to stop
        # ripping. ripper also emits rip-aborted immediately (without waiting
        # for engine to actually finish aborting). importfiles runs import_
        # from the idle loop so that all handlers for import-create-clicked
        # (and the handlers for rip-aborted which it triggers) run first.
        # import_ runs raw_metadata.import_selected_files which runs
        # importer.import_track. import_track emits import-started, so this
        # handler runs well after import-create-clicked.
        self.set_sensitive(True)

    def on_options_edit_clear_activate(self, menuitem):
        # Clear returns edit mode to the last saved state. It stops an
        # ongoing rip and it removes zombies (tracks that were ripped
        # but not saved). It then clears all the forms and re-selects
        # the selection in Select mode (if there is one).
        #
        # clear_or_repopulate_from_selection calls populate for each page.
        # The populate methods for tracks.editor and files do not clear
        # first because they also get called when adding tracks.
        track_metadata_editor = self.pages['tracks'].page_widget
        track_metadata_editor.clear()

        files_editor = self.pages['files'].page_widget
        files_editor.clear()

        self.clear_or_repopulate_from_selection()

    # The delete option deletes the work that is currently selected (not the
    # entire recording). However, if no work remains after the deletion, then
    # delete the recording.
    def on_options_edit_delete_activate(self, menuitem):
        works = self.recording.works
        work = works[self.work_num]
        del works[self.work_num]

        self.delete_work_from_metadata_files()

        if not works:
            self.delete_sound()
            self.delete_notes()
            self.delete_images()

            self.clear_all_forms()
            self.set_sensitive(False)

            self.action = Action.NONE

            ripper.reset()

            options_button.sensitize_menuitem('Edit', 'Delete', False)

        self.revise_mode = False

        # work-deleted triggers deletion of the work in selector.
        # model.recording does not change until the work is deleted. Until
        # the work is deleted, clear_or_repopulate_from_selection does not
        # clear the display.
        self.emit(
            'work-deleted', work.genre, self.recording.uuid, self.work_num)

        # Wait for the work-deleted handler in selector to run.
        GLib.idle_add(self.clear_or_repopulate_from_selection)

    def on_abort_button_clicked(self, button):
        if ripper.rerip:
            # Nothing needs to happen here on rerip. ripper.engine deletes
            # the .part file.
            return

        if ripper.disc_num == 0:
            if self.revise_mode:
                # We are doing (or did) an initial rip of disc 0 and we saved
                # at least one work. All changes to files need to be reversed.
                self.delete_notes()
                self.delete_images()

                # If we get here, then the abort applies to an initial
                # rip of disc 0. ripper deletes all the sound files, so
                # we need to delete *all* works that were saved, regardless
                # of genre. selector.on_recording_deleted deletes all
                # the works for uuid in the current select genre.
                self.delete_short_metadata(edit.uuid)
                self.delete_long_metadata(edit.uuid)

                self.revise_mode = False

                GLib.idle_add(self.emit,
                        'recording-deleted', self.recording.uuid)
            else:
                # If the user did not save the recording before clicking
                # abort then it is still possible to go back to the original
                # selection.
                self.clear_or_repopulate_from_selection()
        elif self.recording is not None:  # disc_num > 0 and recording saved
            for work_num, work in self.recording.works.items():
                work.track_ids[:] = [(d_n, t_n) for d_n, t_n in work.track_ids
                        if d_n != ripper.disc_num]
            self.recording.tracks[:] = [t for t in self.recording.tracks
                    if t.track_id[0] != ripper.disc_num]
            self.write_long_metadata(self.recording)

    def on_changed(self, obj, param):
        sensitive = self.changed
        options_button.sensitize_menuitem('Edit', 'Clear', sensitive)

    def on_revise_mode(self, obj, param):
        sensitive = self.changed and self.revise_mode
        options_button.sensitize_menuitem('Edit', 'Clear', sensitive)

    def on_something_changed(self, obj, param):
        # Assemble all of the changed properties to decide how to set
        # the master changed property.
        edit_genre_changed = getattr_from_obj_with_name(
                'edit-work-page.edit_genre_changed')
        work_metadata_changed = getattr_from_obj_with_name(
                'edit-work-page.work_metadata_changed')
        track_metadata_changed = getattr_from_obj_with_name(
                'edit-tracks-page.track_metadata_changed')
        properties_changed = getattr_from_obj_with_name(
                'edit-properties-page.properties_changed')
        images_changed = getattr_from_obj_with_name(
                'edit-images-page.images_changed')
        docs_changed = getattr_from_obj_with_name(
                'edit-docs-page.docs_changed')
        self._changed = edit_genre_changed \
                or work_metadata_changed \
                or track_metadata_changed \
                or properties_changed \
                or images_changed \
                or docs_changed

    def on_select_genre_changed(self, genre_button, genre):
        # After a user clicks Save, changed is False even though a rip
        # might still be underway. The edit genre should not track the
        # select genre as long as the rip is underway.
        if self.changed or ripper.is_ripping:
            return

        work_metadata_editor = self.pages['work'].page_widget
        work_metadata_editor.prepare(genre)

        self.select_genre = genre

        self.clear_all_forms()
        self.set_sensitive(False)

    def on_recording_selection_changed(self, selection):
        # The user may change the selection in select mode after an edit is
        # underway, but edit mode is dedicated to the original recording
        # until the edit is either saved or cleared.
        #
        # When the user clicks Create, ripping starts. There is a brief
        # period when changed is still False because nothing has arrived
        # yet from the internet. changed will also be False after the
        # user clicks Save even if a rip is still underway. Likewise,
        # changed is True once metadata arrives even after ripping is
        # finished until the user clicks Save. Thus, the "edit mode is
        # busy" state is the OR of changed and is_ripping.
        if self.changed or ripper.is_ripping:
            return

        # The user could change to a different edit genre then return to
        # Select mode and, without ever changing the genre in Select mode,
        # select a recording. The edit genre needs to be brought into
        # synchronization with the select genre.
        work_metadata_editor = self.pages['work'].page_widget
        if self.select_genre != work_metadata_editor.edit_genre:
            work_metadata_editor.genre_button.genre = self.select_genre

        self.clear_all_forms()
        self.populate_forms_from_selection(selection)

        model_filter, treeiter = selection.get_selected()
        self.action = (Action.REVISE, Action.NONE)[treeiter is None]

    def on_save_button_clicked(self, button, label):
        self.select_genre = genre = self.get_work_metadata_editor_genre()
        work_long, work_short = self.get_work_metadata()
        nonce = self.get_nonce()
        tracks, trackids_playable, trackgroups = self.get_tracks()
        props_rec, props_wrk = self.get_props()

        new_work = WorkTuple(
            genre=genre,
            metadata=work_long,
            nonce=nonce,
            props=props_wrk,
            track_ids=trackids_playable,
            trackgroups=trackgroups)

        # If I am revising a recording made from imported tracks, then
        # disc_ids is irrelevant. However, ripper.disc_ids got set to
        # ['0'] in populate_forms_from_selection, so that value gets
        # propagated here.
        if self.revise_mode:
            match label:
                case 'Save revision':
                    old_work = self.recording.works[self.work_num]
                    if genre != old_work.genre:
                        self.delete_short_metadata_for_work(old_work.genre,
                                edit.uuid, self.work_num)
                    self.recording = self.save_revision(new_work,
                            self.recording.works, tracks, props_rec,
                            list(ripper.disc_ids), self.work_num)
                case 'Save new':
                    self.work_num = max(self.recording.works) + 1
                    self.recording = self.recording._replace(tracks=tracks)
                    self.recording.works[self.work_num] = new_work
        else:
            match self.action:
                case Action.READCD:
                    self.recording = self.create_new_recording(new_work,
                            tracks, props_rec, list(ripper.disc_ids))
                    self.work_num = 0
                case Action.IMPORT:
                    self.recording = self.create_new_recording(new_work,
                            tracks, props_rec, ['0'])
                    self.work_num = 0

            self._revise_mode = True

        self.write_long_metadata(self.recording)
        self.write_short_metadata(work_short, genre,
                edit.uuid, self.work_num)

        # Get edit-images-page to write the current images to files.
        images_editor = self.pages['images'].page_widget
        images_editor.write_images(edit.uuid)

        if self.action == Action.READCD:
            images_editor.tag_cover_art(edit.uuid)

        # Get edit-docs-page to write the current docs to files.
        docs_editor = self.pages['docs'].page_widget
        docs_editor.write_docs(edit.uuid)

        files_editor = self.pages['files'].page_widget
        files_editor.populate(self.recording.uuid, new_work.track_ids)

        # Emit recording-saved to trigger updates to the models.
        # The signal is connected to handlers in select.selector,
        # playnotebook, coverartviewer, playqueue, files, and savebutton.
        self.emit('recording-saved', genre)

        options_button.sensitize_menuitem('Edit', 'Delete', True)

        self.learn_new_completions(work_long)

        self._changed = False

    def clear_or_repopulate_from_selection(self):
        # Clear returns edit mode to the last saved state. It stops an
        # ongoing rip and it removes zombies (tracks that were ripped
        # but not saved). It then clears all the forms and re-selects
        # the selection in Select mode (if there is one).
        selector = getattr_from_obj_with_name('selector')
        model = selector.recording_selector.model
        if model.recording is None:
            self.clear_all_forms()
            self.set_sensitive(False)
            self._revise_mode = False
            self.recording = None
        else:
            work_metadata_editor = self.pages['work'].page_widget
            if self.select_genre != work_metadata_editor.edit_genre:
                work_metadata_editor.genre_button.genre = self.select_genre
                work_metadata_editor.prepare(self.select_genre)

            selection = selector.recording_selection
            GLib.idle_add(self.populate_forms_from_selection, selection)
            self.revise_mode = True

        self._changed = False
        self.action = Action.NONE

    def populate_forms_from_selection(self, selection):
        model_filter, treeiter = selection.get_selected()
        if treeiter is None:
            self._revise_mode = False
            self.recording = None
            options_button.sensitize_menuitem('Edit', 'Delete', False)
            self.set_sensitive(False)
            ripper.reset()
        else:
            self.set_sensitive(True)
            if not ripper.is_ripping:
                self._revise_mode = True

            model = model_filter.props.child_model
            self.recording = recording = model.recording
            edit.set_uuid(recording.uuid)
            self.work_num = model.work_num
            metadata = model.metadata
            work = model.work

            # If no edit is underway, set ripper.uuid to the selected
            # recording in case the user clicks Add CD to rerip the tracks.
            ripper.init_disc(recording.uuid, recording.discids)

            # Unlike play mode, edit mode handles each category of
            # metadata differently, so separate primary and secondary here.
            # Weave long and short together for primary metadata. Reformat
            # secondary. After these operations, metadata is formatted as
            # [('key', [('long', 'short'), ...]), ...] for primary and
            # [('key', [('long',), ...]), ...] for secondary. If there are
            # multiple values (namegroup), then there are additional tuples
            # in the list associated with a key.
            row = RecordingModelRow._make(model_filter[treeiter])
            work_metadata_editor = self.pages['work'].page_widget
            work_metadata_editor.populate(self.select_genre,
                    primary=list(self.weave(metadata, row.short)),
                    secondary=list(self.reformat(metadata[len(row.short):])),
                    nonce=list(self.reformat(work.nonce)))

            # Populate the track page.
            track_metadata_editor = self.pages['tracks'].page_widget
            track_metadata_editor.populate(recording.tracks,
                    work.track_ids, work.trackgroups)

            # Populate the images page.
            images_editor = self.pages['images'].page_widget
            images_editor.populate(recording.uuid)

            # Populate the documents page.
            docs_editor = self.pages['docs'].page_widget
            docs_editor.populate(recording.uuid)

            # Populate the properties page.
            properties_editor = self.pages['properties'].page_widget
            properties_editor.populate(recording.props, work.props)

            # Populate the files page.
            files_editor = self.pages['files'].page_widget
            files_editor.populate(recording.uuid, work.track_ids)

            options_button.sensitize_menuitem('Edit', 'Delete', True)

    def create_new_recording(self, new_work, tracks, props, disc_ids):
        works = {0: new_work}

        return RecordingTuple(works, tracks, props, disc_ids, edit.uuid)

    def save_revision(self, new_work, works, tracks, props,
                disc_ids, work_num):
        works[work_num] = new_work

        return RecordingTuple(works, tracks, props, disc_ids, edit.uuid)

    def update_work_props(self, uuid, work_num, props):
        if self.revise_mode \
                and self.recording.uuid == uuid \
                and self.work_num == work_num:
            properties_editor = self.pages['properties'].page_widget
            properties_editor.populate(self.recording.props, props)

    # Customize set_sensitive so that genre_button is always sensitive.
    # work.editor also has a custom set_sensitive. Otherwise, this
    # set_sensitive operates on the top level of every page in the
    # notebook, but not the notebook itself.
    def set_sensitive(self, sensitive):
        for child in self.get_children():
            child.set_sensitive(sensitive)

    def learn_new_completions(self, work_long):
        work_metadata_editor = self.pages['work'].page_widget
        work_genre = work_metadata_editor.work_genre

        all_keys = sum(config.genre_spec[work_genre].values(), [])
        for key, value in zip(all_keys, work_long):
            # Secondary metadata might not have a value.
            if not any(value):
                continue

            completer_fn = Path(COMPLETERS, key)
            if not completer_fn.is_file():
                continue
            if not config.completers[key][1]:
                continue

            names = list(value)
            with open(completer_fn, 'r', encoding='utf-8') as completer_fo:
                lines = completer_fo.read().splitlines()

            self.learning = False
            for name in set(names) - set(lines):
                dialog = LearnDialog(self)
                dialog.set_messages(key, name, len(lines))
                match dialog.run():
                    case Gtk.ResponseType.YES:
                        lines.append(name)
                        self.learning = True
                    case Gtk.ResponseType.CANCEL:
                        pass
                    case Gtk.ResponseType.REJECT:
                        with config.modify('completers') as completers:
                            enabled, learn = completers[key]
                            completers[key] = (enabled, False)
                dialog.destroy()
            if self.learning:
                with open(completer_fn, 'w', encoding='utf-8') as completer_fo:
                    completer_fo.write('\n'.join(lines))
                    completer_fo.write('\n')

    def delete_long_metadata(self, uuid):
        with shelve.open(LONG, 'w') as recording_shelf:
            try:
                del recording_shelf[uuid]
            except KeyError:
                # If we were ripping disc 0 for the first time when we
                # aborted then there is no entry in recording_shelf yet.
                # If we were reripping then an entry was created previously
                # which needs to be deleted now.
                pass

    # Delete short metadata for uuid from the short file of every genre
    # in which it appears. (Used when aborting a rip of disc_num = 0.)
    def delete_short_metadata(self, uuid):
        # The dict of works in recording provides the genres in which
        # uuid appears.
        with shelve.open(LONG, 'w') as recording_shelf:
            recording = recording_shelf[uuid]

        # Multiple works with uuid could be in the same genre, so
        # create a set to suppress duplication.
        genres = {work.genre for work in recording.works.values()}

        # Delete all works in the short file for genre for uuid.
        for genre in genres:
            self.delete_short_metadata_from_genre(genre, uuid)

    # Delete short metadata for uuid from the short file only for genre.
    def delete_short_metadata_from_genre(self, genre, uuid):
        short_path = Path(SHORT, genre)
        tmp_path = Path(str(short_path) + '.tmp')
        with open(short_path, 'rb') as short_fo, \
                open(tmp_path, 'wb') as tmp_fo:
            while True:
                try:
                    data_in = pickle.load(short_fo)
                except EOFError:
                    break
                metadata, uuid_in, work_num_in = data_in
                if uuid_in != uuid:
                    pickle.dump(data_in, tmp_fo)

        # Replace the metadata file with the tmp file.
        tmp_path.rename(short_path)

    # Delete short metadata from the short file for genre for the solitary
    # work with uuid and work_num. (Used when saving a revision.)
    def delete_short_metadata_for_work(self, genre, uuid, work_num):
        short_path = Path(SHORT, genre)
        tmp_path = Path(str(short_path) + '.tmp')
        with open(short_path, 'rb') as short_fo, \
                open(tmp_path, 'wb') as tmp_fo:
            while True:
                try:
                    data_in = pickle.load(short_fo)
                except EOFError:
                    break
                metadata, uuid_in, work_num_in = data_in
                if (uuid_in, work_num_in) != (uuid, work_num):
                    pickle.dump(data_in, tmp_fo)

        # Replace the metadata file with the tmp file.
        tmp_path.rename(short_path)

    def write_long_metadata(self, recording):
        with shelve.open(LONG, 'w') as recording_shelf:
            recording_shelf[recording.uuid] = recording

    def write_short_metadata(self, work_short, genre, uuid, work_num):
        # Read pickles from the short metadata file and write them to
        # the tmp file. For the incoming pickle that corresponds to this
        # recording, write the new metadata instead. If no pickle corresponds
        # to this recording, append the recording.
        short_path = Path(SHORT, genre)
        tmp_path = Path(str(short_path) + '.tmp')
        with open(short_path, 'rb') as short_fo, \
                open(tmp_path, 'wb') as tmp_fo:
            new_data_out = (tuple(work_short), uuid, work_num)
            while True:
                try:
                    data_in = pickle.load(short_fo)
                except EOFError:
                    break
                metadata, uuid_in, work_num_in = data_in
                if (uuid_in, work_num_in) == (uuid, work_num):
                    pickle.dump(new_data_out, tmp_fo)
                    new_data_out = ()
                else:
                    pickle.dump(data_in, tmp_fo)
            if new_data_out:
                # Append short metadata if uuid did not match an
                # existing recording.
                pickle.dump(new_data_out, tmp_fo)

        # Replace the metadata file with the tmp file.
        tmp_path.rename(short_path)

    # Weave the long and short primary metadata together.
    def weave(self, metadata_long, metadata_short):
        for (key, long_vals), short_vals in zip(metadata_long, metadata_short):
            yield (key, list(zip(long_vals, short_vals)))

    def reformat(self, metadata):
        for key, vals in metadata:
            yield (key, list(zip(vals)))

    def get_work_metadata_editor_genre(self):
        work_metadata_editor = self.pages['work'].page_widget
        return work_metadata_editor.work_genre

    def get_work_metadata(self):
        work_metadata_editor = self.pages['work'].page_widget
        work_metadata_editor.consolidate()
        work_metadata = work_metadata_editor.get_metadata()

        # Unweave long and short primary metadata.
        metadata_long, metadata_short = [], []
        for key, values in work_metadata:
            genre = work_metadata_editor.work_genre
            if key in config.genre_spec[genre]['primary']:
                values_long, values_short = zip(*values)
                metadata_short.append(values_short)
            else:
                values_long, = zip(*values)
            metadata_long.append(values_long)
        return metadata_long, metadata_short

    def get_nonce(self):
        work_metadata_editor = self.pages['work'].page_widget
        nonce = work_metadata_editor.get_nonce()

        # values is a name group, so each value corresponds to another name
        # associated with the same key. Each value is a (v,) tuple for
        # consistency with the (long, short) tuples associated with primary
        # metadata. We return a list of (key, (val1, ...)) tuples.
        return [(key, tuple(v for v, in values)) for key, values in nonce]

    def get_tracks(self):
        track_metadata_editor = self.pages['tracks'].page_widget
        return track_metadata_editor.get_metadata()

    def get_props(self):
        props_metadata_editor = self.pages['properties'].page_widget
        return props_metadata_editor.get_props()

    def clear_all_forms(self):
        for module in self.pages.values():
            module.page_widget.clear()

        for textview_name in ('mb-metadata', 'tags-metadata'):
            edit_textview = getattr_from_obj_with_name(textview_name)
            edit_textview.clear()

    def delete_work_from_metadata_files(self):
        # The Delete option is sensitive only when a recording is selected in
        # Select mode. Therefore, self.recording is never None here.
        if self.recording is None:
            return

        uuid = self.recording.uuid
        work_num = self.work_num

        short_path = Path(SHORT, self.select_genre)
        tmp_path = Path(str(short_path) + '.tmp')
        with open(short_path, 'rb') as short_fo, \
                open(tmp_path, 'wb') as tmp_fo:
            while True:
                try:
                    data_in = pickle.load(short_fo)
                except EOFError:
                    break
                # Copy data_in to the tmp file unless its uuid and work_num
                # match the uuid and work_num of the recording we are deleting.
                metadata, uuid_in, work_num_in = data_in
                if (uuid_in, work_num_in) != (uuid, work_num):
                    pickle.dump(data_in, tmp_fo)

        # Replace the metadata file with the tmp file.
        tmp_path.rename(short_path)

        with shelve.open(LONG, 'w') as recording_shelf:
            recording = recording_shelf[uuid]
            works = recording.works
            del works[work_num]

            # If no works remain after deleting the current work, then delete
            # the entire recording.
            if works:
                recording_shelf[uuid] = recording
            else:
                del recording_shelf[uuid]

    def delete_sound(self):
        sound_path = Path(SOUND, edit.uuid)
        shutil.rmtree(sound_path, ignore_errors=True)

    def delete_notes(self):
        documents_path = Path(DOCUMENTS, edit.uuid)
        shutil.rmtree(documents_path, ignore_errors=True)

    def delete_images(self):
        images_path = Path(IMAGES, edit.uuid)
        shutil.rmtree(images_path, ignore_errors=True)


@Gtk.Template.from_file('data/glade/learn_dialog.glade')
class LearnDialog(Gtk.Dialog):
    __gtype_name__ = 'learn_dialog'

    learn_checkbutton = Gtk.Template.Child()
    learn_query_label = Gtk.Template.Child()
    learn_ncount_label = Gtk.Template.Child()
    learn_checkbutton_label = Gtk.Template.Child()

    def __init__(self, parent):
        super().__init__()
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        self.add_buttons(Gtk.STOCK_SAVE, Gtk.ResponseType.YES)
        self.show_all()

        top_level = parent.get_toplevel()
        self.set_transient_for(top_level)

        self.learn_checkbutton.connect('toggled',
                self.on_learn_checkbutton_toggled)

    def on_learn_checkbutton_toggled(self, button):
        self.response(Gtk.ResponseType.REJECT)

    def set_messages(self, key, name, n_names):
        name = GLib.markup_escape_text(name)  # in case there is an &
        self.learn_query_label.set_markup(
            f'Learn name <span foreground="#009185">{name}</span>\n'
            f'for key <span foreground="#009185">{key}</span>?')
        self.learn_ncount_label.set_markup(
            f'(Key <span foreground="#009185">{key}</span> '
            f'has <span foreground="#009185">{n_names}</span> names)')
        self.learn_checkbutton_label.set_markup(f'Do not learn names for key '
            f'<span foreground="#009185">{key}</span>')

