"""A form (WorkMetadataForm) for entering and editing work metadata."""

import re
from pathlib import Path
from collections import defaultdict
from itertools import chain, groupby

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib
from fuzzywuzzy import fuzz

from common.config import config
from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.constants import METADATA_CLASSES, COMPLETERS
from common.descriptors import QuietProperty
from common.genrespec import genre_spec
from common.initlogging import logger
from common.types import NameGroup, Name_LongShort
from common.types import MetadataItem_LongShort
from common.utilities import debug
from ripper import ripper
from widgets import options_button
from widgets.genrebutton import GenreButton
from widgets.select.left.pages.select import filter_button_box
from .abbreviators import abbreviator
from .fields import Entry, NonceWorkMetadataField
from .group import WorkMetadataGroup, NonceWorkMetadataGroup


class WorkMetadataEditor(Gtk.ScrolledWindow):
    """The WorkMetadataEditor is a Scrolledwindow containing a box with
    groups for all metadata types."""

    primary_is_complete = GObject.Property(type=bool, default=False)
    _work_metadata_changed = QuietProperty(type=bool, default=False)
    _edit_genre_changed = QuietProperty(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.set_name('edit-work-page')
        self.tab_text = 'Work'

        self.edit_genre = None

        self.vbox = vbox = Gtk.Box()
        vbox.set_orientation(Gtk.Orientation.VERTICAL)
        self.add(vbox)

        hbox = Gtk.Box()
        hbox.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.genre_button = genre_button = GenreButton()
        genre_button.set_size_request(200, -1)
        genre_button.set_relief(Gtk.ReliefStyle.NONE)
        genre_button.set_can_focus(False)
        genre_button.connect('genre-changing', self.on_edit_genre_changing)
        genre_button.connect('genre-changed', self.on_edit_genre_changed)
        hbox.add(genre_button)
        vbox.add(hbox)

        # Create all 3 groups...
        self.metadata_groups = group_types = {
            'primary': WorkMetadataGroup,
            'secondary': WorkMetadataGroup,
            'nonce': NonceWorkMetadataGroup}
        for metadata_class, group_type in group_types.items():
            group = group_type(self, metadata_class)
            group.connect('work-metadata-group-changed',
                    self.on_work_metadata_group_changed)
            vbox.add(group)
            self.metadata_groups[metadata_class] = group

        add_nonce_button = Gtk.Button.new_with_label('+Nonce')
        add_nonce_button.set_can_focus(False)
        add_nonce_button.connect('clicked',
                self.on_add_nonce_button_clicked)
        self.add_nonce_button = add_nonce_button

        hbox = Gtk.Box()
        hbox.set_orientation(Gtk.Orientation.HORIZONTAL)
        hbox.pack_end(add_nonce_button, False, False, 3)
        vbox.pack_start(hbox, False, False, 3)

        self.show_all()
        self.metadata_groups['nonce'].hide()

        self.connect('notify::work-metadata-changed',
                self.on_work_metadata_changed)

        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)
        register_connect_request('genre-button', 'genre-changed',
                self.on_select_genre_changed)
        register_connect_request('edit-ripcd', 'rip-create-clicked',
                self.on_rip_create_clicked)
        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

        filter_button_box.connect('filter-button-deactivated',
                self.on_filter_buttons_reconfigured)
        filter_button_box.connect('filter-button-created',
                self.on_filter_buttons_reconfigured)

        # Identify the widgets whose sensitivity is affected by set_sensitive.
        # genre_button is not in the list, so it remains sensitive when the
        # rest of the form is not.
        self.main_widgets = list(group_types.values()) + [add_nonce_button]

    def set_sensitive(self, sensitive):
        for widget in self.main_widgets:
            widget.set_sensitive(sensitive)

    # Iterators delegate to the groups for the form. Note that the nonce
    # group will be invisible if it is not in use.
    def __getitem__(self, key):
        for group in self.metadata_groups.values():
            if group.get_visible() and key in group:
                return group[key]
        raise ValueError(f'Key {key} not found in any group')

    def __iter__(self):
        return chain.from_iterable(group.keys()
                for group in self.metadata_groups.values()
                    if group.get_visible())

    # If self changes width, set a new width for the short entries of the
    # last field in the primary group (which correspond to the last column
    # in select mode).
    def do_size_allocate(self, allocation):
        # It is not possible to adjust the widths of short entries in
        # edit mode, so the widths are always the same as the widths of
        # the corresponding columns in select mode, and those widths always
        # get written to config whenever they change, so the values in config
        # are always valid here.

        # If there is only one column, then the width of the field for the
        # short entry should be the available width (the width not occupied
        # by the key and the arrow), not the actual width of the column in
        # select mode.
        if len(config['column widths'][self.edit_genre]) == 1:
            new_width = allocation.width - 114
            primary_group = self.metadata_groups['primary']
            primary_group.set_last_field_short_entry_width(new_width)
            Gtk.ScrolledWindow.do_size_allocate(self, allocation)
            return

        # Sum the widths of all but the last column, but exclude any
        # columns represented by a filter button.
        widths = config['column widths'][self.edit_genre][:-1]
        first_cols_width = sum(w for i, w in enumerate(widths)
                if i not in config['filter config'][self.edit_genre])
        new_width = allocation.width - first_cols_width + 25
        if new_width > 0:
            primary_group = self.metadata_groups['primary']
            primary_group.set_last_field_short_entry_width(new_width)

            # The main window changed size so the size of the last column
            # changed size, so update config.
            widths.append(new_width)
            with config.modify('column widths') as column_widths:
                column_widths[self.edit_genre] = widths

        Gtk.ScrolledWindow.do_size_allocate(self, allocation)

    def on_abort_button_clicked(self, button):
        if ripper.disc_num == 0 and not ripper.rerip:
            self.clear()

    def on_options_edit_clear_activate(self, menuitem):
        self._work_metadata_changed = False
        self._edit_genre_changed = False

    def on_work_metadata_changed(self, obj, param):
        edit_message_label = getattr_from_obj_with_name('edit-message-label')
        if self.work_metadata_changed:
            edit_message_label.queue_message('work metadata changed')

    def on_select_genre_changed(self, genre_button, genre):
        # The genre selection in edit mode tracks the genre_button in
        # selector unless editnotebook.changed is True.
        changed = getattr_from_obj_with_name('edit-left-notebook.changed')
        if not changed:
            self.genre_button.set_genre(genre)
            self.edit_genre = genre

        # The Entry class in fields needs to know the set of all keys so
        # that it can populate the swap submenu in the context menu. At a
        # minimum, that set comprises all permanent keys. If a particular
        # recording has nonce keys, they are added in populate on selection
        # of the recording.
        Entry.all_keys = genre_spec.all_keys(genre)

    def on_edit_genre_changing(self, genre_button, genre):
        self.create_mode_metadata = self.get_all_metadata()

        # If we are not in revise mode then changing the edit genre is
        # not a change.
        edit_message_label = getattr_from_obj_with_name('edit-message-label')
        if getattr_from_obj_with_name('edit-left-notebook.revise_mode'):
            self._edit_genre_changed = True
            edit_message_label.queue_message('edit genre changed')

        # If the form is empty, then changing the edit genre is not
        # considered a change.
        if any(any(any(v for v in val) for val in value)
               for key, value in self.create_mode_metadata):
            self._work_metadata_changed = True

    def on_edit_genre_changed(self, genre_button, genre):
        self.edit_genre = genre
        self.prepare(genre)

        # The swap menu in Entry gets all permanent metadata keys for the
        # new genre at a minimum. Add nonce keys in repopulate.
        Entry.all_keys = genre_spec.all_keys(genre)

        self.repopulate()

    def on_add_nonce_button_clicked(self, button):
        group = self.metadata_groups['nonce']
        group.append_field()
        group.show()

    def on_save_button_clicked(self, button, label):
        self._work_metadata_changed = False
        self._edit_genre_changed = False

    def on_rip_create_clicked(self, button):
        self._work_metadata_changed = False
        self._edit_genre_changed = False

    def on_work_metadata_group_changed(self, group):
        self.primary_is_complete = bool(self.metadata_groups['primary'])
        self._work_metadata_changed = True

    def on_filter_buttons_reconfigured(self, filterbuttonbox, column_index):
        self.queue_resize()

    # Initialize the editor with metadata fields whose keys correspond
    # to the genre but with empty values. Do not prepare a group for
    # nonce secondary because there might not be any (whether there are
    # depends on the recording, which we do not know at this point).
    def prepare(self, genre: str):
        primary_keys = config.genre_spec[genre]['primary']
        default_widths = [80] * len(primary_keys)
        widths = config.column_widths.get(genre, default_widths)

        for metadata_class in METADATA_CLASSES:
            group = self.metadata_groups[metadata_class]
            keys = config.genre_spec[genre][metadata_class]
            group.create(keys, widths)
        self.metadata_groups['nonce'].clear()

    # Provide values for the metadata fields in each group. Called from
    # editnotebook and from map_metadata below using kwargs for primary,
    # secondary, and nonce.
    def populate(self, genre: str,
            **metadata: dict[str, list[tuple[str, list[Name_LongShort]]]]):
        for metadata_class in METADATA_CLASSES:
            group = self.metadata_groups[metadata_class]
            group.populate(metadata[metadata_class])

        group = self.metadata_groups['nonce']
        group.clear()
        nonce_metadata = metadata['nonce']
        if nonce_metadata:
            group.populate(nonce_metadata)
            group.show()
        else:
            group.hide()

        GLib.idle_add(self.metadata_groups['primary'].focus_first_entry)

        # Wait for other handlers to run before setting flags.
        def set_flags():
            self.primary_is_complete = bool(self.metadata_groups['primary'])
            self._edit_genre_changed = False
        GLib.idle_add(set_flags)

    # The edit mode genre changed, so the form was cleared and now must be
    # repopulated. In the new genre, nonce metadata might be permanent, so
    # nonce metadata have to be extracted as the residue after primary and
    # secondary are removed.
    #
    # The big difference between populate and repopulate is that the latter
    # does not receive woven metadata. It computes the short metadata using
    # an abbreviator.
    def repopulate(self):
        metadata = self.create_mode_metadata

        # Clear and hide nonce metadata.
        group = self.metadata_groups['nonce']
        group.clear()
        group.hide()

        # Create a list of the keys in this genre from which we can delete
        # keys that match.
        keys = list(self)

        # If fields exist for any of the metadata, use them. In general,
        # the abbreviator for the new genre will be different from the one
        # in the old genre that produced the short values, so apply the new
        # abbreviator to create short values.
        matched_keys = []
        for key, values in metadata:
            if key in keys:
                if key in self.metadata_groups['primary']:
                    # key is primary, so val must have short form.
                    val = [(v[0], abbreviator(v[0]) if len(v) == 1 else v[1])
                            for v in values]
                else:
                    # key is secondary, so val must not have short form.
                    val = [(v[0],) for v in values]
                keys.remove(key)
                self[key].populate(val)
                matched_keys.append(key)
        metadata_dict = dict(metadata)
        for key in matched_keys:
            del metadata_dict[key]

        # Any metadata that did not match (including nonce metadata)
        # will be treated as nonce.
        nonce_metadata_dict = self.extract_nonce_metadata(metadata_dict)
        if nonce_metadata_dict:
            group = self.metadata_groups['nonce']
            group.populate(nonce_metadata_dict.items())
            group.show()

        # Wait for other handlers to run before setting flag.
        def set_flag():
            self.primary_is_complete = bool(self.metadata_groups['primary'])
        GLib.idle_add(set_flag)

    def extract_nonce_metadata(self, metadata: dict) \
            -> dict[str, NameGroup]:
        # exclude is the sum of keys for primary and secondary.
        exclude = genre_spec.all_keys(self.edit_genre)
        return {k: [(v[0],) for v in val] for k, val in metadata.items()
                if k not in exclude and any(v[0] for v in val)}

    # Clear the values from the metadata fields in each group.
    def clear(self):
        for group in self.metadata_groups.values():
            group.clear()
        self.metadata_groups['nonce'].hide()
        self.primary_is_complete = False
        self._work_metadata_changed = False
        self._edit_genre_changed = False

    # Consolidate nonce metadata fields with keys matching the keys of
    # either primary or secondary metadata fields.
    def consolidate(self):
        if not self.metadata_groups['nonce'].get_visible():
            return

        # First purge nonce fields with empty values.
        nonce_group = self.metadata_groups['nonce']
        nonce_group.purge_invalid_nonces()

        # Now perform the actual consolidation.
        delete_nonce_fields = []
        for key, nonce_field in nonce_group.items():
            # Look for key in primary and secondary. If found, merge the
            # nonce value.
            for match_class in METADATA_CLASSES:
                match_group = self.metadata_groups[match_class]
                if key in match_group:
                    match_field = match_group[key]
                    for value in nonce_field.values():
                        match_field.move_buttons_down()
                        if match_class == 'primary':
                            value += (abbreviator(value[0]),)
                        match_field.append_value_field(value)
                    delete_nonce_fields.append(nonce_field)
                    match_field.clean()
        for nonce_field in delete_nonce_fields:
            nonce_group.remove_metadata_field(nonce_field)
            # Also remove nonce_field from the mapping for nonce
            # metadata because this value just got moved into the
            # secondary group.
            nonce_field.unmap_field()

    def purge_invalid_nonces(self):
        nonce_group = self.metadata_groups['nonce']
        nonce_group.purge_invalid_nonces()

    def swap_values(self, src_field, dest_key):
        # Find the field for dest_key.
        for key, dest_field in self.items():
            if key == dest_key:
                break
        else:
            return  # should not happen

        new_dest_values = src_values = list(src_field.values())
        new_src_values = dest_values = list(dest_field.values())

        field_is_primary = \
                (src_field.key in self.metadata_groups['primary'],
                dest_field.key in self.metadata_groups['primary'])

        # When values move between primary and secondary, the new primary
        # values need to have a short form generated.
        match field_is_primary:
            case True, False:
                new_src_values = [(v, abbreviator(v)) for v, in dest_values]
            case False, True:
                new_dest_values = [(v, abbreviator(v)) for v, in src_values]

        dest_field.populate(new_dest_values)
        src_field.populate(new_src_values)

        # If we just swapped a value out of a nonce field, then that field
        # is now invalid.
        if isinstance(src_field, NonceWorkMetadataField) \
                or isinstance(dest_field, NonceWorkMetadataField):
            nonce_group = self.metadata_groups['nonce']
            nonce_group.purge_invalid_nonces()

        self.on_work_metadata_group_changed(None)

    # Return all metadata (including nonce) in the form.
    def get_all_metadata(self) -> list[tuple[str, list[Name_LongShort]]]:
        for k, f in self.items():
            f.clean()

        # Each value in f.values() is a (long, short) tuple for primary
        # or (long,) tuples for secondary. These tuples get unwoven in
        # editnotebook.get_work_metadata.
        return list((k, list(f.values())) for k, f in self.items())

    # Return permanent (not nonce) metadata to editnotebook.get_work_metadata.
    # This method is called by editnotebook.get_work_metadata which is called
    # by editnotebook.on_save_button_clicked. save_button clicked also has a
    # handler in this module. It sets work_metadata_changed to False.
    def get_metadata(self) -> list[tuple[str, list[Name_LongShort]]]:
        for k, f in self.items(include_nonce=False):
            f.clean()

        # As in get_all_metadata, but exclude values from fields of type
        # NonceWorkMetadataField.
        return list((k, list(f.values()))
                for k, f in self.items(include_nonce=False))

    def get_nonce(self) -> list[tuple[str, list[Name_LongShort]]]:
        for k, f in self.items(include_metadata=False):
            f.clean()

        # As above. These tuples get unwoven in editnotebook.get_nonce.
        return list((k, list(f.values()))
                for k, f in self.items(include_metadata=False))

    def unweave(self, metadata: list[MetadataItem_LongShort]
                ) -> tuple[list[NameGroup], list[NameGroup]]:
        metadata_long, metadata_short = [], []
        for key, values in metadata:
            if key in config.genre_spec[self.edit_genre]['primary']:
                values_long, values_short = zip(*values)
                metadata_short.append(values_short)
            else:
                values_long, = zip(*values)
            metadata_long.append(values_long)
        return metadata_long, metadata_short

    def map_metadata(self, mb_metadata: dict[str, list[str]]):
        all_keys = set(genre_spec.all_keys(self.edit_genre))

        completers_path = Path(COMPLETERS)
        completers = {p.name for p in completers_path.iterdir()}

        # match_keys is the set of keys in the genre for which there are
        # also completers.
        match_keys = all_keys & completers

        # Names in involved_people_list often have a parenthetic phrase
        # attached describing the function of the person. Remove it.
        parens_re = re.compile(r" \(.*\)$")
        all_names = [parens_re.sub('', p)
                for p in mb_metadata.get('involved_people_list', [])]

        artist_names = set(mb_metadata.get('artist', []))
        all_names.extend(artist_names)

        # If there were no names in the metadata, then mapping is done.
        if not all_names:
            return

        # If we are importing, then we might find more names in other ID3 tags.
        for key in ['composer', 'conductor', 'lyricist']:
            all_names.extend(mb_metadata.get(key, []))

        # Remove duplicate names.
        all_names.sort()
        all_names = [name for name, g in groupby(all_names)]

        # matches is a dict of {key: set(names)}.
        matches = defaultdict(set)

        # Scan for perfect matches. Remove any perfect matches from
        # all_names and artist_names (if the match is there). Also
        # remove the corresponding key from match_keys as we no longer
        # seek a match (perfect or fuzzy) for the key.
        for key in set(match_keys):
            with Path(completers_path, key).open(encoding='utf-8') as f:
                while match_name := f.readline().strip():
                    if match_name.startswith('#'):
                        continue
                    for name in all_names:
                        if name == match_name:
                            matches[key].add(name)

                            all_names.remove(name)
                            artist_names.discard(name)
                            match_keys.remove(key)

                            break

        # Fuzzy matches consider only the first and last components of names
        # with more than two components (e.g., First Middle Last).
        def first_last(name):
            name_split = name.split()
            if len(name_split) > 1:
                if name_split[0] == 'Sir' and len(name_split) > 2:
                    return f'{name_split[1]} {name_split[-1]}'
                else:
                    return f'{name_split[0]} {name_split[-1]}'
            else:
                return name

        def scanner_fuzzy(key):
            with Path(completers_path, key).open(encoding='utf-8') as f:
                while match_name := f.readline().strip():
                    if match_name.startswith('#'):
                        continue
                    for name in all_names:
                        ratio = fuzz.token_set_ratio(first_last(name),
                                first_last(match_name))
                        if ratio > 90:
                            yield (name, match_name, ratio)

        # If any names remain in all_names and any keys lack a match, iterate
        # over match_keys again seeking fuzzy matches.
        if all_names:
            for key in set(match_keys):
                fuzzy_matches = list(scanner_fuzzy(key))

                # For each name, keep the best match.
                if fuzzy_matches:
                    fuzzy_matches.sort(key=lambda t: t[-1])
                    name, match_name, ratio = fuzzy_matches[-1]
                    matches[key].add(match_name)

                    all_names.remove(name)
                    artist_names.discard(name)
                    match_keys.remove(key)

        # If there are still names in artist_names, then they did not match
        # any key (including 'artist', if artist has a completer file). If
        # there is an artist key, assign remaining names to matches['artist'].
        # If artist has a completer file, then there could already be some
        # names assigned to artist, just not the ones remaining.
        if 'artist' in all_keys and artist_names:
            matches['artist'].update(artist_names)

        # Currently, only three keys might be interested in the content
        # of the album metadata.
        new_names = set()
        for name in mb_metadata.get('album', ['']):
            # Standardize the formatting of the album metadata.
            if mo := re.match(r'[Ss]ymphony\D+(\d+)', name):
                name = f'Symphony No. {mo.group(1)}'
            new_names.add(name)
        keys = set(['work', 'title', 'album']).intersection(all_keys)
        if keys:
            key = keys.pop()  # probably only one key left at this point
            matches[key] = new_names

        # There might be a field for a date in all_keys or mb_metadata, but
        # in either case the key could be either 'date' or 'year' (or both).
        date_keys = {'date', 'year'}
        match_key_set = date_keys.intersection(all_keys)
        mb_metadata_key_set = date_keys.intersection(mb_metadata)

        # Set 'year' and/or 'date' (all_keys could have both) in matches
        # as long as both all_keys and mb_metadata have at least one of
        # 'year' and 'date'. Prioritize use of 'year'.
        def mb_metadata_get_year_or_date():
            for key in ('year', 'date'):
                try:
                    mb_metadata_key_set.remove(key)
                except KeyError:
                    continue
                return mb_metadata[key]

        while match_key_set and mb_metadata_key_set:
            for key in ('year', 'date'):
                try:
                    match_key_set.remove(key)
                except KeyError:
                    continue
                matches[key].update(mb_metadata_get_year_or_date())


        # The form gets cleared in editnotebook on create_button clicked. If
        # any field is populated here, the user must have typed something in
        # after clicking Create and before the mbquery came back from the
        # worker in editsource. Prefer the user's entries.
        current_metadata = dict(self.get_all_metadata())

        # Format matches by metadata class.
        primary_kv_list = []
        for key in self.metadata_groups['primary']:
            value = current_metadata.pop(key)
            if any(any(v for v in val) for val in value):
                if key in matches:
                    del matches[key]
            else:
                abbrev = (abbreviator, str)[key == 'work']
                value = [(v, abbrev(v)) for v in matches.pop(key, {''})]
                # Append (key, value) to list only if key does not have a
                # value provided by the user.
                primary_kv_list.append((key, value))

        secondary_kv_list = []
        for key in self.metadata_groups['secondary']:
            value = current_metadata.pop(key)
            if any(any(v for v in val) for val in value):
                if key in matches:
                    del matches[key]
            else:
                value = [(v,) for v in matches.pop(key, {''})]
                # Append (key, value) to list only if key does not have a
                # value provided by the user.
                secondary_kv_list.append((key, value))

        # Nonce provided by the user should also take priority over values
        # extracted from tags or mb.
        nonce_kv_list = []
        for key, value in current_metadata.items():
            val = next(zip(*value))
            nonce_kv_list.append((key, [val]))

        self.populate(self.edit_genre,
                primary=primary_kv_list,
                secondary=secondary_kv_list,
                nonce=nonce_kv_list)

    def values(self):
        # group.values gets transformed to
        # group.field_type.metadata_fields.values, which is dict.values. The
        # values are the Fields in the group. The Fields, in turn, have a
        # values method, but we are actually returning an iterator over the
        # Fields in every group here. Likewise for items, below.
        return chain.from_iterable(group.values()
                for group in self.metadata_groups.values()
                    if group.get_visible())

    def items(self, include_metadata=True, include_nonce=True):
        def condition(group):
            match include_metadata, include_nonce:
                case True, True:
                    return True
                case True, False:
                    return not isinstance(group, NonceWorkMetadataGroup)
                case False, True:
                    return isinstance(group, NonceWorkMetadataGroup)

        return chain.from_iterable(group.items()
                for group in self.metadata_groups.values()
                    if group.get_visible() and condition(group))

