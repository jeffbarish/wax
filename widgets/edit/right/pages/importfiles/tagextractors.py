"""Extract tags from sound file.  Note that values are always a tuple to
support multiple values for a tag."""

import wave
import re
import base64
from collections import namedtuple

from mutagen.flac import Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen import MutagenError

from common.utilities import debug

# Used in tagextractor.m4a_extractor to return pictures in a class consistent
# with the one returned by flac_extractor and ogg_extractor. The declaration
# is here to make pickling/unpickling possible.
MP4Picture = namedtuple('MP4Picture', ['data', 'desc'])

# A map from the extension to the function for extracting tags from files
# of that type.
EXT_MAP = {}

# A map from the extension to the codec name that we will use as a property.
CODEC_NAMES = {}

# SaveDict is used for tags.
class SafeDict(dict):
    def __missing__(self, key):
        return ('',)

def extract(source_path):
    """The main function automatically calls the right extractor based on
    the extension in source_path."""
    _, ext = source_path.rsplit('.', 1)
    ext_l = ext.lower()

    tags = SafeDict()  # the dict of tags that we extract
    try:
        tags['codec'] = [CODEC_NAMES[ext_l]]
    except KeyError:
        raise IOError(f'Unknown file extension ({ext})')

    return EXT_MAP[ext_l](source_path, tags)

def _remove_empty_strings(tags):
    """Remove any empty strings from the list of values and convert all
    values to unicode. Used only for ID3 tags."""
    new_tags = {}
    for key, val in tags.items():
        if isinstance(val, list):
            new_tags[key] = list(filter(bool, val))
        else:
            new_tags[key] = val
    return new_tags

def _find_source(tags):
    """Search through tags for a URL (such as www.eClassical.com or
    eClassical.com).  If found, the source is the string in front of
    .com."""
    sources = []
    url_re = re.compile(r'(?:\s|www\.)(\w+)\.com')
    for key, val in tags.items():
        if isinstance(val, list):
            for v in val:
                if isinstance(v, str):
                    mo = url_re.search(v)
                    if mo:
                        sources.append(mo.group(1))
        else:
            if isinstance(val, str):
                mo = url_re.search(val)
                if mo:
                    sources.append(mo.group(1))
    return sources or ['File']

def register(exts, name):
    """exts is a list of extensions that the extractor will recognize and
    name is the string to use as the value for the property 'codec'."""
    def wrap(f):
        for ext in exts:
            EXT_MAP[ext] = f
            CODEC_NAMES[ext] = name
        return f
    return wrap

@register(['wav'], 'WAV')
def wav_extractor(source_path, tags):
    try:
        snd_file = wave.open(source_path)
    except wave.Error as e:
        message = f'Error reading header of {source_path} ({e})'
        raise IOError(message)

    nframes = snd_file.getnframes()
    framerate = snd_file.getframerate()
    tags['duration'] = (float(nframes) / float(framerate),)
    tags['bits_per_sample'] = (snd_file.getsampwidth() * 8,)
    tags['sample_rate'] = (framerate / 1000.0,)
    snd_file.close()

    tags['source'] = ['File']

    return tags

@register(['flac'], 'FLAC')
def flac_extractor(source_path, tags):
    try:
        snd_file = FLAC(source_path)
    except MutagenError as e:
        message = f'Error reading header of {source_path} ({e})'
        raise IOError(message)

    # eClassical uses the involved_people_list tag. They use ^C to
    # separate the role (e.g., 'conductor' or 'violin') from the name,
    # and the name is 'Last, First'. Reformat in Wax style.
    def reverse_name(name):
        if ',' in name:
            name_s = name.split(', ', 1)
            name = ' '.join(reversed(name_s))
        return name
    if 'involved_people_list' in snd_file:
        new_names = []
        for involved_person in snd_file['involved_people_list']:
            if b'\x03' in involved_person:
                instrument, name = involved_person.split('\x03')
                name = reverse_name(name)
                involved_person = f'{name} ({instrument})'
            new_names.append(involved_person)
        snd_file['involved_people_list'] = new_names
    # eClassical uses \x0a in artist to separate multiple artists.
    if 'artist' in snd_file:
        artist_l = []
        for artist in snd_file['artist']:
            artist_l.extend(artist.split('/'))
        snd_file['artist'] = [reverse_name(a) for a in artist_l]

    tags.update(snd_file)
    tags['source'] = _find_source(tags)

    bits_per_sample = getattr(snd_file.info, 'bits_per_sample', 0)
    tags['bits_per_sample'] = (f'{bits_per_sample:d}'
            if bits_per_sample > 0 else '',)

    sample_rate = getattr(snd_file.info, 'sample_rate', 0.0) / 1000.0
    tags['sample_rate'] = (f'{sample_rate:.1f} kHz'
            if sample_rate > 0 else '',)

    tags['duration'] = (getattr(snd_file.info, 'length', 0),)

    if hasattr(snd_file, 'pictures') and len(snd_file.pictures):
        tags['images'] = snd_file.pictures

    return tags

@register(['ogg'], 'Ogg')
def ogg_extractor(source_path, tags):
    try:
        snd_file = OggVorbis(source_path)
    except MutagenError as e:
        message = f'Error reading header of {source_path} ({e})'
        raise IOError(message)

    if 'metadata_block_picture' in snd_file \
            and len(snd_file['metadata_block_picture']):
        tags['images'] = [Picture(base64.b64decode(p))
                for p in snd_file['metadata_block_picture']]
        del snd_file['metadata_block_picture']

    tags.update(snd_file)
    tags['source'] = _find_source(tags)

    bits_per_sample = getattr(snd_file.info, 'bits_per_sample', 0)
    tags['bits_per_sample'] = (f'{bits_per_sample:d}'
            if bits_per_sample > 0 else '',)

    tags['duration'] = (getattr(snd_file.info, 'length', 0),)

    return tags

@register(['m4a', 'mp4'], 'MP4')
def m4a_extractor(source_path, tags):
    try:
        snd_file = MP4(source_path)
    except MutagenError as e:
        message = f'Error reading header of {source_path} ({e})'
        raise IOError(message)

    # Apple uses a proprietary metadata scheme.  I found a table at
    # http://atomicparsley.sourceforge.net/mpeg-4files.html.  Also
    # http://audiotools.sourceforge.net/programming/metadata.html.
    # Rename keys to standard values.  (u'\xa9' is the copyright
    # symbol.)
    key_map = {b'\xa9ART': 'artist',
            b'\xa9alb': 'album',
            b'\xa9day': 'date',
            b'\xa9wrt': 'composer',
            b'\xa9nam': 'title',
            b'aArt': 'albumartist',
            b'\xa9wrt': 'composer'}
    if 'covr' in snd_file:
        pictures = [MP4Picture(d, '') for d in snd_file['covr']]
        tags['images'] = pictures
        del snd_file['covr']

    # Keep only the keys in key_map and use their standard forms.
    tags.update({key_map[k]: snd_file[k] for k in key_map if k in snd_file})

    tags['source'] = _find_source(snd_file)

    bits_per_sample = getattr(snd_file.info, 'bits_per_sample', 0)
    tags['bits_per_sample'] = (f'{bits_per_sample:d}'
            if bits_per_sample > 0 else '',)

    tags['duration'] = (getattr(snd_file.info, 'length', 0),)

    return tags

@register(['mp3'], 'MP3')
def mp3_extractor(source_path, tags):
    try:
        snd_file = MP3(source_path)
    except MutagenError as e:
        message = f'Error reading header of {source_path} ({e})'
        raise IOError(message)

    key_map = {'TIT2': 'title',
            'TALB': 'album',
            'TPE1': 'artist',
            'TPE2': 'albumartist',
            'TPE3': 'conductor',
            'TEXT': 'lyricist',
            'TCOM': 'composer',
            'TDRC': 'date'}

    # The keys are in the form 'APIC:<desc>'.
    images = [snd_file[k] for k in snd_file if k.startswith('APIC')]
    if images:
        tags['images'] = images

    tags.update({key_map[k]: snd_file[k].text for k in key_map
            if k in snd_file})

    # mutagen returns values of [u''], which complicates null detection.
    tags = _remove_empty_strings(tags)

    # mutagen returns date as mutagen.id3._specs.ID3TimeStamp.
    tags['source'] = _find_source(snd_file)

    bits_per_sample = getattr(snd_file.info, 'bits_per_sample', 0)
    tags['bits_per_sample'] = (f'{bits_per_sample:d}'
            if bits_per_sample > 0 else '',)

    tags['duration'] = (getattr(snd_file.info, 'length', 0),)

    return tags

