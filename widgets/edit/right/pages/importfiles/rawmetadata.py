"""The TextView for viewing raw metadata from tags."""

import os
from collections import defaultdict
from datetime import datetime
from itertools import groupby
from operator import itemgetter
from string import punctuation, whitespace

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from mutagen.id3 import PictureType

from .tagextractors import extract
from common.constants import TRANSFER
from common.decorators import idle_add
from common.types import TrackTuple
from common.utilities import debug
from ripper import ripper
from widgets import options_button

REJECT_TAGS = ('bitrate', 'codec', 'bits_per_sample', 'sample_rate', 'discid',
        'tracktotal', 'genre', 'musicbrainz_discid', 'images', 'tracknumber',
        'discnumber', 'isrc', 'totaldiscs', 'duration', 'tagging_time',
        'channel num', 'channel type', 'isrcs', 'itunescompilation',
        'peak level (r128)', 'dynamic range (r128)', 'dynamic range (dr)',
        'volume level (replaygain)', 'tool name', 'peak level (sample)',
        'bpm', 'replaygain_track_peak', 'replaygain_track_gain',
        'volume level (r128)', 'upc')

class RawMetadata(Gtk.ScrolledWindow):
    @GObject.Signal
    def import_started(self, uuid: str, disc_num: int):
        pass

    @GObject.Signal
    def import_finished(self):
        pass

    def __init__(self):
        super().__init__()
        self.set_name('tags-metadata')
        self.set_margin_top(3)
        self.set_margin_left(3)

        self.textview = Gtk.TextView.new()
        self.textview.set_editable(False)
        self.add(self.textview)

        self.text_buffer = text_buffer = self.textview.get_buffer()
        text_buffer.create_tag('fg_color', foreground='#6683D9')
        text_buffer.create_tag('key_font', font='monospace-condensed 9')

        self.connect('button-release-event', self.on_button_release_event)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

    def on_button_release_event(self, textview, event):
        text_buffer = self.text_buffer
        if text_buffer.get_has_selection():
            leftiter, rightiter = text_buffer.get_selection_bounds()
            if not leftiter.starts_word():
                leftiter.backward_word_start()
            if not rightiter.ends_word() and rightiter.get_char() != '>':
                rightiter.forward_find_char(lambda c, u: c in ' ,;:)>\n')
                text = text_buffer.get_text(leftiter, rightiter, False)
                # When the user sweeps out part of 'First Last (soprano)',
                # we want to keep the ')'.  When the user sweeps out part
                # of 'First Last' in '(feat. First Last), we do not want
                # to keep the ')'.
                if '(' in text and rightiter.get_char() == ')':
                    rightiter.forward_char()
            text_buffer.select_range(leftiter, rightiter)

    def on_options_edit_clear_activate(self, menuitem):
        self.clear()

    def clear(self):
        text_buffer = self.text_buffer
        text_buffer.delete(*text_buffer.get_bounds())

    def print_metadata(self, metadata, tracknumbers=None):
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
                self.print_metadata_line(key, lines[0])
            elif len(lines) > 1:
                self.print_metadata_line(key + ':')
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
                    self.print_metadata_line(','.join(line_numbers), line)

        if 'album' in metadata:
            self.print_metadata_line('album', ', '.join(metadata['album']))
        if 'codec' in metadata and metadata['codec'] == 'WAV':
            self.write_message('WAV file: no tags')
        else:
            if 'artist' in metadata:
                printer('artist', metadata['artist'])
            for k, v in metadata.items():
                if k not in ('album', 'tracks', 'cover', 'n_tracks',
                        'codec', 'asin', 'artist'):
                    printer(k, v)
            self.print_metadata_line('')

    def print_metadata_line(self, key, val=None):
        text_buffer = self.text_buffer
        get_end_iter = text_buffer.get_end_iter
        newline = '\n' * bool(text_buffer.get_char_count())
        text_buffer.insert_with_tags_by_name(get_end_iter(), f'{newline}{key}',
                'key_font', 'fg_color')
        if val is not None:
            text_buffer.insert_with_tags_by_name(get_end_iter(), ': ',
                'key_font', 'fg_color')
            text_buffer.insert_with_tags(get_end_iter(), val)

    def write_message(self, message):
        """Write a message in raw_metadata textview.  The message appears in
        fg_color (currently blue) surrounded by brackets."""
        text_buffer = self.text_buffer
        end_iter = text_buffer.get_end_iter()
        newline = '\n' * bool(text_buffer.get_char_count())
        text_buffer.insert_with_tags_by_name(end_iter,
                f'{newline}<{message}>', 'key_font', 'fg_color')
        self.scroll_metadata_textview()

    def write_data(self, message):
        """Write metadata in raw_metadata textview.  Unlike messages, data
        appear in white without brackets and there is an extra newline so
        that nothing is visible in the raw_metadata textview when it is
        collapsed to one line (its default height)."""
        text_buffer = self.text_buffer
        end_iter = text_buffer.get_end_iter()
        newline = '\n\n' * bool(message not in ('', '\n')
                and text_buffer.get_char_count())
        text_buffer.insert_with_tags_by_name(end_iter,
                f'{newline}{message}')
        self.scroll_metadata_textview()

    @idle_add
    def scroll_metadata_textview(self):
        """Move the scrollbar to the bottom so that the last line is
        visible."""
        sb = self.get_vscrollbar()
        if sb is not None:
            sb.set_value(self.props.vadjustment.props.upper)

    def import_selected_files(self, file_dir, file_names):
        docs = set()
        tracks = []
        tags = {}
        worklines = defaultdict(set)
        tracknumbers = defaultdict(set)
        images_set = set()

        self.emit('import-started', ripper.uuid, ripper.disc_num)
        for track_num, file_name in enumerate(file_names):
            root, ext = os.path.splitext(file_name)
            match ext:
                case '.jpg' | '.jpeg' | '.png':
                    image = self.read_image_file(file_dir, file_name)
                    images_set.add(image)
                    continue
                case '.pdf':
                    # Just make a note of the doc file name. On save, we copy
                    # that file to a location in the database.
                    doc_file_name = self.accept_doc_file(file_dir, file_name)
                    docs.add(doc_file_name)
                    continue

            i_track = ripper.import_track(file_dir, file_name)

            try:
                tags = self.extract_tags(file_dir, file_name)
            except IOError as e:
                if str(e) != 'isdir':
                    message = f'Skipping {file_name} (Unkown file type)'
                    self.write_message(message)
                continue

            self.process_tags(track_num, i_track,
                    tracks, tags, worklines, tracknumbers, images_set)

        # If I imported only an image or a doc then there are no tags.
        if not tags:
            images = list(images_set) if images_set else []
            return {}, [], [], [], images, docs

        # Extract metadata, tracks, and images from accumulated data.
        metadata, tracks, props_rec, props_wrk, images = self.process_data(
                tracks, tags, worklines, tracknumbers, images_set)

        self.emit('import-finished')

        return metadata, tracks, props_rec, props_wrk, images, docs

    def process_tags(self, track_num, i_track,
            tracks, tags, worklines, tracknumbers, images_set):
        for key, val in tags.items():
            if key == 'cover':
                continue
            elif key == 'title':
                tracknumbers[('track', val[0])].add(track_num)
            elif key not in REJECT_TAGS \
                    and not key.endswith('sort') \
                    and not key.startswith('Acoustid'):
                worklines[key].update(val)
                for v in val:
                    tracknumbers[(key, v)].add(track_num)
        track_title, = tags.get('title', (f'Track {i_track}',))
        track_title = track_title.strip(punctuation + whitespace)
        duration, = tags['duration']
        tracktuple = TrackTuple(0, i_track, track_title, duration)
        # The discnum tag is useful in multi-CD sets. If I do not heed
        # this tag, then I have to assume that users will import tracks
        # corresponding to multiple CDs in the correct order.
        try:
            discnum = int(tags.get('discnumber', ['-1'])[0]) - 1
        except ValueError as e:
            print(f'Error converting discnumber: {e}')
            discnum = -1
        try:
            # tracknumber might have the form '1/6' (1 of 6).  If so,
            # we want only the first part.
            tracknumber = tags.get('tracknumber', ['-1'])
            tracknum = int(tracknumber[0].split('/')[0]) - 1
        except ValueError as e:
            print(f'Error converting tracknumber: {e}')
            tracknum = -1
        tracks.append(((discnum, tracknum), tracktuple))

        # Accumulate images.
        for image in tags.get('images', []):
            image_type = getattr(image, 'type', None)
            images_set.add((image.data, image_type))

    def process_data(self, tracks, tags, worklines, tracknumbers, images_set):
        metadata = {k: list(v) for k, v in worklines.items()}
        for key, val in metadata.items():
            val.sort(key=lambda v: tracknumbers[(key, v)])
        self.print_metadata(metadata, tracknumbers)

        # First sort images by desc, then put images with type
        # COVER_FRONT in front, then remove the image type.
        image_l = list(images_set)
        if image_l:
            image_l.sort(key=lambda i: i[1] != PictureType.COVER_FRONT)
            images = image_l
        else:
            images = []

        # Reorder the tracks if the specification in the tags is valid:
        # The set of discnums must be complete (only one value (which will
        # be -2 if all tracks lack a discnumber tag)) or no missing tags and
        # no duplicates) and the set of tracknums for each discnum must be
        # complete.
        get_tracknum = itemgetter(0)
        tracknums_d = defaultdict(list)
        for discnum, tracknum in map(get_tracknum, tracks):
            tracknums_d[discnum].append(tracknum)
        discnums = list(tracknums_d)
        discnums.sort()
        for tracknums in tracknums_d.values():
            tracknums.sort()

        discnums_valid = (len(discnums) == 1
                or discnums == list(range(len(discnums))))
        tracknums_valid = \
                all(tracknums[-1] - tracknums[0] + 1 == len(tracknums)
                    for tracknums in tracknums_d.values())
        if discnums_valid and tracknums_valid:
            tracks_orig = list(tracks)
            tracks.sort(key=get_tracknum)
            tracks = [(t[0], t[1]._replace(track_num=i_track))
                    for i_track, t in enumerate(tracks)]
            if tracks != tracks_orig:
                self.write_message('Tracks renumbered by tracknumber tag')

        tracks = list(map(itemgetter(1), tracks))

        # Set props based on the last tag.
        props_d = {}
        props_d['codec'] = tuple(tags['codec'])
        props_d['sample rate'] = tuple(tags['sample_rate'])
        props_d['resolution'] = tuple(tags['bits_per_sample'])
        props_d['source'] = ('File',)
        props_d['date created'] = (datetime.now().strftime('%Y %b %d'),)
        props_rec = list(props_d.items())

        props_wrk = [('times played', ('0',))]

        return metadata, tracks, props_rec, props_wrk, images

    def extract_tags(self, file_dir, file_name):
        source_path = os.path.join(TRANSFER, file_dir.lstrip('/'), file_name)
        if os.path.isdir(source_path):
            raise IOError('isdir')
        tags = extract(source_path)
        return tags

    def read_image_file(self, file_dir, file_name):
        file_path = os.path.join(TRANSFER, file_dir, file_name)
        with open(file_path, 'rb') as fo:
            image_data = fo.read()
        return image_data, -1

    def accept_doc_file(self, file_dir, file_name):
        return os.path.join(TRANSFER, file_dir, file_name)

