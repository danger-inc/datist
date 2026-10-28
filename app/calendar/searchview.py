# datist – Suche: Overlay-Karte mit Suchfeld und Trefferliste (Taste /). Springt zum Termin oder öffnet ihn.
import datetime as dt

import gi
from gi.repository import Gdk, GLib, Gtk

import tui
from tui import label, hbox, vbox

import raster
from raster import WEEKDAYS


class SearchBox(Gtk.Box):
    LIMIT = 60

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.app = app
        self.add_css_class("editor-card")
        self.set_margin_top(40)
        self.panel = tui.Panel("suche")
        self.panel.set_active(True)
        self.append(self.panel)
        self.entry = tui.Entry("Titel, Ort, Notiz …   (⏎ springen · strg+⏎ bearbeiten · ↑↓ wählen · esc zu)",
                               activate=self.go)
        self.entry.set_size_request(560, -1)
        self.entry.connect("changed", self.on_changed)
        self.panel.body.append(hbox(label("/", "accent"), self.entry, spacing=8))
        self.rows_box = vbox(spacing=0)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                         max_content_height=380, min_content_width=560, child=self.rows_box)
        self.panel.body.append(self.scroll)
        self.info = label("", "dim", wrap=True)
        self.panel.body.append(self.info)
        self.results, self.sel, self._id = [], 0, None
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.entry.add_controller(keys)

    # ----- Öffnen / Schließen -----
    def open(self):
        self.entry.set_text("")
        self.set_visible(True)
        self.refresh()
        GLib.idle_add(lambda: self.entry.grab_focus() and False)

    def close(self):
        self.set_visible(False)
        if self._id:
            GLib.source_remove(self._id)
            self._id = None
        self.app.focus_view()

    # ----- Suchen -----
    def on_changed(self, *_):
        if self._id:
            GLib.source_remove(self._id)
        self._id = GLib.timeout_add(120, self.refresh)        # entprellt: erst nach kurzer Tipp-Pause suchen

    def refresh(self):
        self._id = None
        q = self.entry.get_text().strip()
        self.results = self.app.store.search(q, limit=self.LIMIT)
        self.sel = 0
        tui.clear(self.rows_box)
        today = dt.date.today()
        for i, o in enumerate(self.results):
            self.rows_box.append(self.make_row(i, o, today))
        if not self.results:
            self.rows_box.append(label("nichts gefunden" if q else "keine kommenden Termine", "empty", xalign=0.5))
        n = len(self.results)
        self.info.set_label(("" if not q else f"{n} Treffer" + (" (die ersten " + str(self.LIMIT) + ")" if n >= self.LIMIT else ""))
                            if q else "die nächsten Termine – tippen zum Suchen")
        self.paint()
        return False

    def make_row(self, i, o, today):
        d = o["s"].date()
        rel = "heute" if d == today else "morgen" if d == today + dt.timedelta(days=1) else \
            "gestern" if d == today - dt.timedelta(days=1) else ""
        when = f"{WEEKDAYS[d.weekday()]} {d:%d.%m.}" + ("" if o.get("allday") else f" {o['s']:%H:%M}")
        row = Gtk.Button(hexpand=True)
        row.add_css_class("rowhead")
        loc = f" · {o['location']}" if o.get("location") else ""
        row.set_child(hbox(label(when, "dim", xalign=0), label(rel, "accent", xalign=0),
                           label((o.get("title") or "?") + loc, hexpand=True, ellipsize=True, xalign=0), spacing=10))
        row.get_child().get_first_child().set_width_chars(13)
        row.connect("clicked", lambda *_b, i=i: (setattr(self, "sel", i), self.go()))
        row.index = i
        return row

    def paint(self):
        c = self.rows_box.get_first_child()
        while c:
            (c.add_css_class if getattr(c, "index", -1) == self.sel else c.remove_css_class)("sel-row")
            c = c.get_next_sibling()
        self.scroll_to_sel()

    def scroll_to_sel(self):
        c, i = self.rows_box.get_first_child(), 0
        while c and getattr(c, "index", -1) != self.sel:
            c = c.get_next_sibling()
        if c is not None:
            adj = self.scroll.get_vadjustment()
            ok, rect = c.compute_bounds(self.rows_box)
            if ok:
                y, h = rect.get_y(), rect.get_height()
                if y < adj.get_value():
                    adj.set_value(y)
                elif y + h > adj.get_value() + adj.get_page_size():
                    adj.set_value(y + h - adj.get_page_size())

    # ----- Bedienung -----
    def on_key(self, ctrl, kv, code, state):
        if kv in (Gdk.KEY_Down, Gdk.KEY_Up):
            if self.results:
                self.sel = (self.sel + (1 if kv == Gdk.KEY_Down else -1)) % len(self.results)
                self.paint()
            return True
        if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.CONTROL_MASK:
            self.go(edit=True)
            return True
        return False

    def go(self, edit=False):
        if not self.results:
            return
        o = self.results[min(self.sel, len(self.results) - 1)]
        self.set_visible(False)
        app = self.app
        app.cursor = o["s"].date()
        app.focus_uid = o.get("uid")
        app.win.show_tab("day")
        app.redraw()
        if edit:
            app.edit(o)
        else:
            app.focus_view()
