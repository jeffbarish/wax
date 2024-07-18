"""SaveButton is subclassed from DoubleButton. It provides 'Save new'
and 'Save revision' control."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject

from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.utilities import debug
from widgets.doublebutton import DoubleButton

class SaveButton(DoubleButton):
    @GObject.Signal
    def save_button_clicked(self, arg: str):
        pass

    def __init__(self):
        super().__init__()
        self.set_name('save-button')

        register_connect_request('edit-tracks-page',
                'notify::save-selection-nonnull',
                self.on_set_save_button_sensitive)
        register_connect_request('edit-work-page',
                'notify::primary-is-complete',
                self.on_set_save_button_sensitive)
        register_connect_request('edit-left-notebook',
                'notify::changed',
                self.on_set_save_button_sensitive)
        register_connect_request('edit-left-notebook',
                'notify::revise-mode',
                self.on_revise_mode)

        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)

    def on_recording_saved(self, editnotebook, genre):
        self.left_button.set_sensitive(False)
        self.right_button.set_sensitive(False)

    def on_set_save_button_sensitive(self, obj, paramspec):
        self._set_sensitive()

    def on_revise_mode(self, editnotebook, param):
        revise_mode = editnotebook.get_property(param.name)

        if revise_mode:
            # Permit selection of 'Save new', but default to
            # 'Save revision'.
            self.left_button.set_label('Save revision')
        else:
            self.left_button.set_label('Save new')

    # Handlers in:
    #   tracks.editor: track_metadata_changed_quiet <- False
    #   work.editor: work_metadata_changed_quiet <- False
    #   images: images_changed_quiet <- False
    #   properties: properties_changed_quiet <- False
    #   editnotebook: save everything, revise_mode <- True, changed <- False
    #     set_selection: change genre, load metadata
    #                    call edit-left-notebook.on_recording_selection_changed
    #     on_recording_selection_changed: revise_mode <- True
    def on_left_button_clicked(self, button):
        label = button.get_label()
        self.emit('save-button-clicked', label)

    def _set_sensitive(self):
        playable_tracks_selection_nonnull = getattr_from_obj_with_name(
                'edit-tracks-page.playable_tracks_selection_nonnull')
        primary_is_complete = getattr_from_obj_with_name(
                'edit-work-page.primary_is_complete')
        editnotebook = getattr_from_obj_with_name('edit-left-notebook')
        changed = editnotebook.changed
        sensitive = (playable_tracks_selection_nonnull
                and primary_is_complete
                and changed)
        self.left_button.set_sensitive(sensitive)
        revise_mode = editnotebook.revise_mode
        self.right_button.set_sensitive(sensitive and revise_mode)

