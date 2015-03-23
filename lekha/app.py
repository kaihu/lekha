#!/usr/bin/python
#
#  Lekha - A PDF document viewer
#
#  Copyright 2015 Kai Huuhko <kai.huuhko@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from __future__ import print_function

import time
import logging
import argparse
import json
import os

from efl.ecore import Idler

import efl.evas as evas
from efl.evas import Smart, SmartObject, FilledImage, EXPAND_BOTH, FILL_BOTH, \
    EVAS_CALLBACK_KEY_DOWN, EVAS_CALLBACK_KEY_UP, EVAS_CALLBACK_MOUSE_WHEEL, \
    Rect, Rectangle, EXPAND_HORIZ, FILL_HORIZ

import efl.elementary as elm
from efl.elementary import ELM_POLICY_QUIT, ELM_POLICY_QUIT_LAST_WINDOW_CLOSED
from efl.elementary.configuration import Configuration
elm_conf = Configuration()
from efl.elementary.window import StandardWindow, Window, ELM_WIN_DIALOG_BASIC
from efl.elementary.box import Box
from efl.elementary.scroller import Scroller
from efl.elementary.button import Button
from efl.elementary.notify import Notify
from efl.elementary.label import Label
from efl.elementary.spinner import Spinner
from efl.elementary.progressbar import Progressbar
from efl.elementary.toolbar import Toolbar, ELM_OBJECT_SELECT_MODE_NONE
from efl.elementary.fileselector import Fileselector
from efl.elementary.background import Background

import PyPDF2

from xdg import BaseDirectory

from .tabbedbox import Tabs, Tab


class AppWindow(StandardWindow):

    def __init__(self, doc_specs={}):
        SCALE = elm_conf.scale

        self.docs = []
        self.doc_specs = doc_specs

        super(AppWindow, self).__init__(
            "main", "Lekha",
            size=(400 * SCALE, 400 * SCALE),
            autodel=True)

        main_box = Box(self, size_hint_weight=EXPAND_BOTH)
        self.resize_object_add(main_box)

        tb = Toolbar(
            self,  # For some reason item menus break when parent is main_box
            size_hint_weight=EXPAND_HORIZ, size_hint_align=FILL_HORIZ,
            select_mode=ELM_OBJECT_SELECT_MODE_NONE, icon_size=24)
        tb.item_append(
            "document-open", "Open", lambda x, y: Fs(self.document_open))

        it = tb.item_append("zoom-in", "Zoom")
        it.menu = True
        tb.menu_parent = self
        menu = it.menu
        menu.item_add(
            None, "Zoom In", "zoom-in",
            lambda x, y: tabs.currentContent.zoom_in())
        menu.item_add(
            None, "Zoom Out", "zoom-out",
            lambda x, y: tabs.currentContent.zoom_out())
        menu.item_add(
            None, "Zoom 1:1", "zoom-original",
            lambda x, y: tabs.currentContent.zoom_orig())
        menu.item_add(
            None, "Zoom Fit", "zoom-fit-best",
            lambda x, y: tabs.currentContent.zoom_fit())

        tabs = self.tabs = Tabs(main_box, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)

        # tabs.callback_add("tab,added", lambda x, y: print("added", y))
        # tabs.callback_add("tab,selected", lambda x, y: print("selected", y))
        tabs.callback_add("tab,deleted", lambda x, y: y.delete())

        main_box.pack_end(tb)
        main_box.pack_end(tabs)
        tb.show()
        tabs.show()

        main_box.show()

    def document_open(self, doc_path):
        if not doc_path:
            return
        doc_zoom, doc_pos = self.doc_specs.get(doc_path, [None, None])
        try:
            assert isinstance(doc_zoom, float), "zoom is not float"
            assert isinstance(doc_pos, list), "pos is not tuple"
            assert len(doc_pos) == 4, "pos len is not 4"
        except Exception as e:
            log.info("document zoom and position could not be restored because: %r", e)
            doc_pos = (0, 0, 0, 0)
            doc_zoom = 1.0

        t1 = self.t1 = time.clock()
        try:
            doc = PyPDF2.PdfFileReader(doc_path)
            info = doc.getDocumentInfo()
        except Exception as e:
            log.exception("Document could not be opened because: %r" % e)
            return
        doc._flatten()
        t2 = time.clock()

        log.info("%s %s %s %s %s", info.title, info.author, info.subject, info.creator, info.producer)

        log.info("Reading the doc took: %f", t2-t1)

        if info.title and info.author:
            doc_title = "{0}".format(info.title)
        else:
            doc_title = doc_path

        content = Document(self, doc, doc_path, doc_zoom, doc_pos)
        self.docs.append(content)
        self.tabs.append(Tab(doc_title, content))

        idler = Idler(content.populate_page, enumerate(doc.pages, start=0))
        self.callback_delete_request_add(lambda x: idler.delete())


class Document(Box):

    def __init__(self, parent, doc, doc_path, doc_zoom=1.0, doc_pos=None):
        self.doc_path = doc_path
        self._zoom = doc_zoom
        self.doc_pos = doc_pos
        self.pages = []

        super(Document, self).__init__(parent, size_hint_weight=EXPAND_BOTH, align=(0.5, 0.0))

        scr = self.scr = Scroller(self, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)
        scr.callback_scroll_add(self._scrolled)
        self.pack_end(scr)

        box = self.page_box = Box(scr, size_hint_weight=EXPAND_BOTH, size_hint_align=(0.5, 0.0))
        scr.content = box

        self.elm_event_callback_add(self._event_handler)
        self.on_resize_add(self._resized)

        toolbox = Box(self, horizontal=True, size_hint_weight=EXPAND_HORIZ)

        spn = self.spn = Spinner(toolbox, round=1.0)
        spn.special_value_add(1, "First")
        toolbox.pack_end(spn)

        btn = Button(toolbox, text="show page")
        btn.callback_clicked_add(self._show_page_cb, spn)
        toolbox.pack_end(btn)

        zlbl = self.zlbl = Label(
            toolbox, text="%1.0f %%" % (self.zoom * 100.0))
        toolbox.pack_end(zlbl)

        for c in toolbox:
            c.show()

        self.pack_end(toolbox)

        for c in self:
            c.show()

        n = self.page_notify = Notify(scr, align=(0.02, 0.02))
        b = Box(n, horizontal=True, padding=(6, 0))
        n.content = b

        n = self.load_notify = Notify(scr, align=(0.98, 0.98))
        pb = Progressbar(n, pulse_mode=True, style="wheel")
        n.content = pb
        pb.pulse(True)
        n.show()

        self.show()

    def populate_page(self, itr):
        try:
            pg_num, pg = next(itr)
        except StopIteration:
            self.load_notify.content.pulse(False)
            self.load_notify.hide()
            self.spn.special_value_add(len(self.pages), "Last")
            if self.doc_pos is not None:
                self.scr.region_show(*self.doc_pos)
            return False

        mbox = pg.mediaBox
        w, h = mbox[2], mbox[3]

        box = self.page_box

        page = Page(box, self.doc_path, pg_num, w, h, self.zoom)
        page.callback_add("viewport,in", self._viewport_in, self.page_notify)
        page.callback_add("viewport,out", self._viewport_out, self.page_notify)
        box.pack_end(page)
        page.show()

        self.pages.append((pg.indirectRef.idnum, page))

        self.spn.min_max = (1, len(self.pages))

        return True

    @staticmethod
    def _resized(obj):
        for page in obj.page_box:
            page.changed()

    @property
    def zoom(self):
        return self._zoom

    @zoom.setter
    def zoom(self, value):
        for c in self.page_box:
            c.zoom_set(value)
        self._zoom = value
        self.zlbl.text = "%1.0f %%" % (value * 100.0)

    def zoom_in(self, value=0.2):
        self.zoom += value

    def zoom_out(self, value=0.2):
        self.zoom -= value

    def zoom_orig(self):
        self.zoom = 1.0

    def zoom_fit(self):
        widest = 0
        for c in self.page_box:
            pw = c.size[0]
            if pw > widest:
                widest = pw

        viewport_width = self.scr.region[2]
        self.zoom *= viewport_width/widest

    def _event_handler(self, obj, src, tp, ev):
        if tp == EVAS_CALLBACK_KEY_UP:
            if ev.key == "plus":
                self.zoom_in()
            elif ev.key == "minus":
                self.zoom_out()

    @staticmethod
    def _viewport_in(obj, ei, n):
        l = obj.page_num_label
        b = n.content
        b.pack_end(l)
        n.timeout = 3
        l.show()
        n.show()

    @staticmethod
    def _viewport_out(obj, ei, n):
        l = obj.page_num_label
        b = n.content
        b.unpack(l)
        l.hide()
        n.show()

    def _show_page_cb(self, btn, spn):
        pg_num = int(round(spn.value))-1
        self.page_show(pg_num)

    def page_show(self, pg_num):
        pg_id, pg = self.pages[pg_num]
        x1, y1, w1, h1 = self.scr.region
        x2, y2, w2, h2 = pg.geometry
        new_x = x1 + x2
        new_y = y1 + y2
        self.scr.region_show(new_x, new_y, 0, h1)

    def _scrolled(self, scr):
        self.doc_pos = scr.region


class PageSmart(Smart):

    @staticmethod
    def check_visibility(obj, x, y, w, h):
        r1 = Rect(x, y, w, h)
        r2 = obj.evas.rect
        hq_img = obj.hq_img
        pv_img = obj.pv_img

        if r1.intersects(r2):
            if obj.in_viewport:
                return
            obj.in_viewport = True
            obj.callback_call("viewport,in")
            for img in (pv_img,):
                img.file = (obj.doc_path, str(obj.page_num))
                img.preload()
            log.debug("preloading pv %d %r %r", obj.page_num, r1, r2)
        else:
            if not obj.in_viewport:
                return
            obj.in_viewport = False
            obj.callback_call("viewport,out")
            log.debug("hiding %d %r %r", obj.page_num, r1, r2)
            for img in pv_img, hq_img:
                img.image_data_set(None)
                img.hide()

    def calculate(self, obj):
        self.check_visibility(obj, *obj.geometry)

    def resize(self, obj, w, h):
        # x, y = obj.pos
        #log.debug("resize %d %d", w, h)
        for child in obj:
            child.resize(w, h)
        # self.check_visibility(obj, x, y, w, h)

    def move(self, obj, x, y):
        #log.debug("move %d %d", x, y)
        w, h = obj.size
        for child in obj:
            child.move(x, y)
        self.check_visibility(obj, x, y, w, h)

    @staticmethod
    def clip_set(obj, clip):
        for child in obj:
            child.clip_set(clip)

    @staticmethod
    def clip_unset(obj):
        for child in obj:
            child.clip_unset()

    @staticmethod
    def delete(obj):
        for child in obj:
            child.delete()


class Page(SmartObject):

    SMART = PageSmart()
    SIZE_MIN = 50

    def __init__(self, parent, doc_path, page_num, w, h, zoom=1.0):
        self.doc_path = doc_path
        self.page_num = page_num
        self.in_viewport = False

        evas = parent.evas
        super(Page, self).__init__(evas, self.SMART, parent=parent)

        self.page_num_label = Label(parent, text=str(page_num + 1))

        self.bg = Rectangle(evas, color=(255, 255, 255, 255))
        self.member_add(self.bg)
        self.bg.show()

        self.pv_img = FilledImage(evas, load_dpi=1, load_size=(w/2, h/2))
        self.member_add(self.pv_img)

        self.pv_img.on_image_preloaded_add(self.pv_preloaded)

        self.hq_img = FilledImage(evas, load_dpi=1, load_size=(w*4, h*4))
        self.member_add(self.hq_img)

        self.hq_img.on_image_preloaded_add(self.hq_preloaded, self.pv_img)

        self.orig_w = float(w)
        self.orig_h = float(h)

        w = float(w) * zoom
        h = float(h) * zoom

        self.size_hint_min = w, h

        self.pass_events = True

    def zoom_set(self, value):
        old_size = self.size_hint_min
        new_size = [i * value for i in (self.orig_w, self.orig_h)]
        if (
                (old_size[0] >= self.SIZE_MIN or
                 old_size[1] >= self.SIZE_MIN) and
                (new_size[0] < self.SIZE_MIN or
                 new_size[1] < self.SIZE_MIN)):
            return
        self.size_hint_min = new_size

    def hq_preloaded(self, hq_img, pv_img):
        log.debug("preloaded hq %d", self.page_num)
        pv_img.hide()
        hq_img.show()

    def pv_preloaded(self, pv_img):
        log.debug("preloaded pv %d", self.page_num)
        pv_img.show()
        for img in (self.hq_img,):
            img.file = (self.doc_path, str(self.page_num))
            img.preload()
        log.debug("preloading hq %d", self.page_num)


class Fs(Window):

    def __init__(self, done_cb):
        SCALE = elm_conf.scale

        super(Fs, self).__init__(
            "fileselector", ELM_WIN_DIALOG_BASIC, title="Select file",
            size=(400 * SCALE, 400 * SCALE), autodel=True)

        bg = Background(self, size_hint_weight=EXPAND_BOTH)
        self.resize_object_add(bg)
        bg.show()

        fs = Fileselector(
            self, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH,
            is_save=False, expandable=False, path=os.path.expanduser("~"))
        self.resize_object_add(fs)
        fs.mime_types_filter_append(["application/pdf", ], "pdf")
        fs.mime_types_filter_append(["*", ], "all")
        fs.callback_done_add(lambda x, y: done_cb(y))
        fs.callback_done_add(lambda x, y: self.delete())
        fs.show()
        self.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Presenter of writings")
    parser.add_argument(
        'documents', metavar='pdf', type=str, nargs='*',
        help='documents you may want to display')
    args = parser.parse_args()

    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(name)s [%(levelname)s] %(module)s:%(lineno)d   %(message)s")
    handler.setFormatter(formatter)

    efl_log = logging.getLogger("efl")
    efl_log.addHandler(handler)

    log = logging.getLogger("lekha")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    evas.init()
    elm.init()

    elm.policy_set(ELM_POLICY_QUIT, ELM_POLICY_QUIT_LAST_WINDOW_CLOSED)

    doc_specs = {}

    cfg_base_path = BaseDirectory.save_config_path("lekha")
    cfg_file_path = os.path.join(cfg_base_path, "document_positions")

    if not os.path.exists(cfg_file_path):
        try:
            open(cfg_file_path, "w").close()
        except Exception as e:
            log.debug(e)

    with open(cfg_file_path, "r") as fp:
        try:
            doc_specs = json.load(fp)
        except Exception:
            log.info("document positions could not be restored")

    app = AppWindow(doc_specs)

    docs = []

    for doc_path in args.documents:
        app.document_open(doc_path)

    app.show()

    elm.run()

    for d in app.docs:
        path = d.doc_path
        zoom = d.zoom
        pos = d.doc_pos
        doc_specs[path] = (zoom, pos)

    with open(cfg_file_path, "w") as fp:
        json.dump(doc_specs, fp, indent=4, separators=(',', ': '))

    elm.shutdown()
    evas.shutdown()
    logging.shutdown()
