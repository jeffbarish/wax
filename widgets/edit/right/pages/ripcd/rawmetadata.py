"""The TextView for viewing raw metadata from MusicBrainz."""

from typing import Dict, Optional
from itertools import groupby

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.utilities import debug
from widgets import options_button

class RawMetadata(Gtk.TextView):
    def __init__(self):
        super().__init__()
        self.set_name('mb-metadata')
        self.set_editable(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD)

        self.text_buffer = text_buffer = self.get_buffer()
        text_buffer.create_tag('fg_color', foreground='#6683D9')
        text_buffer.create_tag('key_font', font='monospace-condensed 9')

        self.connect('button-release-event', self.on_button_release_event)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

        self.show()

    def on_button_release_event(self, textview, event):
        text_buffer = self.text_buffer
        if text_buffer.get_has_selection():
            leftiter, rightiter = text_buffer.get_selection_bounds()
            if not leftiter.starts_word():
                leftiter.backward_word_start()
            if not rightiter.ends_word() and rightiter.get_char() != '>':
                rightiter.forward_find_char(lambda c, u: c in ' ,;:)>\n')
                text = text_buffer.get_text(leftiter, rightiter, False)
                # When the user sweeps out part of "First Last (soprano)",
                # we want to keep the ")".  When the user sweeps out part
                # of "First Last" in "(feat. First Last), we do not want
                # to keep the ")".
                if '(' in text and rightiter.get_char() == ')':
                    rightiter.forward_char()
            text_buffer.select_range(leftiter, rightiter)

    def on_options_edit_clear_activate(self, menuitem):
        self.clear()

    def clear(self):
        text_buffer = self.text_buffer
        text_buffer.delete(*text_buffer.get_bounds())

    def display_metadata(self,
            metadata: Dict,
            tracknumbers: Optional[Dict] = None):
        def ranges(nums):
            """Group a list of numbers into ranges of numbers."""
            # The lambda takes the difference between nums and a sequence of
            # ascending integers. That difference jumps when nums skips some
            # integers, which terminates a group. We use the first and last
            # value in each group to create a string specifying each range.
            for k, g in groupby(enumerate(nums), lambda t: t[1] - t[0]):
                g = list(g)
                low, high = (g[0][1], g[-1][1])
                yield str(low) + '-{}'.format(high) * bool(high > low)
        def printer(key, lines):
            if len(lines) == 1:
                self.display_metadata_line(key, lines[0])
            elif len(lines) > 1:
                self.display_metadata_line(f'\n{key}:')
                for i, line in enumerate(lines):
                    if tracknumbers is None or (key, line) not in tracknumbers:
                        if key == 'track':
                            line_numbers = [str(i)]
                        else:
                            line_numbers = [chr(i + ord('a'))]
                    else:
                        n_tracks = metadata.get('n_tracks', -1)
                        if len(tracknumbers[(key, line)]) == n_tracks:
                            line_numbers = ['all']
                        else:
                            nums = tracknumbers[(key, line)]
                            line_numbers = list(ranges(nums))
                    self.display_metadata_line(','.join(line_numbers), line)

        if 'album' in metadata:
            self.display_metadata_line('album', ', '.join(metadata['album']))
        if 'codec' in metadata and metadata['codec'] == 'WAV':
            self.write_message('WAV file: no tags')
        else:
            if 'artist' in metadata:
                printer('artist', metadata['artist'])
            for k, v in metadata.items():
                if k not in ('album', 'tracks', 'cover', 'n_images',
                        'n_tracks', 'codec', 'asin', 'artist'):
                    printer(k, v)
            if 'tracks' in metadata:
                printer('track', metadata['tracks'])
            if 'n_images' in metadata:
                n_images = metadata['n_images']
                message_format = {0: 'found no images',
                        1: 'found 1 image'}.get(n_images, 'found {:d} images')
                self.display_metadata_line(message_format.format(n_images))
            self.display_metadata_line('')

    def display_metadata_line(self, key, val=None):
        text_buffer = self.get_buffer()
        get_end_iter = text_buffer.get_end_iter
        text_buffer.insert_with_tags_by_name(get_end_iter(), f'{key}',
                'key_font', 'fg_color')
        if val is not None:
            text_buffer.insert_with_tags_by_name(get_end_iter(), ': ',
                'key_font', 'fg_color')
            text_buffer.insert_with_tags(get_end_iter(), f'{val}\n')
        else:
            text_buffer.insert_with_tags(get_end_iter(), '\n')

