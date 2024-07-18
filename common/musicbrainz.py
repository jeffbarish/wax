"""Provide access to MusicBrainz metadata through attributes tracks,
worklines, and tracknumbers.

Always get track durations from disc.  That way, we can still use track
titles from MusicBrainz even when durations are missing (which happens at
least with CDStubs).
"""

import sys
import logging
from collections import defaultdict
from dataclasses import dataclass

import musicbrainzngs as mb

from .utilities import debug

# discid search of Musicbrainz from URL:
# http://musicbrainz.org/ws/2/discid/3WCY2gFYwCfQkaSTzJFuIkzGOFc-?inc=recordings+artists+work-rels
# mbid search of Musicbrainz from URL:
# http://musicbrainz.org/ws/2/release/64b6dd30-f963-41e8-9607-401b18d7cd33?inc=recording-level-rels+recordings+work-rels+work-level-rels+artist-rels+artists+discids
# Display of Musicbrainz metadata here using pprint:
# pprint(<object>, indent=0, depth=[4-7])

# I am not interested in the INFO logging messages from musicbrainzngs.
logging.getLogger("musicbrainzngs").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

mb.set_useragent('wax', '1.0', 'http://3beez.com')

class MusicBrainzError(Exception):
    pass

@dataclass
class Track:
    title: str
    duration: float

    def __repr__(self):
        return f'Track({self.title}, {self.duration:.2f})'

class MBQuery:
    def __init__(self, disc):
        self.warnings = []

        if disc:
            self.do_query(disc)

    def __getitem__(self, item):
        return self.metadata.get(item, [''])

    @classmethod
    def do_discid_query(cls, disc_id):
        """Just get cover art for the recording with the given disc_id. We
        do the discid_search to get the mbid and asin for the recording,
        which is all we need to search for cover art."""
        mbquery = cls(None)
        mbquery.disc_id = disc_id
        mbquery.release, medium = mbquery.discid_search(disc_id,
                need_asin=True)
        return mbquery

    def do_query(self, disc):
        self.disc_id = disc_id = disc.id
        self.release, medium = self.discid_search(disc_id, need_asin=False)
        self.mbid_search(disc_id, medium, disc.tracks, self.release['id'])

    def discid_search(self, disc_id, need_asin):
        """Search by discid first to get the mbid."""
        includes = ['recordings', 'artist-rels']
        try:
            search_result = mb.get_releases_by_discid(disc_id,
                    includes=includes)
        except mb.WebServiceError as e:
            # Catches NetworkError, ResponseError, and AuthenticationError.
            raise MusicBrainzError(e)
        if not search_result:
            raise MusicBrainzError('Search by disc ID failed')

        if 'disc' not in search_result:
            raise MusicBrainzError('Search by disc ID has no disc')
        disc = search_result['disc']

        return self._get_release(disc, disc_id, need_asin)

    def mbid_search(self, disc_id, medium, disc_tracks, mbid):
        """Search by mbid to get all the metadata we seek."""
        includes = ['recording-level-rels', 'recordings', 'work-rels',
                'work-level-rels', 'artist-rels', 'artists', 'discids']
        try:
            search_result = mb.get_release_by_id(mbid, includes=includes)
        except mb.WebServiceError as e:
            # Catches NetworkError, ResponseError, and AuthenticationError.
            raise MusicBrainzError(e)
        if not search_result:
            raise MusicBrainzError('Search by MusicBrainz ID failed')

        if 'release' not in search_result:
            raise MusicBrainzError('Search by MusicBrainz ID has no release')
        release = search_result['release']

        artist_list = self._get_artist_list(release)
        if release['medium-count'] == 1:
            # Use the medium we got from discid_search because we found
            # it by searching through the mediums to find the one that
            # corresponds to our disc_id. Otherwise, use the one medium
            # associated with this release.
            medium = self._get_medium(disc_id, release)
        else:
            message = f'Found CD in set with {release["medium-count"]} discs'
            self.warnings.append(message)
            # Otherwise, get medium from the result of the second search.
        track_list = self._get_track_list(medium, disc_tracks)
        worklines, tracknumbers = self._get_involved_people(track_list)

        metadata = {k: list(v) for k, v in worklines.items()}
        for key, val in metadata.items():
            val.sort(key=lambda v: tracknumbers[(key, v)])
        self.tracknumbers = tracknumbers

        tracks = []
        for track, disc_track in zip(track_list, disc_tracks):
            recording = track['recording']
            trackSectors = disc_track.sectors
            trk = Track(recording['title'], trackSectors / 75.0)
            tracks.append(trk)
        self.tracks = tracks

        metadata['artist'] = artist_list
        for key in ('date', 'asin', 'album'):
            if key in release:
                metadata[key] = [release[key]]
        metadata['album'] = [release['title']]
        metadata['n_tracks'] = len(track_list)
        self.metadata = metadata

    def _get_release(self, disc, disc_id, need_asin):
        if 'release-list' not in disc:
            raise MusicBrainzError('Disc has no release-list')
        release_list = disc['release-list']

        # Find the release with the shortest medium-list that contains a
        # medium with the right discid.
        medium_list_sort = []
        for i, release in enumerate(release_list):
            medium_list = release.get('medium-list')
            medium_count = release.get('medium-count', sys.maxsize)
            medium_list_sort.append((i, release, medium_list, medium_count))
        medium_list_sort.sort(key=lambda e: e[3])

        def get_medium(disc_id):
            for i, release, medium_list, medium_count in medium_list_sort:
                for medium in medium_list:
                    if medium.get('format') in ('CD', 'Hybrid SACD'):
                        for disc in medium.get('disc-list', []):
                            if need_asin:
                                if disc.get('id') == disc_id \
                                        and 'asin' in release:
                                    return i, release, medium
                            else:
                                if disc.get('id') == disc_id:
                                    return i, release, medium
            return None, None, None
        medium_list_index, release, medium = get_medium(disc_id)
        release_list_len = len(release_list)
        if medium_list_index is None:
            plural = ('', 's')[release_list_len > 1]
            raise MusicBrainzError(f'No CD (or SACD) found in '
                f'{release_list_len} release{plural}')
        if release_list_len > 1:
            self.warnings.append(f'There are {release_list_len} releases. '
                    f'Using release {medium_list_index}')

        return release, medium

    def _get_artist_list(self, release):
        artist_list = []
        if 'artist-credit' not in release:
            self.warnings.append('No artist-credit list in release')
            return []
        for artist_credit in release['artist-credit']:
            # The list includes strings for punctuation. Only the
            # dictionaries contain useful information.
            if isinstance(artist_credit, dict):
                # The name that appears in the artist dict seems always to
                # be complete whereas the name that appears in name might
                # be just the last name -- and the key might not be there
                # at all. However, the name in artist also might be in
                # the original language (e.g., Russian).
                name = artist_credit.get('name', '')
                try:
                    artist_name = artist_credit['artist']['name']
                except KeyError:
                    pass
                else:
                    # Use name unless all characters are unicode (in
                    # which case it likely uses a different alphabet
                    # (e.g., Cyrillic).
                    if any(ord(c) < 128 and c != ' '
                            for c in artist_name):
                        name = artist_name
                # If there is only one name in name, try sort-name.
                if not name or len(name.split()) == 1:
                    try:
                        artist_name = artist_credit['artist']['sort-name']
                    except KeyError:
                        pass
                    else:
                        # sort-name is probably formatted last, first
                        # middle.
                        if ',' in artist_name:
                            name_s = artist_name.split(', ', 1)
                            name = ' '.join(reversed(name_s))
                if name:
                    artist_list.append(name)
        return artist_list

    def _get_medium(self, disc_id, release):
        # Find a medium in medium_list with the right disc_id.
        if 'medium-list' not in release:
            raise MusicBrainzError('Did not find medium-list in release')
        # I expect to find one medium, but it is in a list.
        if release['medium-count'] > 1:
            self.warnings.append('Found multiple mediums where one expected')
        for medium in release['medium-list']:
            for disc in medium['disc-list']:
                if disc['id'] == disc_id:
                    return medium
        raise MusicBrainzError('Did not find discid in any medium')

    def _get_track_list(self, medium, disc_tracks):
        if 'track-list' not in medium:
            return []
        track_list = medium['track-list']
        if len(track_list) != len(disc_tracks):
            self.warnings.append(f'Number of tracks in Musicbrainz '
                    f'({len(track_list)}) different from number on '
                    f'disc ({len(disc_tracks)})')
        return track_list

    def _get_involved_people(self, track_list):
        tracknumbers = defaultdict(list)
        worklines = defaultdict(set)
        for track in track_list:
            track_no = int(track['position'])
            tracknumbers[('tracks', track_no)].append(track_no)
            try:
                artist_relation_list = \
                        track['recording']['artist-relation-list']
            except KeyError:
                return {}, {}
            for artist_relation in artist_relation_list:
                try:
                    name = artist_relation['artist']['name']
                except KeyError:
                    continue
                if not any(ord(c) < 128 and c != ' '
                        for c in name):
                    continue
                role = artist_relation.get('type')
                if role:
                    val = f'{name} ({role})'
                else:
                    val = name
                key = 'involved_people_list'
                worklines[key].add(val)
                if track_no not in tracknumbers[(key, val)]:
                    tracknumbers[(key, val)].append(track_no)
        return worklines, tracknumbers

