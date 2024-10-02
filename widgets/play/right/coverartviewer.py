"""Display cover art."""

import os
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from gi.repository import GdkPixbuf

from common.config import config
from common.connector import register_connect_request
from common.constants import IMAGES, IMAGES_DIR
from common.utilities import debug

WIDTH = config.geometry['right_panel_width']

class CoverArtViewer(Gtk.EventBox):
    def __init__(self):
        super().__init__()
        self.set_name('coverart-viewer')
        self.set_vexpand(True)
        self.set_size_request(341, -1)
        self.image = Gtk.Image.new()
        self.add(self.image)
        self.show_all()

        register_connect_request('selector.recording_selection', 'changed',
                self.on_recording_selection_changed)
        register_connect_request('edit-left-notebook', 'recording-saved',
                self.on_recording_saved)

        self.connect('button-press-event', self.on_button_press_event)

    def on_recording_saved(self, editnotebook, genre):
        uuid = editnotebook.recording.uuid
        self.get_images(uuid)

    def on_recording_selection_changed(self, recording_selection):
        model_filter, selected_row_iter = \
                recording_selection.get_selected()
        if selected_row_iter is None:
            return

        recording_model = model_filter.props.child_model
        selected_row_iter = recording_model.convert_iter_to_child_iter(
                selected_row_iter)

        short, uuid, work_num = recording_model[selected_row_iter]
        self.get_images(uuid)

    def get_images(self, uuid):
        images_path = Path(IMAGES, uuid)
        file_paths = list(map(str, images_path.glob('image-??.jpg')))
        file_paths.sort()
        if not file_paths:
            file_paths = [str(Path(IMAGES_DIR, 'noimage.png'))]

        pixbufs = map(GdkPixbuf.Pixbuf.new_from_file, file_paths)
        self.scaled_pixbufs = list(map(self.scale_image, pixbufs))

        if len(self.scaled_pixbufs) > 1:
            list(map(self.composite_arrows, self.scaled_pixbufs))

        self.image.set_from_pixbuf(self.scaled_pixbufs[0])

    def on_button_press_event(self, coverartviewer, eventbutton):
        n_images = len(self.scaled_pixbufs)
        if n_images <= 1:
            return

        if eventbutton.type == Gdk.EventType.BUTTON_PRESS \
                and eventbutton.state == 0 \
                and eventbutton.button == 1:
            if eventbutton.x > 0.8 * WIDTH:
                self.scaled_pixbufs.append(self.scaled_pixbufs.pop(0))
            elif eventbutton.x < 0.2 * WIDTH:
                self.scaled_pixbufs.insert(0, self.scaled_pixbufs.pop())
            self.image.set_from_pixbuf(self.scaled_pixbufs[0])

    def scale_image(self, pb):
        # Hardwire image size as self might not be allocated the first time
        # we come here. Adjust these values if the layout of the right
        # panel changes.
        image_width = WIDTH - 9
        image_height = image_width - 14

        # Scale pb to fit image (self) preserving the aspect ratio of the
        # original image. Scale to the width and see whether the height fits.
        # If it does not, scale to the height.
        ratio = float(pb.props.height) / pb.props.width

        pb_width = image_width
        pb_height = round(pb_width * ratio)
        if pb_height > image_height:
            pb_height = image_height
            pb_width = round(pb_height / ratio)
        pb_scaled = pb.scale_simple(pb_width, pb_height,
                GdkPixbuf.InterpType.BILINEAR)
        return pb_scaled

    def composite_arrows(self, pb):
        images_dir = os.path.join('data', 'images')
        for arrow_fn, x_func in [
                ('arrow_l.png', lambda a: 3),
                ('arrow_r.png', lambda a: pb.props.width - a.props.width - 3)]:
            arrow_pb = GdkPixbuf.Pixbuf.new_from_file(
                    os.path.join(images_dir, arrow_fn))
            x = x_func(arrow_pb)
            y = round((pb.props.height - arrow_pb.props.height) / 2.0)
            arrow_pb.composite(pb, x, y,
                    arrow_pb.props.width, arrow_pb.props.height,
                    x, y, 1.0, 1.0, GdkPixbuf.InterpType.BILINEAR, 0xaf)

