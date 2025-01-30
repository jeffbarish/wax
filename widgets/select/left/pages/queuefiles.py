import pickle
import shelve
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from gi.repository.GdkPixbuf import PixbufLoader

from common.config import config
from common.constants import SOUND, IMAGES, IMAGES_DIR, QUEUEFILES, LONG
from common.types import GroupTuple
from common.utilities import debug
from common.utilities import make_time_str
from widgets.select.right import playqueue_model_with_attrs, PlayqueueModelRow
from widgets.select.right import select_right

@Gtk.Template.from_file('data/glade/select/queuefiles.glade')
class QueueFiles(Gtk.ScrolledWindow):
    __gtype_name__ = 'queuefiles_scrolledwindow'

    queuefiles_save_button = Gtk.Template.Child()
    queuefiles_delete_button = Gtk.Template.Child()
    queuefiles_load_button = Gtk.Template.Child()
    queuefiles_liststore = Gtk.Template.Child()
    queuefiles_treeview = Gtk.Template.Child()
    queuefiles_treeselection = Gtk.Template.Child()
    queuefiles_name_entry = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('queuefiles')
        self.tab_text = 'Queue files'

        playqueue_model_with_attrs.connect('row-inserted',
                self.on_playqueue_model_row_inserted)
        playqueue_model_with_attrs.connect('row-deleted',
                self.on_playqueue_model_row_deleted)

        # Initialize queuefiles_liststore with any queue files already
        # present.
        for fp in QUEUEFILES.iterdir():
            duration, n_works = self.get_stats(fp)
            self.queuefiles_liststore.append((fp.name, duration, n_works))

        # Sort the queue file names in alphabetic order.
        def sort_func(model, treeiter_a, treeiter_b, user_data):
            a, b = model[treeiter_a][0], model[treeiter_b][0]
            if a > b:
                return 1
            if a < b:
                return -1
            return 0
        self.queuefiles_liststore.set_default_sort_func(sort_func)
        self.queuefiles_liststore.set_sort_column_id(
                Gtk.TREE_SORTABLE_DEFAULT_SORT_COLUMN_ID,
                Gtk.SortType.ASCENDING)

    def on_playqueue_model_row_inserted(self, model, treepath, treeiter):
        text = self.queuefiles_name_entry.get_text()
        sensitive = text and len(model)
        self.queuefiles_save_button.set_sensitive(sensitive)

    def on_playqueue_model_row_deleted(self, model, treepath):
        text = self.queuefiles_name_entry.get_text()
        sensitive = text and len(model)
        self.queuefiles_save_button.set_sensitive(sensitive)

    @Gtk.Template.Callback()
    def on_queuefiles_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()

        sensitive = treeiter is not None
        self.queuefiles_delete_button.set_sensitive(sensitive)
        self.queuefiles_load_button.set_sensitive(sensitive)

    @Gtk.Template.Callback()
    def on_queuefiles_name_entry_changed(self, entry):
        text = entry.get_text()
        sensitive = text and bool(playqueue_model_with_attrs)
        self.queuefiles_save_button.set_sensitive(sensitive)
        if text:
            self.queuefiles_treeselection.unselect_all()

        sensitive = text and Path(QUEUEFILES, text).exists()
        self.queuefiles_load_button.set_sensitive(sensitive)

        # If text is in treeview, select the row.
        for row in self.queuefiles_liststore:
            if row[0] == text:
                self.queuefiles_treeselection.select_iter(row.iter)
                break
        else:
            self.queuefiles_delete_button.set_sensitive(False)

    @Gtk.Template.Callback()
    def on_queuefiles_save_button_clicked(self, button):
        text = self.queuefiles_name_entry.get_text()
        save_fp = Path(QUEUEFILES, text)

        with open(save_fp, 'wb') as queue_fo:
            for row in playqueue_model_with_attrs:
                pb, *metadata = row

                # pb has image data reconstructed from a jpeg. Re-encoding that
                # data to jpeg format (using Pixbuf.savev) further degrades the
                # image. Instead, read the original jpeg data from the file
                # whence it came.
                thumbnail_fn = Path(IMAGES, row.uuid, 'thumbnail-00.jpg')
                if not thumbnail_fn.exists():
                    thumbnail_fn = Path(IMAGES_DIR, 'noimage_thumbnail.png')
                with open(thumbnail_fn, 'rb') as fo:
                    thumbnail_data = fo.read()

                queue_data = (thumbnail_data, *metadata)
                pickle.dump(queue_data, queue_fo)

        sensitive = text and save_fp.exists()
        self.queuefiles_load_button.set_sensitive(sensitive)

        stats = self.get_stats(save_fp)
        for row in self.queuefiles_liststore:
            # If text is already in queuefiles_liststore, just update stats.
            if row[0] == text:
                self.queuefiles_liststore[row.iter] = (text, *stats)
                break
        else:
            # Otherwise, append a new row and select it.
            treeiter = self.queuefiles_liststore.append((text, *stats))
            self.queuefiles_treeselection.select_iter(treeiter)

    @Gtk.Template.Callback()
    def on_queuefiles_load_button_clicked(self, button):
        model, treeiter = self.queuefiles_treeselection.get_selected()
        text = self.queuefiles_liststore[treeiter][0]
        load_fn = Path(QUEUEFILES, text)

        queue_fo = open(load_fn, 'rb')
        tmp_fn = load_fn.with_suffix('.tmp')
        tmp_fo = open(tmp_fn, 'wb')

        def get_row():
            try:
                queue_file_data = pickle.load(queue_fo)
                queue_file_row = PlayqueueModelRow._make(queue_file_data)

                # The recording exists if the sound file exists.
                if Path(SOUND, queue_file_row.uuid).exists():
                    # Aside from random and uuid, use the metadata in the
                    # queue file only when the recording no longer exists.
                    new_queue_file_row = self.get_current(queue_file_row)

                    # Keep the same subset of tracks as in the queue file.
                    new_tracks = self.select_tracks(new_queue_file_row.tracks,
                            queue_file_row.tracks)
                    new_queue_file_row = new_queue_file_row._replace(
                            tracks=new_tracks)

                    pickle.dump(tuple(new_queue_file_row), tmp_fo)

                    # The queue gets the same data except that the
                    # image is a pixbuf.
                    new_pixbuf = self.load_pixbuf(new_queue_file_row.image)
                    new_queue_row = new_queue_file_row._replace(
                            image=new_pixbuf)
                else:
                    # If I remove the unplayable recording from the
                    # queue file, then the user gets one chance to
                    # identify the recording. Preserve it instead.
                    pickle.dump(tuple(queue_file_row), tmp_fo)

                    new_pixbuf = self.load_pixbuf(queue_file_row.image)
                    new_queue_row = queue_file_row._replace(
                            image=new_pixbuf,
                            playable=False)
                playqueue_model_with_attrs.append(new_queue_row)
                if new_queue_row.playable:
                    select_right.select_last_set()
                return True
            except EOFError:
                queue_fo.close()
                tmp_fo.close()
                tmp_fn.rename(load_fn)
                return False

        get_row()
        GLib.timeout_add(500, get_row)

    # Get the current metadata for the recording with uuid.
    def get_current(self, queue_file_row):
        genre = queue_file_row.genre
        uuid = queue_file_row.uuid
        work_num = queue_file_row.work_num
        with shelve.open(LONG, 'r') as long_shelf:
            recording = long_shelf[queue_file_row.uuid]
        work = recording.works[work_num]
        track_tuples = queue_file_row.tracks

        # Get thumbnail data for the recording with uuid.
        thumbnail_fn = Path(IMAGES, uuid, 'thumbnail-00.jpg')
        if not thumbnail_fn.exists():
            thumbnail_fn = Path(IMAGES_DIR, 'noimage_thumbnail.png')
        with open(thumbnail_fn, 'rb') as fo:
            thumbnail_data = fo.read()

        group_map = {t: GroupTuple(g_name, g_metadata)
                for g_name, g_tracks, g_metadata in work.trackgroups
                for t in g_tracks}

        primary_keys = config.genre_spec[genre]['primary']
        primary_metadata, = zip(*work.metadata[:len(primary_keys)])
        primary_vals_str = '\n'.join(primary_metadata)

        play_tracks = list(track_tuples)
        return PlayqueueModelRow(thumbnail_data, (primary_vals_str,),
                track_tuples, group_map, genre, uuid, work_num,
                queue_file_row.random, recording.props, True, play_tracks)

    def load_pixbuf(self, data):
        pb_loader = PixbufLoader.new_with_type('jpeg')
        pb_loader.write(data)
        pb_loader.close()
        return pb_loader.get_pixbuf()

    def select_tracks(self, all_tracks, queue_file_tracks):
        t_map = {t.track_id: t for t in all_tracks}
        return [t_map[t.track_id] for t in queue_file_tracks]

    @Gtk.Template.Callback()
    def on_queuefiles_delete_button_clicked(self, button):
        model, treeiter = self.queuefiles_treeselection.get_selected()
        text = self.queuefiles_liststore[treeiter][0]
        Path(QUEUEFILES, text).unlink()
        self.queuefiles_load_button.set_sensitive(False)
        self.queuefiles_delete_button.set_sensitive(False)

        model.remove(treeiter)

    def get_stats(self, path):
        total_duration = 0.0
        n_works = 0
        with open(path, 'rb') as queue_fo:
            while True:
                try:
                    queue_file_data = pickle.load(queue_fo)
                    queue_file_row = PlayqueueModelRow._make(queue_file_data)

                    item_duration = sum(track.duration
                            for track in queue_file_row.tracks)
                    total_duration += item_duration
                    n_works += 1
                except EOFError:
                    break
        return make_time_str(total_duration), n_works


page_widget = QueueFiles()

