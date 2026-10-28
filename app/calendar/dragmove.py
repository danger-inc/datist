# datist – Termine mit der Maus verschieben (Woche, Tag, Monat). Mixin für Cells (ui.py).
# Klick ohne Ziehen öffnet den Termin wie bisher; ab ~8 px Bewegung wird gezogen: das Ziel (Tag + Doppelstunde bzw.
# Monatsfeld) leuchtet, Loslassen verschiebt (Dauer bleibt). Auf einem Feld ohne Ziel passiert nichts.
import datetime as dt
import math

import gi
from gi.repository import Gdk, Gtk, PangoCairo

import raster
from raster import WEEKDAYS


class DragMixin:
    DRAG_PX = 8
    DRAG_VIEWS = ("week", "day", "month")

    def init_drag(self):
        self._press, self.drag_target = None, None
        g = Gtk.GestureDrag(button=1)
        g.connect("drag-begin", self._d_begin)
        g.connect("drag-update", self._d_update)
        g.connect("drag-end", self._d_end)
        self.add_controller(g)

    def region_at(self, x, y, kinds):
        """Oberster Bereich der gewünschten Arten an Pixelposition (x, y): (c, r, w, h, payload) | None."""
        cw, ch = self.metrics()
        c, r = x / cw, y / ch
        for reg in reversed(self.regions):
            rc, rr, rw, rh, payload = reg
            if payload[0] in kinds and rc <= c < rc + rw and rr <= r < rr + rh:
                return reg
        return None

    def on_bottom_edge(self, reg, y):
        """Zeiger auf der untersten Zeile (Rahmen) eines Termins im Raster → Dauer ändern statt verschieben."""
        if self.view not in ("week", "day"):
            return False
        o = reg[4][1]
        if o.get("allday") or o["e"] - o["s"] >= dt.timedelta(hours=20) or reg[3] < 3:
            return False
        _, ch = self.metrics()
        return y / ch >= reg[1] + reg[3] - 1

    def click_owned_by_drag(self, hit, button):
        """Termin-Klicks mit der linken Taste behandelt die Zieh-Geste (Klick = Loslassen ohne Bewegung)."""
        return hit and hit[0] == "event" and button == 1 and self.view in self.DRAG_VIEWS

    # ----- Geste -----
    def _d_begin(self, gesture, x, y):
        self._press = None
        reg = self.region_at(x, y, ("event",))
        if reg and self.view in self.DRAG_VIEWS:
            self._press = {"hit": reg[4], "x0": x, "y0": y, "active": False, "resize": self.on_bottom_edge(reg, y)}

    def _d_update(self, gesture, dx, dy):
        p = self._press
        if not p:
            return
        if not p["active"]:
            if math.hypot(dx, dy) < self.DRAG_PX:
                return
            if self.app.store.is_readonly(p["hit"][1]):
                self._press = None
                self.app.win.say("nur lesbar – lässt sich nicht verschieben", error=True)
                return
            p["active"] = True
            self.set_cursor(Gdk.Cursor.new_from_name("grabbing"))
        self.drag_target = (self.resize_target_at(p["hit"][1], p["x0"] + dx, p["y0"] + dy) if p.get("resize")
                            else self.target_at(p["x0"] + dx, p["y0"] + dy))
        self.queue_draw()

    def _d_end(self, gesture, dx, dy):
        p, tgt = self._press, self.drag_target
        self._press, self.drag_target = None, None
        self.set_cursor(Gdk.Cursor.new_from_name("default"))
        self.queue_draw()
        if not p:
            return
        if not p["active"]:
            self.app.on_hit(self.view, p["hit"], 1, 1)          # war nur ein Klick
        elif tgt and p.get("resize"):
            self.app.resize_event(p["hit"][1], tgt)
        elif tgt:
            self.app.move_event(p["hit"][1], tgt)

    def target_at(self, x, y):
        """Ziel unter dem Zeiger: {"day", "ds" | None, "rect", "label"} oder None."""
        if self.view in ("week", "day"):
            reg = self.region_at(x, y, ("slot",))
            if reg:
                _, d, k = reg[4]
                return {"day": d, "ds": k, "rect": reg[:4],
                        "label": f"{WEEKDAYS[d.weekday()]} {d.day}.{d.month}. · {k + 1}. DS"}
            reg = self.region_at(x, y, ("day",))
            if reg:
                d = reg[4][1]
                return {"day": d, "ds": None, "rect": reg[:4], "label": f"{WEEKDAYS[d.weekday()]} {d.day}.{d.month}."}
            return None
        reg = self.region_at(x, y, ("day", "dayhead"))
        if reg:
            d = reg[4][1]
            return {"day": d, "ds": None, "rect": reg[:4], "label": f"{WEEKDAYS[d.weekday()]} {d.day}.{d.month}."}
        return None

    def resize_target_at(self, o, x, y):
        """Neues Ende: Ende der Doppelstunde unter dem Zeiger am Tag des Termins (nur nach unten, später als der Beginn)."""
        reg = self.region_at(x, y, ("slot",))
        if not reg or reg[4][1] != o["s"].date():
            return None
        k = reg[4][2]
        end = dt.datetime.combine(o["s"].date(), raster.ds_times(k + 1)[1])
        if end <= o["s"]:
            return None
        return {"day": o["s"].date(), "ds": k, "end": end, "rect": reg[:4], "label": f"bis {end:%H:%M} ({k + 1}. DS)"}

    # ----- Zielanzeige (am Ende von _draw) -----
    def draw_ghost(self, cr, cw, ch, layout):
        t = self.drag_target
        if not t:
            return
        c, r, w, h = t["rect"]
        col = self.app.pal.primary
        cr.set_source_rgba(*col, 0.22)
        cr.rectangle(c * cw, r * ch, w * cw, h * ch)
        cr.fill()
        cr.set_source_rgba(*col, 0.95)
        cr.set_line_width(2)
        cr.rectangle(c * cw + 1, r * ch + 1, w * cw - 2, h * ch - 2)
        cr.stroke()
        layout.set_font_description(self.font)
        layout.set_text(" → " + t["label"] + " ", -1)
        pw, ph = layout.get_pixel_size()
        x, y = c * cw + 2, r * ch + 2
        cr.set_source_rgba(*col, 1.0)
        cr.rectangle(x, y, pw, ph)
        cr.fill()
        cr.set_source_rgba(*self.app.pal.on_primary, 1.0)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)
