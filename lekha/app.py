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
from threading import Thread
import mimetypes
try:
    from urllib import unquote
except ImportError:
    from urllib.parse import unquote

from efl.ecore import Idler, Timer

import efl.evas as evas
from efl.evas import Smart, SmartObject, FilledImage, EXPAND_BOTH, FILL_BOTH, \
    EVAS_CALLBACK_KEY_DOWN, EVAS_CALLBACK_KEY_UP, EVAS_CALLBACK_MOUSE_WHEEL, \
    Rect, Rectangle, EXPAND_HORIZ, FILL_HORIZ, EVAS_EVENT_FLAG_ON_HOLD

ALIGN_LEFT = 0.0, 0.5
ALIGN_RIGHT = 1.0, 0.5

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
from efl.elementary.table import Table
from efl.elementary.entry import Entry, utf8_to_markup
from efl.elementary.panel import Panel, ELM_PANEL_ORIENT_LEFT
from efl.elementary.genlist import Genlist, GenlistItem, GenlistItemClass, \
    ELM_GENLIST_ITEM_TREE, ELM_GENLIST_ITEM_NONE, ELM_LIST_COMPRESS, \
    ELM_OBJECT_SELECT_MODE_ALWAYS
from efl.elementary.menu import Menu
from efl.elementary.popup import Popup
from efl.elementary.check import Check
from efl.elementary.hover import Hover
from efl.elementary.list import List, ELM_LIST_EXPAND

import PyPDF2

from xdg import BaseDirectory

from .tabbedbox import Tabs, Tab

log = logging.getLogger("lekha")


class AppWindow(StandardWindow):

    def __init__(self, doc_specs={}):
        SCALE = elm_conf.scale

        self.docs = []
        self.doc_specs = doc_specs

        self.settings = {"scroll_by_page": False}

        super(AppWindow, self).__init__(
            "main", "Lekha",
            size=(400 * SCALE, 400 * SCALE),
            autodel=True)

        main_box = self.main_box = Box(self, size_hint_weight=EXPAND_BOTH)
        self.resize_object_add(main_box)

        tb = self.tb = Toolbar(
            self,  # For some reason item menus break when parent is main_box
            size_hint_weight=EXPAND_HORIZ, size_hint_align=FILL_HORIZ,
            select_mode=ELM_OBJECT_SELECT_MODE_NONE, icon_size=24)
        tb.item_append(
            "document-open", "Open", lambda x, y: Fs(self.document_open))
        tb.item_append(
            "view-fullscreen", "Fullscreen", lambda x, y: self.fullscreen_set(True))
        it = tb.item_append("preferences-system", "Settings", self._settings_open)

        tabs = self.tabs = Tabs(
            main_box, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)

        # tabs.callback_add(
        #     "tab,added", lambda x, y: self.title_set(y.doc_title))
        tabs.callback_add(
            "tab,selected", lambda x, y: self.title_set(y.doc_title))
        def selected_cb(tabs, content):
            for c in content.page_box:
                c.changed()
        tabs.callback_add(
            "tab,selected", selected_cb)
        tabs.callback_add(
            "tab,deleted", lambda x, y: y.delete())

        main_box.pack_end(tb)
        main_box.pack_end(tabs)
        tb.show()
        tabs.show()

        self.callback_fullscreen_add(self._fullscreen_cb)
        self.callback_unfullscreen_add(self._unfullscreen_cb)
        self.elm_event_callback_add(self._event_handler)

        main_box.show()

    def _event_handler(self, obj, src, tp, ev):
        content = self.tabs.currentContent
        if tp == EVAS_CALLBACK_MOUSE_WHEEL:
            if not content:
                return True
            if ev.modifier_is_set("Control"):
                if ev.direction == 0:
                    if ev.z == 1:
                        content.zoom_out()
                    else:
                        content.zoom_in()
                    ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD
            elif self.settings["scroll_by_page"]:
                if ev.direction == 0:
                    visible = content.visible_pages
                    if not visible:
                        return True
                    visible = visible[0]
                    if ev.z == 1:
                        content.page_show_by_num(visible+1)
                    else:
                        content.page_show_by_num(visible-1)
                    ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD
        elif tp == EVAS_CALLBACK_KEY_UP:
            key = ev.key
            if key == "plus":
                if content:
                    content.zoom_in()
            elif key == "minus":
                if content:
                    content.zoom_out()
            elif key == "Escape":
                if self.fullscreen:
                    self.fullscreen = False
            elif key == "F11":
                self.fullscreen = not self.fullscreen
            elif key == "Control_L" or key == "Control_R":
                if content:
                    content.scroll_thaw()
            elif key == "Page_Up" or key == "Up":
                if self.settings["scroll_by_page"]:
                    visible = content.visible_pages
                    if not visible:
                        return True
                    visible = visible[0]
                    content.page_show_by_num(visible-1)
                    ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD
            elif key == "Page_Down" or key == "Down":
                if self.settings["scroll_by_page"]:
                    visible = content.visible_pages
                    if not visible:
                        return True
                    visible = visible[0]
                    content.page_show_by_num(visible+1)
                    ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD
            else:
                return True
            ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD
        elif tp == EVAS_CALLBACK_KEY_DOWN:
            key = ev.key
            if key == "Control_L" or key == "Control_R":
                if content:
                    content.scroll_freeze()
            else:
                return True
            ev.event_flags |= EVAS_EVENT_FLAG_ON_HOLD

        return True

    @staticmethod
    def _fullscreen_cb(win):
        win.tabs.hide_tabs()
        win.main_box.unpack(win.tb)
        win.tb.hide()

    @staticmethod
    def _unfullscreen_cb(win):
        win.tabs.show_tabs()
        win.main_box.pack_start(win.tb)
        win.tb.show()

    def document_open(self, doc_path):
        if not doc_path:
            return

        mt = mimetypes.guess_type(doc_path)
        if mt[0] != "application/pdf":
            log.error("%s does not seem to be a pdf document", doc_path)
            return

        if doc_path.startswith("file://"):
            doc_path = unquote(doc_path[7:])

        if doc_path in self.doc_specs:
            doc_zoom, doc_pos = self.doc_specs[doc_path]
            try:
                assert isinstance(doc_zoom, float), "zoom is not float"
                assert isinstance(doc_pos, list), "pos is not tuple"
                assert len(doc_pos) == 4, "pos len is not 4"
            except Exception as e:
                log.warn(
                    "document zoom and position could not be restored because: %r",
                    e)
                doc_pos = [0, 0, 0, 0]
                doc_zoom = 1.0
        else:
            doc_pos = [0, 0, 0, 0]
            doc_zoom = 1.0

        doc = Document(self, doc_path, doc_pos, doc_zoom)
        self.docs.append(doc)
        tab = Tab(os.path.splitext(os.path.basename(doc_path))[0], doc)

        def title_changed(doc, title):
            tab.name = title
        doc.callback_add("title,changed", title_changed)
        self.tabs.append(tab)

    def _settings_open(self, obj, it):
        h = Hover(self)
        t = it.track_object
        h.pos = t.bottom_center
        del t
        del it.track_object

        l = List(h)
        l.mode = ELM_LIST_EXPAND
        h.part_content_set("bottom", l)
        l.show()

        chk = Check(self, text="Scroll By Page")
        chk.state = self.settings["scroll_by_page"]
        def _scroll_by_page_cb(obj):
            target_state = obj.state
            self.settings["scroll_by_page"] = target_state
            if self.tabs.currentContent:
                if target_state:
                    self.tabs.currentContent.scroll_freeze()
                else:
                    self.tabs.currentContent.scroll_thaw()
            h.dismiss()
        chk.callback_changed_add(_scroll_by_page_cb)

        l.item_append(None, chk)
        l.go()

        h.show()
        #chk.callback_clicked_add()


class OutLine(GenlistItemClass):

    def text_get(self, gl, part, ol):
        return ol.title

ol_glic = OutLine(item_style="no_icon")


class OutLineList(GenlistItemClass):

    def text_get(self, gl, part, ol):
        return

oll_glic = OutLineList(item_style="no_icon")


class Document(Table):

    """

    Custom smart events:

    - title,changed
    """

    def __init__(self, parent, path, pos=None, zoom=1.0):
        self.doc_path = path
        self._zoom = zoom
        self.doc_pos = pos
        self.pages = []
        self.doc = None
        self.doc_title = os.path.splitext(os.path.basename(path))[0]
        self.visible_pages = []

        super(Document, self).__init__(
            parent, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)

        scr = self.scr = Scroller(
            self, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)
        scr.callback_scroll_add(self._scrolled)
        self.pack(scr, 0, 0, 4, 1)
        scr.show()

        box = self.page_box = Box(
            scr, size_hint_weight=EXPAND_BOTH, size_hint_align=(0.5, 0.0))
        scr.content = box

        self.on_resize_add(self._resized)

        btn = Button(
            self, text="Toggle outlines", size_hint_align=ALIGN_LEFT)
        btn.callback_clicked_add(lambda x: self.ol_p.toggle())
        self.pack(btn, 0, 1, 1, 1)
        btn.show()

        spn = self.spn = Spinner(
            self, round=1.0,
            size_hint_weight=EXPAND_HORIZ, size_hint_align=FILL_HORIZ)
        spn.special_value_add(1, "First")
        spn.editable = True
        self.pack(spn, 1, 1, 1, 1)
        spn.show()

        btn = Button(
            self, text="show page",
            size_hint_weight=EXPAND_HORIZ, size_hint_align=ALIGN_LEFT)
        btn.callback_clicked_add(self._show_page_cb, spn)
        self.pack(btn, 2, 1, 1, 1)
        btn.show()

        menu = Menu(self.top_widget)
        menu.item_add(
            None, "Zoom In", "zoom-in",
            lambda x, y: self.zoom_in())
        menu.item_add(
            None, "Zoom Out", "zoom-out",
            lambda x, y: self.zoom_out())
        menu.item_add(
            None, "Zoom 1:1", "zoom-original",
            lambda x, y: self.zoom_orig())
        menu.item_add(
            None, "Zoom Fit", "zoom-fit-best",
            lambda x, y: self.zoom_fit())

        def z_clicked(btn):
            x, y = btn.evas.pointer_canvas_xy_get()
            menu.move(x, y)
            menu.show()

        zlbl = self.zlbl = Button(
            self, text="%1.0f %%" % (self.zoom * 100.0),
            size_hint_weight=EXPAND_HORIZ, size_hint_align=ALIGN_RIGHT)
        zlbl.callback_clicked_add(z_clicked)
        self.pack(zlbl, 3, 1, 1, 1)
        zlbl.show()

        n = self.page_notify = Notify(scr, align=(0.02, 0.02))
        b = Box(n, horizontal=True, padding=(6, 0))
        n.content = b

        n = self.load_notify = Notify(scr, align=(0.98, 0.98))
        pb = Progressbar(n, pulse_mode=True, style="wheel")
        n.content = pb
        pb.pulse(True)
        n.show()

        p = self.ol_p = Panel(
            self, orient=ELM_PANEL_ORIENT_LEFT,
            size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH,
            ) #scrollable=True, scrollable_content_size=0.35)
        p.hidden = True
        scr.on_move_add(lambda x: p.move(*x.pos))
        scr.on_resize_add(lambda x: p.resize(x.size[0] * 0.35, x.size[1]))

        ol_gl = self.ol_gl = Genlist(
            p, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH,
            mode=ELM_LIST_COMPRESS, homogeneous=True,
            select_mode=ELM_OBJECT_SELECT_MODE_ALWAYS
            )
        p.content = ol_gl

        ol_gl.callback_contract_request_add(self._gl_contract_req)
        ol_gl.callback_contracted_add(self._gl_contracted)
        ol_gl.callback_expand_request_add(self._gl_expand_req)
        ol_gl.callback_expanded_add(self._gl_expanded)
        ol_gl.show()

        p.show()
        self.show()

        def read_worker():
            t1 = self.t1 = time.clock()
            try:
                self.doc = PyPDF2.PdfFileReader(path)
                self.page_count = self.doc.getNumPages()
            except Exception as e:
                log.exception("Document could not be opened because: %r", e)
                self.doc = None
                self.display_error(e)
                return
            t2 = time.clock()
            log.info("Reading the doc took: %f", t2-t1)

        t = Thread(target=read_worker)
        t.daemon = True
        t.start()

        def worker_check(t):
            if t.is_alive():
                return True
            elif self.doc and self.page_count:
                spn.special_value_add(self.page_count, "Last")
                spn.min_max = (1, self.page_count)

                if self.doc.isEncrypted:
                    PasswordPrompt(self)
                    return False

                self.metadata_read()
                self.populate_pages()
                return False

        timer = Timer(0.2, worker_check, t)
        self.parent.callback_delete_request_add(lambda x: timer.delete())

    def display_error(self, exc):
        self.load_notify.content.delete()
        l = Label(
            self.load_notify, style="marker",
            text="Document load error: %s" % utf8_to_markup(str(exc)), color=(255, 0, 0, 255))
        self.load_notify.content = l
        l.show()

    def metadata_read(self):
        try:
            info = self.doc.getDocumentInfo()
        except Exception:
            log.warn("Metadata information could not be extracted from the document")
            return
        else:
            if not info:
                log.warn("Metadata information could not be extracted from the document")
                return

            log.info(
                "%s %s %s %s %s",
                info.title, info.author, info.subject, info.creator, info.producer)

            if info.title:
                self.doc_title = "{0}".format(info.title)
            self.callback_call("title,changed", self.doc_title)

    def populate_pages(self):
        try:
            itr = iter(xrange(self.page_count))
        except Exception:
            itr = iter(range(self.page_count))
        idler = Idler(self.populate_page, self.doc, itr)
        self.parent.callback_delete_request_add(lambda x: idler.delete())

    def outlines_populate(self, outlines, parent=None):
        for outline in outlines:
            if isinstance(outline, list):
                GenlistItem(oll_glic, outline, parent, ELM_GENLIST_ITEM_TREE).append_to(self.ol_gl)
            else:
                GenlistItem(ol_glic, outline, parent, ELM_GENLIST_ITEM_NONE, self._outline_clicked_cb, outline).append_to(self.ol_gl)

    @staticmethod
    def _gl_contract_req(gl, it):
        it.expanded = False

    @staticmethod
    def _gl_contracted(gl, it):
        it.subitems_clear()

    @staticmethod
    def _gl_expand_req(gl, it):
        it.expanded = True

    def _gl_expanded(self, gl, it):
        self.outlines_populate(it.data, it)

    def populate_page(self, doc, itr):
        try:
            pg_num = next(itr)
            pg = doc.getPage(pg_num)
        except StopIteration:
            if self.doc_pos is not None:
                self.scr.region_show(*self.doc_pos)

            def outlines_get():
                self.outlines = doc.outlines

            t1 = time.clock()
            t = Thread(target=outlines_get)
            t.daemon = True
            t.start()

            def check_outlines(t):
                if t.is_alive():
                    return True
                t2 = time.clock()
                log.info("Fetching outlines took: %f", t2-t1)
                self.outlines_populate(self.outlines)
                self.load_notify.content.pulse(False)
                self.load_notify.hide()

            self.outlines_timer = Timer(0.2, check_outlines, t)

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

        if widest == 0:
            log.error("Widest page has width of 0!")
            return

        widest += 1  # won't trigger scrolling because of rounding error.

        viewport_width = self.scr.region[2]

        self.zoom *= viewport_width/widest

    def _viewport_in(self, obj, ei, n):
        self.visible_pages.append(obj.page_num)
        l = obj.page_num_label
        b = n.content
        b.pack_end(l)
        n.timeout = 3.0
        l.show()
        n.show()

    def _viewport_out(self, obj, ei, n):
        self.visible_pages.remove(obj.page_num)
        l = obj.page_num_label
        b = n.content
        b.unpack(l)
        n.timeout = 3.0
        l.hide()
        n.show()

    def _show_page_cb(self, btn, spn):
        pg_num = int(round(spn.value))-1
        self.page_show_by_num(pg_num)

    def _outline_clicked_cb(self, glit, gl, ol):
        if ol.typ == "/Fit":
            self.page_show_by_id(ol.page.idnum)
        elif ol.typ == "/XYZ":
            self.page_show_by_id(ol.page.idnum, ol.left, ol.top)
        else:
            self.page_show_by_id(ol.page.idnum)
        # /FitH      [top]
        # /FitV      [left]
        # /FitR      [left] [bottom] [right] [top]
        # /FitB      No additional arguments
        # /FitBH     [top]
        # /FitBV     [left]

    def page_show_by_id(self, page_id, offset_x=0, offset_y=0):
        for id_num, pg in self.pages:
            if page_id == id_num:
                self.page_show(pg, offset_x, offset_y)
                break

    def page_show_by_num(self, pg_num):
        if pg_num < 0:
            pg_num = 0
        elif pg_num > self.page_count - 1:
            pg_num = -1
        pg_id, pg = self.pages[pg_num]
        self.page_show(pg)

    def page_show(self, pg, offset_x=0, offset_y=0):
        x1, y1, w1, h1 = self.scr.region
        x2, y2, w2, h2 = pg.geometry
        x3, y3 = self.scr.pos
        new_x = x1 + x2 - x3 + offset_x
        new_y = y1 + y2 - y3 + offset_y
        self.scr.region_show(new_x, new_y, 0, h1)

    def _scrolled(self, scr):
        self.doc_pos = scr.region

    def scroll_freeze(self):
        self.scr.scroll_freeze_push()

    def scroll_thaw(self):
        self.scr.scroll_freeze_pop()

    def scroll_freeze_get(self):
        return self.scr.scroll_freeze


class PageSmart(Smart):

    @staticmethod
    def check_visibility(obj, x, y, w, h):
        r1 = Rect(x, y, w, h)
        r2 = obj.parent.parent.rect
        hq_img = obj.hq_img
        pv_img = obj.pv_img

        if r1.intersects(r2):
            if obj.in_viewport is True:
                return
            obj.in_viewport = True
            obj.callback_call("viewport,in")
            pv_img.file = (obj.doc_path, str(obj.page_num))
            pv_img.preload()
            log.debug("preloading pv %d %r %r", obj.page_num, r1, r2)
        else:
            if obj.in_viewport is False:
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

        self.orig_w = float(w)
        self.orig_h = float(h)

        w = float(w) * zoom
        h = float(h) * zoom

        self.pv_img = FilledImage(evas, load_dpi=1, load_size=(w/2, h/2))
        self.member_add(self.pv_img)

        self.pv_img.on_image_preloaded_add(self.pv_preloaded)

        self.hq_img = FilledImage(evas, load_dpi=1, load_size=(w*2, h*2))
        self.member_add(self.hq_img)

        self.hq_img.on_image_preloaded_add(self.hq_preloaded, self.pv_img)

        self.size_hint_min = w, h

        self.pass_events = True

    def zoom_set(self, value):
        old_size = self.size_hint_min
        new_size = [(i * value) for i in (self.orig_w, self.orig_h)]
        if (
                (old_size[0] >= self.SIZE_MIN or
                 old_size[1] >= self.SIZE_MIN) and
                (new_size[0] < self.SIZE_MIN or
                 new_size[1] < self.SIZE_MIN)):
            return
        self.pv_img.load_size = [
            (i * value / 2) for i in (self.orig_w, self.orig_h)
            ]
        self.hq_img.load_size = [
            (i * value * 2) for i in (self.orig_w, self.orig_h)
            ]
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


class PasswordPrompt(Popup):

    def __init__(self, parent):
        Popup.__init__(self, parent)

        self.part_text_set("title,text", "Document is encrypted")

        e = self.e = Entry(self, password=True)
        e.part_text_set("guide", "Enter Password")
        self.content_set(e)
        e.show()

        okb = Button(self, text="OK")
        self.part_content_set("button1", okb)
        okb.callback_clicked_add(lambda x: self.okcb())
        okb.show()

        canb = Button(self, text="Cancel")
        self.part_content_set("button2", canb)
        canb.callback_clicked_add(lambda x: self.delete())
        canb.show()

        self.show()

    def okcb(self):
        ret = 0
        try:
            ret = self.parent.doc.decrypt(self.e.entry.encode("utf-8"))
        except Exception:
            log.exception("Could not decrypt the document")
            return
        if ret:
            self.parent.metadata_read()
            self.parent.populate_pages()
            self.delete()
        else:
            self.part_text_set("title,text", "Document is encrypted - Invalid password entered")


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
