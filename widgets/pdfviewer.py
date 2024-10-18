"""A viewer and a treemodel for acquiring documents. Used by docs in
edit mode and docs in play mode."""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Poppler', '0.18')
from gi.repository import Gtk, Poppler

from common.decorators import UniqObjectName
from common.utilities import debug

# Gtk.ListStore cannot store binary data (the data in the PDF file), so
# I define a class that behaves like a ListStore that can.
class MyDocsListstore:
    def __init__(self, pdfviewer_liststore):
        self.pdfviewer_liststore = pdfviewer_liststore
        self.pdf_data = []

    def __getitem__(self, index):
        return self.pdfviewer_liststore.__getitem__(index)

    def __delitem__(self, treeiter):
        del self.pdfviewer_liststore[treeiter]

        path = self.pdfviewer_liststore.get_path(treeiter)
        del self.pdf_data[path[0]]

    def __iter__(self):
        return zip(self.name_iter(), self.pdf_data)

    def __len__(self):
        return self.pdfviewer_liststore.__len__()

    def append(self, val):
        treeiter = self.pdfviewer_liststore.append(val[:2])
        self.pdf_data.append(val[2])
        return treeiter

    def add(self, val):
        # If the file name matches, replace the pdf data.
        for i, row in enumerate(self.pdfviewer_liststore):
            if row[0] == val[0]:
                self.pdf_data[i] = val[2]
                return row.iter

        # No match, so simply append val.
        treeiter = self.append(val)
        return treeiter

    def clear(self):
        self.pdfviewer_liststore.clear()
        self.pdf_data = []

    # Iterate over the names in the liststore.
    def name_iter(self):
        return (r[0] for r in self.pdfviewer_liststore)

@UniqObjectName
class PdfViewer(Gtk.EventBox):
    def __init__(self):
        drawing_area = Gtk.DrawingArea.new()
        self.add(drawing_area)

    def do_draw(self, context):
        alloc = self.get_allocation()
        alloc_width, alloc_height = (alloc.width, alloc.height)

        image_width, image_height = self.page.get_size()
        ratio = image_height / image_width

        # First scale by width. If the resulting height does not fit, then
        # scale by height.
        scaled_height = round(alloc_width * ratio)
        if scaled_height > alloc_height:
            scale = float(alloc_height) / image_height
        else:
            scale = float(alloc_width) / image_width
        context.scale(scale, scale)

        # Fill background with white in case pdf has transparent background.
        context.set_source_rgb(1, 1, 1)
        context.rectangle(0, 0, image_width, image_height)
        context.fill()

        self.page.render(context)

    def set_doc(self, filename):
        self.document = Poppler.Document.new_from_file(filename, None)
        self.n_pages = self.document.get_n_pages()

        self.page_num = 0
        self.page = self.document.get_page(0)
        self.queue_draw()

        self.show()

    def next_page(self):
        self.page_num = (self.page_num + 1) % self.n_pages
        self.page = self.document.get_page(self.page_num)
        self.queue_draw()

    def prev_page(self):
        self.page_num = (self.page_num - 1) % self.n_pages
        self.page = self.document.get_page(self.page_num)
        self.queue_draw()

