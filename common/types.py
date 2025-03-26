from typing import NamedTuple, Self, Any, get_origin, Generator

type TrackID = tuple[int, int]

type Name_LongShort = tuple[str, str]  # ('long', 'short')

type NameGroup = tuple[str, ...]  # could be only 1 str
type MetadataItem = tuple[str, NameGroup]

type NameGroup_LongShort = list[Name_LongShort]
type MetadataItem_LongShort = tuple[str, NameGroup_LongShort]

# There are three places where I use the types of attributes of my classes
# to create a ListStore or a TreeStore (RecordingModel, TrackModel, and
# playqueue_model). I use __annotations__ to obtain the types, but typing
# also uses __annotations__. Accordingly, any type hints in __annotations__
# must be converted to an actual type. get_origin returns an unsubscripted
# version of the type (e.g., for list[tuple[str, NameGroup]] it returns
# list). However, Gtk requires a GObject.GType (which list is not). For those
# types, we need to specify 'object'. When the type of a column is a numeric
# or string type, get_origin returns None. For those types, we bypass
# get_origin and use the actual content of __annotations__.
def column_types(my_class):
    for t in my_class.__annotations__.values():
        yield t if get_origin(t) is None else object

class GroupTuple(NamedTuple):
    title:      str        # group title
    metadata:   list[MetadataItem] = []

class TrackTuple(NamedTuple):
    disc_num:   int
    track_num:  int
    title:      str
    duration:   float = 0.0
    metadata:   list[MetadataItem] = []

    @property
    def track_id(self) -> TrackID:
        return (self.disc_num, self.track_num)

    @classmethod
    def _convert(cls, grouptuple: GroupTuple) -> Self:
        return cls(-1, -1, grouptuple.title, 0.0, grouptuple.metadata)

    def is_group(self) -> bool:
        return (self.disc_num, self.track_num) == (-1, -1)

    def __str__(self) -> str:
        return f'{self.disc_num} {self.track_num:02d}'

    def __eq__(self, other) -> bool:
        return self.track_id == other.track_id

class WorkTuple(NamedTuple):
    genre:      str
    metadata:   list[NameGroup]     # just long values (no keys)
    nonce:      list[MetadataItem]
    props:      list[MetadataItem]
    track_ids:  list[TrackID]
    trackgroups: list[tuple[str, list[TrackID], list[MetadataItem]]]

# RecordingTuple.tracks is the list of all tracks on the CD.
# Note that all values in props are str, but they are embedded in a tuple
class RecordingTuple(NamedTuple):
    works:      dict[int, WorkTuple]
    tracks:     list[TrackTuple]
    props:      list[MetadataItem]
    discids:    list[str]
    uuid:       str

class DragCargo(NamedTuple):
    genre:      str
    metadata:   list[NameGroup]
    tracks:     list[TrackTuple]
    group_map:  dict[TrackID, GroupTuple]
    props:      list[MetadataItem]
    uuid:       str
    work_num:   int

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

    def __getattr__(self, attr) -> Any:
        return getattr(self.model, attr)

    def __getitem__(self, index) -> 'ModelRowWithAttrs':
        row = self.model[index]
        return ModelRowWithAttrs(self.row_tuple, row)

    def __iter__(self) -> Generator['ModelRowWithAttrs', None, None]:
        return (ModelRowWithAttrs(self.row_tuple, row) for row in self.model)

    def __len__(self) -> int:
        return len(self.model)

    def row_has_child(self, row) -> bool:
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

