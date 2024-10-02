"""Wrap the config pickle file to provide options for accessing the genre
data."""

from .config import config
from .utilities import debug

class GenreSpec():
    def __iter__(self):
        return iter(config.genre_spec)

    def all_keys(self, genre: str) -> list:
        # Return the sum of keys for primary and secondary.
        return sum(config.genre_spec[genre].values(), start=[])

    # Because config is a shelf, I need to assign something to it to effect
    # a change. Pull genre_spec out of config, make the desired change to it,
    # then assign genre_spec back to the shelf.
    def rename_genre(self, old_genre: str, new_genre: str):
        genre_spec = config.genre_spec
        genre_spec = {(genre if genre != old_genre else new_genre): spec
                for genre, spec in config.genre_spec.items()}
        config.genre_spec = genre_spec

    def reorder_genres(self, new_order: list):
        genre_spec = config.genre_spec
        genre_spec = {key: config.genre_spec[key] for key in new_order}
        config.genre_spec = genre_spec

    def add_genre(self, new_genre, primary_key):
        genre_spec = config.genre_spec
        genre_spec[new_genre] = {'primary': [primary_key],
                'secondary': []}
        config.genre_spec = genre_spec

    def delete_genre(self, old_genre: str):
        genre_spec = config.genre_spec
        del genre_spec[old_genre]
        config.genre_spec = genre_spec

    def update_keys(self, genre: str, metadata_class: str, keys: list):
        genre_spec = config.genre_spec
        genre_spec[genre][metadata_class] = keys
        config.genre_spec = genre_spec

    def demote_key(self, genre, key, index):
        genre_spec = config.genre_spec
        genre_spec[genre]['primary'].remove(key)
        genre_spec[genre]['secondary'].insert(index, key)
        config.genre_spec = genre_spec

    def promote_key(self, genre, key, index):
        genre_spec = config.genre_spec
        genre_spec[genre]['secondary'].remove(key)
        genre_spec[genre]['primary'].insert(index, key)
        config.genre_spec = genre_spec


genre_spec = GenreSpec()

