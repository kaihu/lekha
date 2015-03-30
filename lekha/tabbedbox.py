# encoding: utf-8

from collections import OrderedDict

from efl.evas import EXPAND_BOTH, EXPAND_HORIZ, FILL_BOTH
from efl.elementary.box import Box
from efl.elementary.button import Button
from efl.elementary.icon import Icon
from efl.elementary.separator import Separator
from efl.elementary.scroller import Scroller, ELM_SCROLLER_POLICY_OFF, \
    ELM_SCROLLER_POLICY_AUTO, ELM_SCROLLER_MOVEMENT_BLOCK_VERTICAL
from efl.elementary.naviframe import Naviframe

EXPAND_NONE = 0.0, 0.0
ALIGN_CENTER = 0.5, 0.5
ALIGN_RIGHT = 1.0, 0.5
ALIGN_LEFT = 0.0, 0.5


class Tabs(Box):

    """A tabbed interface widget

    Contains a Box with tabs buttons at top and Naviframe at bottom for the
    main contents.

    Acts as both a Box and as OrderedDict with tab content as keys.
    You can use the dict interface for accessing tabs, like in this example::

        tabs = Tabs(win)
        tab1 = Tab("tab1", content1)
        tabs[content1] = tab1
        tabs.showTab(content1)
        tabs[content1].canSelect = False

    you can also use append() to add tabs:

        tab = Tab("tab2", content2)
        tabs.append(tab)

    Smart events:

    tab,selected
        A tab was selected (event info is the tabs content)

    tab,added
        A tab was added (event info is the tabs content)

    tab,deleted
        A tab was deleted (event info is the tabs content)

        The tab and its contents are deleted immediately after this event

    tabs,add,clicked
        The Add tab -button was clicked

    tabs,empty
        All tabs have been deleted
    """

    def __init__(self, parent_widget, add_tab=False, *args, **kwargs):
        Box.__init__(self, parent_widget, *args, **kwargs)

        self._dict = OrderedDict()

        # Tabs
        scr = self._scr = Scroller(
            self, size_hint_weight=EXPAND_HORIZ, size_hint_align=FILL_BOTH,
            policy=(ELM_SCROLLER_POLICY_AUTO, ELM_SCROLLER_POLICY_OFF),
            movement_block=ELM_SCROLLER_MOVEMENT_BLOCK_VERTICAL)
        scr.content_min_limit(False, True)

        tb = self._tabBox = Box(
            self._scr, size_hint_weight=EXPAND_HORIZ, align=ALIGN_LEFT,
            horizontal=True)
        tb.show()

        self._addTab = None
        if add_tab:
            at = self._addTab = Button(self._tabBox, style="anchor")
            at.content = Icon(self._addTab, standard="list-add")
            at.callback_clicked_add(lambda x: self.callback_call("tabs,add,clicked"))
            self._tabBox.pack_end(self._addTab)
            at.show()

        scr.content = self._tabBox
        scr.show()

        # Contents
        nf = self._nf = Naviframe(
            self, size_hint_weight=EXPAND_BOTH, size_hint_align=FILL_BOTH)
        nf.callback_transition_finished_add(self._nfit_shown)
        nf.show()

        self.pack_end(scr)
        self.pack_end(nf)

    def __len__(self):
        return OrderedDict.__len__(self._dict)

    def __getitem__(self, content):
        return OrderedDict.__getitem__(self._dict, content)

    def __setitem__(self, content, tab):
        if content in self._dict:
            raise KeyError("Content has already been added!")

        OrderedDict.__setitem__(self._dict, content, tab)

        tab._initialize(self._tabBox, self.showTab, self.__delitem__)

        if self._addTab is not None:
            self._tabBox.pack_before(tab._sel_btn, self._addTab)
            self._tabBox.pack_before(tab._cls_btn, self._addTab)
            self._tabBox.pack_before(tab._sep, self._addTab)
        else:
            self._tabBox.pack_end(tab._sel_btn)
            self._tabBox.pack_end(tab._cls_btn)
            self._tabBox.pack_end(tab._sep)

        current = self.currentContent
        if current is not None:
            self._dict[current].selected = False

        it = self._nf.item_simple_push(content)
        it.pop_cb_set(self._nfit_popping)

        tab.selected = True

        self.callback_call("tab,added", content)

    def __delitem__(self, content):
        self._nf.item_simple_promote(content)
        self._nf.item_pop()

    def __iter__(self):
        return OrderedDict.__iter__(self._dict)

    def __reversed__(self):
        return OrderedDict.__reversed__(self._dict)

    def __contains__(self, content):
        return OrderedDict.__contains__(self._dict, content)

    def keys(self):
        return OrderedDict.keys(self._dict)

    def items(self):
        return OrderedDict.items(self._dict)

    def append(self, tab):
        self[tab.content] = tab

    @property
    def currentContent(self):
        it = self._nf.top_item
        return it.content if it is not None else None

    def showTab(self, content):
        if content not in self._dict:
            return
        current = self.currentContent
        if content is current:
            return

        self._nf.item_simple_promote(content)

    def _nfit_shown(self, nf, it):
        for item in nf.items:
            if item is not it:
                self[item.content].selected = False

        self[it.content].selected = True
        self.callback_call("tab,selected", it.content)

    def _nfit_popping(self, it):
        tab = self._dict[it.content]
        tab._delete()
        OrderedDict.__delitem__(self._dict, it.content)
        self.callback_call("tab,deleted", it.content)
        if len(self) == 0:
            self.callback_call("tabs,empty")
        return True

    def hide_tabs(self):
        self.unpack(self._scr)
        self._scr.hide()

    def show_tabs(self):
        self.pack_start(self._scr)
        self._scr.show()


class Tab(object):

    SEL_COL = (255, 255, 255, 255)
    UNSEL_COL = (128, 128, 128, 128)

    def __init__(self, name, content, canClose=True, canSelect=True):
        self._name = name
        self.content = content
        self._canClose = canClose
        self._canSelect = canSelect
        self._sel_btn = None
        self._cls_btn = None
        self._sep = None

    def __repr__(self):
        return "<%s(name=%r, content=%r, canClose=%r, canSelect=%r)>" % (
            self.__class__.__name__, self._name, self.content.__name__,
            self.canClose, self.canSelect)

    def _initialize(self, parent_widget, show_func, del_func):
        sel_btn = self._sel_btn = Button(
            parent_widget, style="anchor", text=self._name,
            size_hint_align=ALIGN_LEFT, disabled=(not self._canSelect))
        sel_btn.callback_clicked_add(lambda x, y=self.content: show_func(y))
        sel_btn.show()

        icn = Icon(parent_widget, standard="window-close")
        icn.show()

        cls_btn = self._cls_btn = Button(
            parent_widget, style="anchor", content=icn,
            size_hint_align=ALIGN_LEFT, disabled=(not self._canClose))
        cls_btn.callback_clicked_add(lambda x, y=self.content: del_func(y))
        if self._canClose:
            cls_btn.show()

        self._sep = Separator(parent_widget, size_hint_align=ALIGN_LEFT)
        self._sep.show()

    def _delete(self):
        for w in self._sel_btn, self._cls_btn, self._sep:
            w.parent.unpack(w)
            w.delete()

    @property
    def selected(self):
        return True if self._sel_btn.color == self.SEL_COL else False

    @selected.setter
    def selected(self, value):
        self._sel_btn.color = self.SEL_COL if value else self.UNSEL_COL
        self._cls_btn.color = self.SEL_COL if value else self.UNSEL_COL

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._sel_btn.text = value
        self._name = value

    @property
    def canClose(self):
        return self._canClose

    @canClose.setter
    def canClose(self, value):
        self._canClose = value
        if self._cls_btn is not None:
            self._cls_btn.disabled = not value
            self._cls_btn.visible = value

    @property
    def canSelect(self):
        return self._canSelect

    @canSelect.setter
    def canSelect(self, value):
        self._canSelect = value
        if self._sel_btn is not None:
            self._sel_btn.disabled = not value


if __name__ == "__main__":
    import logging
    elog = logging.getLogger("efl")
    elog.addHandler(logging.StreamHandler())
    elog.setLevel(logging.WARN)

    import efl.elementary as elm
    import efl.evas as evas
    from efl.elementary.window import StandardWindow
    from efl.elementary.label import Label

    evas.init()
    elm.init()
    elm.policy_set(elm.ELM_POLICY_QUIT, elm.ELM_POLICY_QUIT_LAST_WINDOW_CLOSED)

    win = StandardWindow("test", "test", autodel=True)

    tabs = Tabs(win, size_hint_weight=EXPAND_BOTH, size_hint_fill=FILL_BOTH)

    def added(tabs, content): print("added", content)
    def selected(tabs, content): print("selected", content)
    def deleted(tabs, content): print("deleted", content)

    tabs.callback_add("tab,added", added)
    tabs.callback_add("tab,selected", selected)
    tabs.callback_add("tab,deleted", deleted)

    for i in range(20):
        lbl = Label(win, text="Tab %s" % i)
        tabs.append(Tab("Tab %s" % i, lbl))

    tabs.show()
    win.resize_object_add(tabs)
    win.resize(640, 480)
    win.show()

    elm.run()
    elm.shutdown()
    evas.shutdown()
    logging.shutdown()
