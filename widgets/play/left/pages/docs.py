"""A widget for viewing documents."""

from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from common.constants import DOCUMENTS, TRANSFER
from common.constants import EXPAND
from common.contextmanagers import stop_emission
from common.decorators import emission_stopper
from common.utilities import debug
from widgets.pdfviewer import MyDocsListstore, PdfViewer

@Gtk.Template.from_file('data/glade/play/docs.glade')
class DocsView(Gtk.Box):
    __gtype_name__ = 'docs_box'

    docs_liststore = Gtk.Template.Child()
    docs_treeselection = Gtk.Template.Child()
    docs_pdf_next_button = Gtk.Template.Child()
    docs_pdf_prev_button = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self.set_name('play-docs-page')
        self.tab_text = 'Docs'
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.props.margin = 2
        self.props.margin_left = 3
        self.props.margin_top = 3
        self.set_spacing(2)

        self.my_docs_liststore = MyDocsListstore(self.docs_liststore)

        self.pdf_data = []

        self.pdf_viewer = pdf_viewer = PdfViewer()
        self.pack_end(pdf_viewer, *EXPAND)
        self.show()

    @Gtk.Template.Callback()
    @emission_stopper()
    def on_docs_treeselection_changed(self, selection):
        model, treeiter = selection.get_selected()
        sensitive = (treeiter is not None)
        self.docs_pdf_next_button.props.sensitive = sensitive
        self.docs_pdf_prev_button.props.sensitive = sensitive

        if treeiter is not None:
            filename, uuid = model[treeiter]
            filename = Path(DOCUMENTS, uuid, filename).absolute().as_uri()
            self.pdf_viewer.set_doc(filename)
            self.pdf_viewer.show_all()

    @Gtk.Template.Callback()
    def on_docs_pdf_prev_button_clicked(self, button):
        self.pdf_viewer.prev_page()
        self.queue_draw()

    @Gtk.Template.Callback()
    def on_docs_pdf_next_button_clicked(self, button):
        self.pdf_viewer.next_page()
        self.queue_draw()

    def populate(self, uuid):
        with stop_emission(self.docs_treeselection, 'changed'):
            self.clear()

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

    def has_docs(self, uuid):
        documents_dir = Path(DOCUMENTS, uuid)
        return any(documents_dir.iterdir())

    def clear(self):
        self.my_docs_liststore.clear()
        self._docs_changed = False


page_widget = DocsView()
