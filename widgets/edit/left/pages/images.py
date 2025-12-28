"""A form for acquiring cover art images."""

import re
from contextlib import chdir
from enum import Enum
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, Gio, GdkPixbuf, GLib
from gi.repository.GdkPixbuf import PixbufLoader

from common.connector import register_connect_request
from common.connector import getattr_from_obj_with_name
from common.constants import IMAGES, IMAGES_DIR
from common.constants import BORDER, THUMBNAIL_SIZE
from common.constants import EXPAND
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.descriptors import QuietProperty
from common.initlogging import logger
from common.musicbrainz import MBQuery, MusicBrainzError
from common.utilities import debug
from ripper import ripper
from widgets import options_button
from widgets.messagelabel import MessageLabel
from worker import worker

class Provenance(Enum):
    FILE = 0
    PASTE = -1
    AMAZON = -2
    CAA = -3
    SAVED = -4
    EMBEDDED = -5

    @staticmethod
    def get_label(p):
        if not isinstance(p, Provenance):
            p = Provenance(p)
        return p.name.lower()

# It is a shame that Gdk.Rectangle does not provide a method for
# instantiating a rectangle with specific values for its attributes.
class Rectangle(Gdk.Rectangle):
    def __init__(self, x=-1, y=-1, width=1, height=1):
        super().__init__()
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def __eq__(self, other):
        return self.equal(other)

# NULL_RECTANGLE corresponds to the rectangle of an unallocated widget.
NULL_RECTANGLE = Rectangle()

@Gtk.Template.from_file('data/glade/edit/left/image.glade')
class ImagesEditor(Gtk.Box):
    __gtype_name__ = 'edit_images_box'

    _images_changed = QuietProperty(type=bool, default=False)

    thumbnail_treeview = Gtk.Template.Child()
    thumbnail_treeselection = Gtk.Template.Child()

    image_delete_button = Gtk.Template.Child()
    image_download_button = Gtk.Template.Child()
    image_provenance_label = Gtk.Template.Child()
    image_buttons_box = Gtk.Template.Child()

    images_liststore = Gtk.Template.Child()
    image_box = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('edit-images-page')
        self.tab_text = 'Images'
        self.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.props.margin = 2
        self.props.margin_left = 3
        self.props.margin_top = 3
        self.set_spacing(2)

        self.message_label = message_label = MessageLabel()
        self.image_buttons_box.pack_start(message_label, *EXPAND)
        message_label.show_all()

        self.image = image = Image()
        self.image_box.pack_start(image, False, True, 0)

        self.cancellable = Gio.Cancellable.new()

        register_connect_request('save-button', 'save-button-clicked',
                self.on_save_button_clicked)
        register_connect_request('edit-ripcd.abort_button', 'clicked',
                self.on_abort_button_clicked)
        register_connect_request('edit-ripcd', 'rip-create-clicked',
                self.on_rip_create_clicked)
        register_connect_request('edit-importfiles', 'import-create-clicked',
                self.on_import_create_clicked)
        register_connect_request('ripper', 'rip-started',
                self.on_rip_started)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)
        options_button.connect_menuitem('Edit', 'Delete',
                self.on_options_edit_delete_activate)

        self.uuid = None

    def queue_images_changed_message(self):
        edit_message_label = getattr_from_obj_with_name('edit-message-label')
        edit_message_label.queue_message('images changed')

    def on_save_button_clicked(self, button, label):
        self._images_changed = False

    def on_rip_create_clicked(self, button):
        self.cancellable.reset()

    def on_import_create_clicked(self, importfiles):
        self.cancellable.cancel()

    def on_options_edit_clear_activate(self, menuitem):
        self.cancellable.cancel()
        self._images_changed = False

    def on_options_edit_delete_activate(self, menuitem):
        self.cancellable.cancel()

    def on_rip_started(self, ripper, uuid, disc_num):
        self.uuid = uuid

    def on_abort_button_clicked(self, button):
        self.cancellable.cancel()

        if ripper.disc_num == 0:
            if not ripper.rerip:
                self.clear()
        else:
            # Remove the images in images_liststore corresponding to disc
            # disc_num. Note that images_liststore has a meaningful disc_num
            # only when first creating a recording. If we are revising an
            # existing recording, disc_num is -1 for all images. In that
            # case, it is no longer possible to remove existing images
            # associated with a particular disc.
            for row in reversed(self.images_liststore):
                if row[4] >= ripper.disc_num:
                    self.images_liststore.remove(row.iter)

            # Select the last row if no row is selected.
            model, treeiter = self.thumbnail_treeselection.get_selected()
            if treeiter is None and len(self.images_liststore) > 0:
                last_row = self.images_liststore[-1]
                self.thumbnail_treeselection.select_iter(last_row.iter)
                self.thumbnail_treeview.scroll_to_cell(last_row.path, None,
                        False, 0.0, 0.0)

    @Gtk.Template.Callback()
    def on_thumbnail_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is not None:
            image_pb = self.images_liststore[treeiter][0]
            self.image.display_pb(image_pb)
            p = self.images_liststore[treeiter][2]
            text = Provenance.get_label(p)
            self.image_provenance_label.set_text(text)
            self.image_delete_button.set_sensitive(True)
        else:
            self.image_provenance_label.set_text('')
            self.image_delete_button.set_sensitive(False)

    @Gtk.Template.Callback()
    def on_image_delete_button_clicked(self, selection):
        if len(self.images_liststore) == 1:
            del self.images_liststore[0]
            self.image.display_pb(None)
            self.image_delete_button.set_sensitive(False)
            return

        model, treeiter = selection.get_selected()
        del_i = self.images_liststore[treeiter][3]
        self.images_liststore.remove(treeiter)

        # Display the image that replaced the one just deleted or the last
        # image if we just deleted the last image.
        display_i = min(len(self.images_liststore) - 1, del_i)
        self.image.display_pb(self.images_liststore[display_i][0])

        if len(self.images_liststore) == 1:
            self.thumbnail_treeview.hide()
            return

        # Decrement i for any row with i > del_i.
        for row in self.images_liststore:
            if row[3] > del_i:
                self.images_liststore.set_value(row.iter, 3, row[3] - 1)

        # Sometimes the selection does not move up one after deleting the
        # last row, so set the selection explicitly in that case.
        if len(self.images_liststore) > 1:
            model, treeiter = self.thumbnail_treeselection.get_selected()
            if treeiter is None:
                last_row = self.images_liststore[-1]
                self.thumbnail_treeselection.select_iter(last_row.iter)

        self._images_changed = True

    @Gtk.Template.Callback()
    @emission_stopper('row-deleted')
    def on_images_liststore_row_deleted(self, model, path):
        self._images_changed = True
        self.queue_images_changed_message()

    @Gtk.Template.Callback()
    def on_images_liststore_row_changed(self, model, path, treeiter):
        if path[0] == 0:
            image_pb = self.images_liststore[0][0]
            self.image.display_pb(image_pb)

    @Gtk.Template.Callback()
    def on_image_paste_button_clicked(self, button):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        pb = clipboard.wait_for_image()
        if pb is not None:
            self.append_image(pb, Provenance.PASTE)
            self._images_changed = True

    @Gtk.Template.Callback()
    def on_image_download_button_clicked(self, button):
        # The existing mbquery corresponds to the last disc ripped. To refresh
        # all the images in a multi-CD set, we need to iterate through
        # recording.discids, just as we do for an existing recording.
        self.cancellable.reset()
        recording = getattr_from_obj_with_name('edit-left-notebook.recording')
        for disc_num, discid in enumerate(recording.discids):
            try:
                mbquery = MBQuery.do_image_query(discid)
            except MusicBrainzError:
                message = 'MusicBrainz: disc not found'
                self.message_label.queue_message(message,
                        self.image_provenance_label.hide,
                        self.image_provenance_label.show)
                return
            self.get_images(mbquery, disc_num)

    def populate(self, uuid):
        self.uuid = uuid

        with stop_emission(self.images_liststore, 'row-deleted'):
            self.images_liststore.clear()

        # Collect all image and thumbnail files.
        pb_iter_pair = []
        for image_class in ('image', 'thumbnail'):
            images_dir = Path(IMAGES, uuid)
            pattern = f'{image_class}-??.jpg'
            files_iter = map(str, images_dir.glob(pattern))
            pb_iter = map(GdkPixbuf.Pixbuf.new_from_file, sorted(files_iter))
            pb_iter_pair.append(pb_iter)

        # pb_iter_pair contains two iterators, one for 'image' and one for
        # 'thumbnail'. The zip pairs an image with a thumbnail in a tuple.
        for i, pb_pair in enumerate(zip(*pb_iter_pair)):
            row = (*pb_pair, Provenance.SAVED.value, i, -1)
            self.images_liststore.append(row)

        # Display the first image.
        self._display_first_image()

        if len(self.images_liststore):
            self.image_delete_button.set_sensitive(True)

    def _display_first_image(self):
        if not len(self.images_liststore):
            self.image.display_pb(None)
            return

        pb, pb_scaled, prov_value, _, _ = self.images_liststore[0]
        self.image.display_pb(pb)
        self.image_provenance_label.set_text(Provenance.get_label(prov_value))

        visible = (len(self.images_liststore) > 1)
        self.thumbnail_treeview.props.visible = visible
        self.image_download_button.set_sensitive(True)

    def write_images(self, uuid):
        # Some images might have been deleted from images_liststore
        # after the recording was saved, so delete all existing image
        # files and save the ones in images_liststore that survive.
        with chdir(Path(IMAGES, uuid)):
            for file_path in Path('.').iterdir():
                file_path.unlink()

            for row_index, row in enumerate(self.images_liststore):
                for i, size in enumerate(('image', 'thumbnail')):
                    new_path = Path(f'{size}-{row_index:02d}.jpg')
                    row[i].savev(str(new_path), 'jpeg', [], [])

    def append_images(self, images):
        for image_data, image_type in images:
            pb = self._load_pixbuf(image_data)
            width = height = 74
            pb_scaled = pb.scale_simple(width, height,
                    GdkPixbuf.InterpType.BILINEAR)
            provenance = (Provenance.EMBEDDED, Provenance.FILE)[image_type < 0]
            row = (pb, pb_scaled, provenance.value, 0, -1)
            self.images_liststore.append(row)
        if not self.thumbnail_treeview.props.visible:
            self._display_first_image()
        self._images_changed = True
        self.queue_images_changed_message()

        self.thumbnail_treeselection.select_path('0')
        self.image_delete_button.set_sensitive(True)

    def _load_pixbuf(self, data):
        pb_loader = PixbufLoader.new()
        pb_loader.write(data)
        pb_loader.close()
        return pb_loader.get_pixbuf()

    def append_image(self, pb, provenance, disc_num=-1):
        thumbnail = pb.scale_simple(*THUMBNAIL_SIZE,
                GdkPixbuf.InterpType.BILINEAR)
        i = len(self.images_liststore)
        row = (pb, thumbnail, provenance.value, i, disc_num)
        treeiter = self.images_liststore.append(row)
        if len(self.images_liststore) > 1:
            self.thumbnail_treeview.show()

        self._images_changed = True
        self.queue_images_changed_message()

        self.thumbnail_treeselection.select_iter(treeiter)
        treepath = self.images_liststore.get_path(treeiter)
        self.thumbnail_treeview.scroll_to_cell(treepath, None, False, 0.0, 0.0)

    def get_images(self, mbquery, disc_num):
        if self.cancellable.is_cancelled():
            return

        try:
            self._get_amazon_image(mbquery, disc_num)
        except Exception:
            message = 'Amazon: error getting image'
            self.message_label.queue_message(message,
                    self.image_provenance_label.hide,
                    self.image_provenance_label.show)

        # This function takes a while to run.
        def get_caa_image_urls(mbid, disc_num):
            import musicbrainzngs as mb
            image_list = mb.get_image_list(mbid)
            caa_image_urls = [image['image'] for image in image_list['images']]
            return (caa_image_urls, disc_num)

        # Any click of create_button sets cancellable. If the click occurred
        # after initiating readcd, do not proceed. If the second click
        # occurred after requesting caa images urls, the subsequent
        # asynchronous requests for images will be cancelled.
        if not self.cancellable.is_cancelled():
            worker.do_in_subprocess(
                    get_caa_image_urls,
                    self._get_caa_image_urls_cb,
                    mbquery.release['id'],
                    disc_num)

    def _get_amazon_image(self, mbquery, disc_num):
        if 'asin' in mbquery.release:
            url_format = 'http://ec1.images-amazon.com/images/P/' \
                '{}.01.LZZZZZZZ.jpg'
            amazon_image_url = url_format.format(mbquery.release['asin'])
            image_file = Gio.File.new_for_uri(amazon_image_url)
            image_file_input_stream = image_file.read()
            GdkPixbuf.Pixbuf.new_from_stream_async(image_file_input_stream,
                    self.cancellable, self._get_image_cb,
                    Provenance.AMAZON, disc_num)

    def _get_caa_image_urls_cb(self, success, result):
        if not success:
            logger.error(f'CAA access failed with message:\n\n{result}')
            if 'Error 404' in result:
                message = 'CAA: image not found'
            else:
                message = re.sub(r'^.*caused by:\s*', '', result)
                message = message.replace('\n', '/')
            self.message_label.queue_message(message,
                    self.image_provenance_label.hide,
                    self.image_provenance_label.show)
            return

        caa_image_urls, disc_num = result

        for caa_image_url in caa_image_urls:
            image_file = Gio.File.new_for_uri(caa_image_url)
            image_file.read_async(GLib.PRIORITY_DEFAULT,
                    self.cancellable,
                    self._caa_read_async_cb, disc_num)

    def _caa_read_async_cb(self, image_file, result, disc_num):
        try:
            image_file_input_stream = image_file.read_finish(result)
        except GLib.Error:
            return
        GdkPixbuf.Pixbuf.new_from_stream_async(image_file_input_stream,
                self.cancellable, self._get_image_cb, Provenance.CAA, disc_num)

    # called for amazon or caa images.
    def _get_image_cb(self, image_file, result, source, disc_num):
        try:
            pb = GdkPixbuf.Pixbuf.new_from_stream_finish(result)
        except GLib.Error:
            return
        self.append_image(pb, source, disc_num)

    # Clear all images.
    def clear(self):
        self.thumbnail_treeview.hide()
        with stop_emission(self.images_liststore, 'row-deleted'):
            self.images_liststore.clear()
        self.image.display_pb(None)

        self.image_provenance_label.set_text('')

        self.image_delete_button.set_sensitive(False)
        self.image_download_button.set_sensitive(False)

        self._images_changed = False

# Subclass Gtk.Image so that I can override do_get_preferred_width and
# do_get_preferred_height.
class Image(Gtk.Image):
    def __init__(self):
        super().__init__()
        self.set_vexpand(True)
        self.min_nat_size = (300, 300)
        self.show()

        path = Path(IMAGES_DIR, 'noimage.jpg')
        self.pb = self.no_image_pb = GdkPixbuf.Pixbuf.new_from_file(str(path))

    # These two overrides allow the image to shrink. It does not matter
    # what values I put here as long as they are smaller than the smallest
    # the image needs to be.
    def do_get_preferred_width(self):
        return self.min_nat_size

    def do_get_preferred_height(self):
        return self.min_nat_size

    def scale_at_size(self, pb, image_width, image_height):
        # Given width and height of the Gtk.Image, scale pb to fit
        # preserving the aspect ratio.
        allocation = self.get_allocation()
        if allocation == NULL_RECTANGLE:
            return

        # Leave a border.
        image_width -= BORDER
        image_height -= BORDER

        # First fit by width. If the resulting height does not fit, then
        # fit by height.
        ratio = pb.props.height / pb.props.width
        scaled_width = image_width
        scaled_height = image_width * ratio
        if scaled_height > image_height:
            scaled_height = image_height
            scaled_width = image_height // ratio

        return pb.scale_simple(scaled_width, scaled_height,
                GdkPixbuf.InterpType.BILINEAR)

    def do_size_allocate(self, allocation):
        Gtk.Image.do_size_allocate(self, allocation)

        width, height = (allocation.width, allocation.height)
        self.set_from_pixbuf(self.scale_at_size(self.pb, width, height))

    def display_pb(self, pb):
        allocation = self.get_allocation()
        width, height = (allocation.width, allocation.height)

        if isinstance(pb, GdkPixbuf.Pixbuf):
            self.pb = pb
        elif pb is None:
            self.pb = self.no_image_pb
        self.set_from_pixbuf(self.scale_at_size(self.pb, width, height))


page_widget = ImagesEditor()

