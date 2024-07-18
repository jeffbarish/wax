"""This package assembles the widgets for selecting recordings."""

from widgets.genrebutton import GenreButton

genre_button = GenreButton()

# There is a second instance in work.editor, but we care about signals only
# from this instance so only this one gets a name.
genre_button.set_name('genre-button')


from .selector import Selector

page_widget = Selector()

