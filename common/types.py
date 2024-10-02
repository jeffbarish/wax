from typing import NamedTuple

# RecordingTuple.tracks is the list of all tracks on the CD.
# Note that all values in props are str, but they are embedded in a tuple
class RecordingTuple(NamedTuple):
    works: object       # {0: WorkTuple, ...}
    tracks: object      # [TrackTuple, ...]
    props: object       # [(str, (str, ...)), ...] (key, values)
    discids: object     # [str, ...]
    uuid: str

# WorkTuple.track_ids is the list of all track_ids in the work.
# Each (str, ...) is a namegroup. An empty namegroup is ('',).
class WorkTuple(NamedTuple):
    genre: str
    metadata: object    # [(str, ...), (str, ...), ...] (just values)
    nonce: object       # [(str, (str, ...)), ...] (key, values)
    props: object       # [(str, (str, ...)), ...] (key, values)
    track_ids: object   # [(track_id1), ...]
    trackgroups: object # [(str, [(disc_num, track_num), ...],
                        #     [(str, (str, str, ...)), ...]), ...]

class TrackTuple(NamedTuple):
    disc_num: int
    track_num: int
    title: str
    duration: float = 0.0
    metadata: object = [] # [(str, [str])]

    @property
    def track_id(self):
        return (self.disc_num, self.track_num)

    @classmethod
    def _convert(cls, grouptuple):
        return cls(-1, -1, grouptuple.title, 0.0, grouptuple.metadata)

    def is_group(self):
        return (self.disc_num, self.track_num) == (-1, -1)

    def __str__(self):
        return f'{self.disc_num} {self.track_num:02d}'

    def __eq__(self, other):
        return self.track_id == other.track_id

class GroupTuple(NamedTuple):
    title: str
    metadata: list = [] # [(str, (str, str)), ...]

class DragCargo(NamedTuple):
    genre: str
    metadata: object    # [(str, [str])]
    tracks: object      # [(trackpath, TrackTuple)]
    group_map: object   # {(disc_num, track_num): GroupTuple}
    props: object       # [(str, (str, ...)), ...] (key, values)
    uuid: str
    work_num: int

# Wrap a treemodel in a class with a __getitem__ to return a row wrapped
# in a class that knows about field names. The wrapped row has __getattr__
# and __setattr__ to convert named attributes to the appropriate numeric
# index into the row. I use a NamedTuple to specify the fields because
# it provides self-documentation of the fields. Also, I use the NamedTuple
# by itself in situations where I only read from the model.
class ModelWithAttrs:
    def __init__(self, model, row_tuple):
        self.model = model
        self.row_tuple = row_tuple

    def __getattr__(self, attr):
        return getattr(self.model, attr)

    def __getitem__(self, index):
        row = self.model[index]
        return ModelRowWithAttrs(self.row_tuple, row)

    def __iter__(self):
        return (ModelRowWithAttrs(self.row_tuple, row) for row in self.model)

    def __len__(self):
        return len(self.model)

    def row_has_child(self, row):
        return self.model.iter_has_child(row.iter)

class ModelRowWithAttrs:
    def __init__(self, row_tuple, row):
        self.__dict__['row'] = row
        self.__dict__['row_tuple'] = row_tuple._make(row)
        self.__dict__['fields'] = row_tuple._fields

    def __iter__(self):
        return iter(self.__dict__['row_tuple'])

    def __getattr__(self, attr):
        # Look first in the row_tuple for attr and then in the row (e.g.,
        # for iter or path).
        try:
            return getattr(self.row_tuple, attr)
        except AttributeError:
            try:
                return getattr(self.row, attr)
            except AttributeError:
                message = f'{type(self).__name__} ' \
                    f'(based on {type(self.row_tuple).__name__}) ' \
                    f'has no attribute \'{attr}\''
                raise AttributeError(message) from None

    def __setattr__(self, attr, value):
        self.__dict__['row_tuple'] = self.row_tuple._replace(**{attr: value})

        index = self.fields.index(attr)
        self.row[index] = value

    def __repr__(self):
        return repr(self.row_tuple)

    def iterchildren(self):
        return (ModelRowWithAttrs(self.row_tuple, row)
                for row in self.row.iterchildren())

