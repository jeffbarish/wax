"""A widget for acquiring and displaying documents."""

import os
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Poppler', '0.18')
from gi.repository import Gtk

from common.constants import DOCUMENTS, TRANSFER
from common.constants import PDF_EXT
from common.contextmanagers import cd_context
from common.descriptors import QuietProperty
from common.utilities import debug
from widgets.pdfviewer import MyDocsListstore, PdfViewer
from widgets import options_button

NOUUID = '0'

@Gtk.Template.from_file('data/glade/edit/left/docs.glade')
class DocsEditor(Gtk.Box):
    __gtype_name__ = 'edit_docs_box'

    _docs_changed = QuietProperty(type=bool, default=False)

    docs_delete_button = Gtk.Template.Child()
    docs_pdf_next_button = Gtk.Template.Child()
    docs_pdf_prev_button = Gtk.Template.Child()
    docs_liststore = Gtk.Template.Child()
    docs_treeselection = Gtk.Template.Child()
    docs_filename_column = Gtk.Template.Child()
    docs_filename_renderer = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('edit-docs-page')
        self.tab_text = 'Docs'
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.props.margin = 2
        self.props.margin_left = 3
        self.props.margin_top = 3
        self.set_spacing(2)

        self.my_docs_liststore = MyDocsListstore(self.docs_liststore)

        # Display only the basename of the document in the treeview.
        def func(column, cell, model, treeiter, *data):
            cell.props.text = os.path.basename(model[treeiter][0])
        cell = self.docs_filename_renderer
        col = self.docs_filename_column
        col.set_cell_data_func(cell, func)

        options_button.connect_menuitem('Edit', 'Clear',
                self.on_options_edit_clear_activate)

        self.pdf_data = []

        self.pdf_viewer = pdf_viewer = PdfViewer()
        self.pack_end(pdf_viewer, True, True, 0)
        self.show()

    def on_options_edit_clear_activate(self, menuitem):
        self._docs_changed = False

    @Gtk.Template.Callback()
    def on_docs_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()
        sensitive = (treeiter is not None)
        self.docs_delete_button.props.sensitive = sensitive
        self.docs_pdf_next_button.props.sensitive = sensitive
        self.docs_pdf_prev_button.props.sensitive = sensitive

        if treeiter is not None:
            filename, uuid = model[treeiter][0], model[treeiter][1]
            if uuid == NOUUID:
                filename = Path(TRANSFER, filename).absolute().as_uri()
            else:
                filename = Path(DOCUMENTS, uuid, filename).absolute().as_uri()
            self.pdf_viewer.set_doc(filename)
            self.pdf_viewer.show_all()

    @Gtk.Template.Callback()
    def on_docs_delete_button_clicked(self, button):
        model, treeiter = self.docs_treeselection.get_selected()
        del self.my_docs_liststore[treeiter]

        self.pdf_viewer.props.visible = bool(len(model))

        self._docs_changed = True

    @Gtk.Template.Callback()
    def on_filename_renderer_edited(self, renderer, path, new_text):
        if not Path(new_text).suffix in PDF_EXT:
            new_text += '.pdf'
        self.docs_liststore[path] = (new_text, NOUUID)
        self._docs_changed = True

    @Gtk.Template.Callback()
    def on_docs_pdf_prev_button_clicked(self, button):
        self.pdf_viewer.prev_page()
        self.queue_draw()

    @Gtk.Template.Callback()
    def on_docs_pdf_next_button_clicked(self, button):
        self.pdf_viewer.next_page()
        self.queue_draw()

    def populate(self, uuid):
        self.my_docs_liststore.clear()

        documents_dir = Path(DOCUMENTS, uuid)
        for filename in documents_dir.iterdir():
            doc_data = self._read_pdf(filename)
            new_row = (filename.name, uuid, doc_data)
            self.my_docs_liststore.append(new_row)

        if len(self.my_docs_liststore):
            row = self.my_docs_liststore[0]
            self.docs_treeselection.select_iter(row.iter)
        else:
            self.pdf_viewer.hide()

    def _import_pdf(self, filename):
        doc_filename = Path(TRANSFER, filename)
        return self._read_pdf(doc_filename)

    def _read_pdf(self, filename):
        with open(filename, 'rb') as fo:
            return fo.read()

    # For importing multiple doc files (see importfiles.import_).
    def append_docs(self, doc_filenames):
        for doc_filename in doc_filenames:
            doc_data = self._read_pdf(doc_filename)
            filename = doc_filename.removeprefix(str(TRANSFER)).lstrip('/')
            new_row = (filename, NOUUID, doc_data)
            new_iter = self.my_docs_liststore.append(new_row)
        self.docs_treeselection.select_iter(new_iter)

    # For adding multiple doc files (see importfiles.add).
    def add_docs(self, doc_filenames):
        for doc_filename in doc_filenames:
            doc_data = self._read_pdf(doc_filename)
            filename = doc_filename.removeprefix(str(TRANSFER)).lstrip('/')
            new_row = (filename, NOUUID, doc_data)
            new_iter = self.my_docs_liststore.add(new_row)
        self.docs_treeselection.select_iter(new_iter)

        filename = Path(doc_filename).absolute().as_uri()
        self.pdf_viewer.set_doc(filename)

        self._docs_changed = True

    def write_docs(self, uuid):
        # Some documents might have been deleted from my_docs_liststore
        # after the recording was saved, so delete all existing doc files
        # and save the ones in docs_liststore/pdf_data that survive.
        with cd_context(Path(DOCUMENTS, uuid)):
            for file_path in Path('.').iterdir():
                if file_path not in self.my_docs_liststore.name_iter():
                    file_path.unlink()

            for filename, pdf_data in self.my_docs_liststore:
                filename = os.path.basename(filename)
                if not os.path.exists(filename):
                    with open(filename, 'wb') as fo:
                        fo.write(pdf_data)
        self._docs_changed = False

    def clear(self):
        self.my_docs_liststore.clear()
        self._docs_changed = False
        self.pdf_viewer.hide()


page_widget = DocsEditor()

