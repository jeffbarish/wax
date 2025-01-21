"""These are the functions that extract tags from wax metadata.

Note that metadata is a dict in the form:
{'key1': (val1, val2, ...), 'key2': (val1, ...), ...}.

The keys of metadata_long are both primary and secondary (not nonce) and
the values are in their long form. metadata_short has keys for primary and
the values are in the their short form.
"""

from dataclasses import dataclass

# Functions for converting name groups (a tuple of multiple names) to a str.
def join_group(names):
    return '; '.join(names)

def first_in_group(names):
    return names[0]

# The generic mapping assumes a simple mapping from wax keys specified
# in the kwargs to the 2 tags 'album', 'artist'. Note that it is
# permissible for there to be no mapping to either of these tags.
def generic(**kwargs):
    def wrapper(cls):
        def __init__(self, metadata_long, metadata_short):
            self.metadata_long = metadata_long
            self.metadata_short = metadata_short

            self.tags = {(tag, join_group(metadata_long.get(wax_key, ('',))))
                    for tag, wax_key in kwargs.items()}

        def __call__(self, trackgroup_title, title):
            return title

        cls.__init__ = __init__
        cls.__call__ = __call__

        return cls
    return wrapper

@dataclass
class Main:
    metadata_long: dict
    metadata_short: dict

@dataclass
class Anthology(Main):
    def __post_init__(self):
        subgenre = first_in_group(self.metadata_long['subgenre'])

        self.tags = {
            'album': join_group(self.metadata_long['title']),
            'artist': first_in_group(self.metadata_long['composer']),
            'performer': join_group(self.metadata_long['artist']),
            'genre': f'Anthology ({subgenre})'
        }

    def __call__(self, trackgroup_title, title):
        if trackgroup_title:
            return f'{trackgroup_title}: {title}'
        else:
            return title

@dataclass
class Chamber(Main):
    def __post_init__(self):
        subgenre = first_in_group(self.metadata_long['subgenre'])

        self.tags = {
            'album': join_group(self.metadata_long['work']),
            'artist': first_in_group(self.metadata_long['composer']),
            'performer': join_group(self.metadata_long['artist']),
            'genre': f'Chamber ({subgenre})'}

    def __call__(self, trackgroup_title, title):
        if trackgroup_title:
            return f'{trackgroup_title}: {title}'
        else:
            return f'{first_in_group(self.metadata_short['work'])}: {title}'

@dataclass
class Concerto(Main):
    def __post_init__(self):
        soloist = join_group(self.metadata_long['soloist'])
        conductor = first_in_group(self.metadata_long['conductor'])
        performer = f'{soloist} ({conductor})'

        self.tags = {
            'album': join_group(self.metadata_long['work']),
            'artist': join_group(self.metadata_long['composer']),
            'performer': performer,
            'genre': 'Concerto'}

        self.work = first_in_group(self.metadata_short['work'])

    def __call__(self, trackgroup_title, title):
        return f'{self.work}: {title}'

@dataclass
class Opera(Main):
    def __post_init__(self):
        performer = first_in_group(self.metadata_long['conductor'])

        orchestra = first_in_group(self.metadata_long['orchestra'])
        if orchestra:
            performer += f' ({orchestra})'

        self.tags = {
            'album': join_group(self.metadata_long['work']),
            'artist': join_group(self.metadata_long['composer']),
            'performer': performer,
            'genre': 'Opera'}

        self.work = join_group(self.metadata_short['work'])

    def __call__(self, trackgroup_title, title):
        if trackgroup_title:
            return f'{self.work}: {trackgroup_title}: {title}'
        else:
            return f'{self.work}: {title}'

@dataclass
class Recital(Main):
    def __post_init__(self):
        subgenre = first_in_group(self.metadata_long['subgenre'])

        self.tags = {
            'album': join_group(self.metadata_long['title']),
            'artist': join_group(self.metadata_long['artist']),
            'genre': f'Recital ({subgenre})'}

    def __call__(self, trackgroup_title, title):
        if trackgroup_title:
            return f'{trackgroup_title}: {title}'
        else:
            return title

@dataclass
class Symphonic(Main):
    def __post_init__(self):
        performer = first_in_group(self.metadata_long['conductor'])
        orchestra = first_in_group(self.metadata_long['orchestra'])
        if orchestra:
            performer += f' ({orchestra})'

        subgenre = join_group(self.metadata_long['subgenre'])

        self.tags = {
            'album': join_group(self.metadata_long['work']),
            'artist': join_group(self.metadata_long['composer']),
            'performer': performer,
            'genre': f'Symphonic ({subgenre})'
        }

        self.work = first_in_group(self.metadata_short['work'])

    def __call__(self, trackgroup_title, title):
        if trackgroup_title:
            return f'{trackgroup_title}: {title}'
        else:
            return f'{self.work}: {title}'

@dataclass
class Pop(Main):
    def __post_init__(self):
        subgenre = first_in_group(self.metadata_long['subgenre'])

        self.tags = {
            'album': first_in_group(self.metadata_long['title']),
            'artist': join_group(self.metadata_long['group']),
            'genre': f'Pop ({subgenre})'
        }

    def __call__(self, trackgroup_title, title):
        return title

@generic(album='film', artist='composer')
class Film:
    pass

@generic(album='title', artist='ensemble')
class Jazz:
    pass

@generic(album='title', artist='composer')
class Show:
    pass

@generic(album='title', artist='soloists')
class Showtunes:
    pass

@generic(album='title', artist='comedian')
class Comedy:
    pass

@generic(album='album', artist='artist')
class Pristine:
    pass

@generic(album='title')
class Podcast:
    pass

@generic(album='title')
class Demo:
    pass

