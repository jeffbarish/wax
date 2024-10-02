"""The config dict lives in memory (it is not big). It contains five keys,
'genre spec', 'column widths', 'filter config', 'random_config', 'user
props', and 'completers'. The value for all but 'user props' is a dict;
for the latter it is a list. The values can be accessed either as
config['genre spec'] or config.genre_spec. A write to either of those
triggers a write to disk of the pickle for the entire config dict. As
with shelve, updating a mutable within one of the dicts will not update
the pickle. To update the pickle, there must be a statement like
config.filter_config = val."""

import contextlib
import pickle
from copy import copy
from pprint import pformat

from .constants import CONFIG

class Config:
    def __init__(self):
        with open(CONFIG, 'rb') as config_fo:
            # Like self.config = pickle.load(config_fo).
            self.__dict__['config'] = pickle.load(config_fo)

    def __getattr__(self, attr):
        key = attr.replace('_', ' ')
        val = self.__dict__['config'].get(key, {})
        return val

    def __setattr__(self, attr, val):
        key = attr.replace('_', ' ')
        self.__dict__['config'][key] = val
        with open(CONFIG, 'wb') as config_fo:
            pickle.dump(self.__dict__['config'], config_fo)

    def __getitem__(self, key):
        val = self.__dict__['config'].get(key, {})
        return val

    def __setitem__(self, key, val):
        self.__dict__['config'][key] = val
        with open(CONFIG, 'wb') as config_fo:
            pickle.dump(self.__dict__['config'], config_fo)

    def __str__(self):
        return pformat(self.__dict__['config'])

    # Yield the mutable specification for key. After the main program modifies
    # the specification, write it back to config to trigger a write to disk.
    # Do nothing if the specification did not actually change.
    @staticmethod
    @contextlib.contextmanager
    def modify(key):
        from common.config import config
        spec_copy = copy(config[key])
        yield spec_copy
        if spec_copy != config[key]:
            config[key] = spec_copy

config = Config()
