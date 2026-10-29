#!/usr/bin/env python3
# datist – TUI-Kalender im musicalist-Stil (Super+K). Ansichten Tag/Woche/Monat im DS-Raster der TU Berlin,
# Google-Kalender-Abgleich (gcal.py) mit Offline-Cache (store.py), Farben live aus matugen.
# Tasten: h/j/k/l bewegen, H/L Zeitraum, d/w/m Ansicht, t heute, n neu, a Schnelleingabe, ⏎ bearbeiten,
#         x löschen, Tab nächster Termin, g Datum, s abgleichen, ? Hilfe, Esc schließen.
import colorsys, copy, datetime as dt, math, os, re, sys, time
os.environ.setdefault("GSK_RENDERER", "gl")        # Vulkan lässt mit der Cursor-Spur Bilder aus (gemessen: 33 statt 17 ms)

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))           # rice-apps: tui, glass

try:                           # glibc: wenige malloc-Arenen, der Daemon bleibt schlank
    import ctypes
    ctypes.CDLL("libc.so.6").mallopt(-8, 2)        # M_ARENA_MAX
except (OSError, AttributeError):
    pass

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

import tui
from tui import label, hbox, vbox, esc
import swipe
import raster
from raster import DS, TZ, WEEKDAYS, WEEKDAYS_LONG, MONTHS, CATS, CAT_NAMES, CAT_SHORT
import rrule
import store as st
import gcal
import holidays
import quickparse
import reminders
import searchview
import agendaview
import barstate
import deskcard

os.environ.pop("LD_PRELOAD", None)    # gtk4-layer-shell ist schon geladen – Kindprozesse (Browser) sollen es nicht erben
from zoneinfo import ZoneInfo
from dragmove import DragMixin
from acctpanels import AcctMixin

APP_ID = "de.invincible.Datist"
SYNC_EVERY = 300          # Sekunden
TONES = [("primary", "Primär"), ("analog", "Analog −60°"), ("analog2", "Analog +60°"), ("secondary", "Sekundär"),
         ("tertiary", "Tertiär"), ("complement", "Komplementär"),
         ("triad", "Triade"), ("triad2", "Triade 2"), ("alert", "Signal"), ("color2", "Grün"), ("color3", "Gelb"),
         ("color4", "Blau"), ("color5", "Magenta"), ("color6", "Cyan")]

CSS = """
.kw-badge { padding: 1px 7px; border-radius: 4px; margin-right: 4px; }
.kw-badge.even { background-color: @primary; color: @on_primary; }
.kw-badge.odd { background-color: @tertiary; color: @background; }
.sync-badge { color: @secondary; margin-right: 6px; }
.editor-card button.swatch { padding: 0; margin: 0; min-width: 0; min-height: 0; background: none;
    border: none; box-shadow: none; }
.editor-scrim { background-color: alpha(@background, 0.22); }
.editor-card { background-color: alpha(@background, 0.97); border-radius: 6px; padding: 4px 6px 10px 6px; }
.glass .editor-card { background-color: alpha(@background, 0.97); }
/* durchsichtige Fenster in der App (Konto → darstellung): Inhalt dahinter weichgezeichnet */
.editor-card.see-through, .glass .editor-card.see-through {
    background-color: alpha(@background, 0.55); backdrop-filter: blur(14px);
}
.editor-card.see-through.typing, .glass .editor-card.see-through.typing { backdrop-filter: none; background-color: alpha(@background, 0.9); }
.flabel { color: @secondary; min-width: 64px; }
button.ds { padding: 1px 7px; border: 1px solid alpha(@primary, 0.45); border-radius: 4px; background: none;
    box-shadow: none; min-height: 0; min-width: 0; color: @foreground; }
button.ds:hover { background-color: alpha(@primary, 0.18); }
button.rowhead.sel-row { background-color: alpha(@primary, 0.2); }
button.ds.on { background-color: @primary; color: @on_primary; border-color: @primary; }
.notes-box { background-color: alpha(@background, 0.45); border: 1px solid alpha(@primary, 0.45); border-radius: 4px;
    padding: 3px 8px; }
.notes-box textview, .notes-box textview text { background: none; color: @foreground; }
.quick { padding: 2px 14px 4px 14px; }
.swatch { min-width: 26px; }
.help { color: @foreground; }
"""


# =====================================================================
# Farben: matugen-Palette + daraus abgeleitete Komplementär-/Triadenfarben (OKLCH)
# =====================================================================
def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(rgb):
    r, g, b = (_lin(x) for x in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(A, B), math.degrees(math.atan2(B, A)) % 360


def from_oklch(L, C, H):
    for _ in range(30):     # Chroma senken, bis die Farbe in sRGB passt
        A, B = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
        l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
        m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
        s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3
        r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
        if all(-0.001 <= x <= 1.001 for x in (r, g, b)):
            break
        C *= 0.9
    return tuple(_gam(x) for x in (r, g, b))


# Die 11 Ereignisfarben von Google Kalender (colorId → Farbe)
GOOGLE_COLORS = {"1": "#7986cb", "2": "#33b679", "3": "#8e24aa", "4": "#e67c73", "5": "#f6bf26", "6": "#f4511e",
                 "7": "#039be5", "8": "#616161", "9": "#3f51b5", "10": "#0b8043", "11": "#d50000"}


GOOGLE_NAMES = {"1": "Lavendel", "2": "Salbei", "3": "Weintraube", "4": "Flamingo", "5": "Banane", "6": "Mandarine",
                "7": "Pfau", "8": "Graphit", "9": "Heidelbeere", "10": "Basilikum", "11": "Tomate"}


def _hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


_G_LCH = {k: to_oklch(_hex_rgb(v)) for k, v in GOOGLE_COLORS.items()}


def google_color(rgb):
    """Nächste Google-Farbe zu einer datist-Farbe (vor allem nach Farbton, graue Töne → Graphit)."""
    L, C, H = to_oklch(rgb)
    if C < 0.035:
        return "8"
    best, score = None, 9
    for k, (l2, c2, h2) in _G_LCH.items():
        if k == "8":
            continue
        dh = abs((H - h2 + 180) % 360 - 180) / 180
        sc = dh + 0.35 * abs(L - l2) + 0.5 * abs(min(C, 0.2) - min(c2, 0.2))
        if sc < score:
            best, score = k, sc
    return best


class Palette:
    _cache = (None, None)       # (Farbtabelle, Palette): wird bei jedem Neuladen der Farben ein neues Objekt

    def __new__(cls):
        c = tui.colors()
        key = tuple((k, v.red, v.green, v.blue) for k, v in c.items())     # Farbtabelle wird beim Neuladen verändert
        if cls._cache[0] != key:
            self = super().__new__(cls)
            self._build(c)
            cls._cache = (key, self)
        return cls._cache[1]

    def __init__(self):
        pass

    def _build(self, c):

        def rgb(name, fb):
            v = c.get(name)
            return (v.red, v.green, v.blue) if v else fb
        self.fg = rgb("foreground", (0.94, 0.87, 0.84))
        self.bg = rgb("background", (0.1, 0.07, 0.05))
        self.surface = rgb("surface_container", (0.15, 0.12, 0.1))
        p = rgb("primary", (1.0, 0.71, 0.56))
        self.on_primary = rgb("on_primary", (0.32, 0.13, 0.0))
        L, C, H = to_oklch(p)
        C = max(C, 0.09)
        # Typen-Farben: gleichmäßig um den Primärton verteilt (gleiche Helligkeit/Sättigung wie matugen-primary)
        used = [H, H - 60, H + 60, H + 120, H + 180]
        # Signalfarbe (Prüfung): roter Bereich, möglichst weit weg von allen anderen Tönen
        dist = lambda a, b: abs((a - b + 180) % 360 - 180)
        alert_h = max((25, 5, 345, 40, 55, 330), key=lambda h: min(dist(h, u) for u in used))
        self.tones = {"primary": p, "secondary": rgb("secondary", p), "tertiary": rgb("tertiary", p),
                      "analog": from_oklch(L, C, H - 60), "analog2": from_oklch(L, C, H + 60),
                      "complement": from_oklch(L, C, H + 180), "triad": from_oklch(L, C, H + 120),
                      "triad2": from_oklch(L, C, H + 240),
                      "alert": from_oklch(max(L, 0.68), max(C, 0.16), alert_h),
                      "outline": rgb("outline", self.fg)}
        for i in range(1, 7):
            self.tones[f"color{i}"] = rgb(f"color{i}", p)
        self.cat_tone = {k: src for k, _, _, src in CATS}

    def cat(self, cat, tone=None):
        if tone and tone in self.tones:
            return self.tones[tone]
        return self.tones.get(self.cat_tone.get(cat, "outline"), self.fg)

    @property
    def primary(self):
        return self.tones["primary"]


# =====================================================================
# Zeichenraster: alles in Zeichenzellen (Monospace) wie im Terminal
# =====================================================================
class Cells(DragMixin, Gtk.DrawingArea):
    def __init__(self, app, view):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.app, self.view = app, view
        self.set_draw_func(self._draw)
        self.regions = []
        self.ops = []
        self.off, self.clip = 0, None          # Zeilen-Verschiebung und sichtbarer Bereich (für Scrollen)
        self._acc = 0.0
        click = Gtk.GestureClick()
        click.connect("pressed", self._click)
        self.add_controller(click)
        self.init_drag()
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._scroll)
        scroll.connect("scroll-end", lambda *_: setattr(self, "_acc", 0.0))
        self.add_controller(scroll)
        self.set_cursor(Gdk.Cursor.new_from_name("default"))
        self._font_size = None


    def _scroll(self, ctrl, dx, dy):
        # Touchpads schicken viele kleine Schritte – sammeln, erst ab einer Raste weitergeben
        step = 1.0 if ctrl.get_unit() == Gdk.ScrollUnit.WHEEL else 45.0
        self._acc += dy / step
        n = int(self._acc)
        if n:
            self._acc -= n
            self.app.on_scroll(self.view, n)
        return True


    def metrics(self):
        size = self.app.store.settings.get("font_size", 10)
        if size != self._font_size:
            self._font_size = size
            self.font = Pango.FontDescription.from_string(f"{tui.FONT} Bold {size}")
            self.font_n = Pango.FontDescription.from_string(f"{tui.FONT} {size}")
            lay = self.create_pango_layout("M")
            lay.set_font_description(self.font)
            ink, log = lay.get_extents()
            self.cw = log.width / Pango.SCALE
            self.ch = math.ceil(log.height / Pango.SCALE)
        return self.cw, self.ch

    # ----- Zeichen-Befehle (von den Ansichten benutzt) -----
    def text(self, c, r, s, color, alpha=1.0, bold=True, maxw=None, bg=None):
        r += self.off
        if self.clip and not (self.clip[0] <= r < self.clip[1]):
            return
        if maxw is not None:
            if maxw <= 0:
                return
            if len(s) > maxw:
                s = s[:max(0, maxw - 1)] + "…"
        if bg is not None:
            self.ops.append(("f", c, r, len(s), 1, bg[0], bg[1]))
        self.ops.append(("t", c, r, s, color, alpha, bold))


    def fill(self, c, r, w, h, color, alpha=1.0):
        r += self.off
        if self.clip:
            top, bot = max(r, self.clip[0]), min(r + h, self.clip[1])
            r, h = top, bot - top
        if w > 0 and h > 0:
            self.ops.append(("f", c, r, w, h, color, alpha))


    def box(self, c, r, w, h, color, alpha=1.0, title=None, title_color=None, rounded=False, right=None, heavy=False):
        """Rahmen; title/right stehen in der oberen Linie (ohne Hintergrundfläche, passt auch im Glas-Modus)."""
        if w < 2 or h < 2:
            return
        if rounded:
            tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"
        elif heavy:
            tl, tr, bl, br, hz, vt = "┏", "┓", "┗", "┛", "━", "┃"
        else:
            tl, tr, bl, br, hz, vt = "┌", "┐", "└", "┘", "─", "│"
        inner = w - 2
        t = f" {title} " if title else ""
        rt = f" {right} " if right else ""
        if len(t) + len(rt) + 3 > inner:          # zu schmal: rechte Angabe weg, dann Titel kürzen
            rt = ""
        if len(t) + 2 > inner:
            t = (t[:inner - 4] + "… ") if inner >= 8 else ""
        mid = inner - 2 - len(t) - len(rt)
        if mid < 0:
            t = rt = ""
            mid = inner - 2
        top = tl + hz + " " * len(t) + hz * mid + " " * len(rt) + hz + tr if inner >= 2 else tl + hz * inner + tr
        self.text(c, r, top, color, alpha)
        if t:
            self.text(c + 2, r, t, title_color or color, 1.0)
        if rt:
            self.text(c + w - 2 - len(rt), r, rt, color, max(alpha, 0.8))
        for i in range(1, h - 1):
            self.text(c, r + i, vt, color, alpha)
            self.text(c + w - 1, r + i, vt, color, alpha)
        self.text(c, r + h - 1, bl + hz * inner + br, color, alpha)


    def hline(self, c, rf, w, color, alpha=1.0, width=2.0, dot=False):
        """Feine Linie bei Zeile rf (Bruchteil erlaubt) über dem Text – z. B. die Jetzt-Linie."""
        rf += self.off
        if self.clip and not (self.clip[0] <= rf < self.clip[1]):
            return
        self.ops.append(("l", c, rf, w, color, alpha, width, dot))

    def erase(self, c, r, w):
        """Schon gesetzte Texte, die in Zeile r zwischen c und c+w beginnen, wieder entfernen (Überschreiben)."""
        r += self.off
        self.ops = [op for op in self.ops if not (op[0] == "t" and op[2] == r and c <= op[1] < c + w)]

    def region(self, c, r, w, h, payload):
        r += self.off
        if self.clip:
            top, bot = max(r, self.clip[0]), min(r + h, self.clip[1])
            r, h = top, bot - top
        if h > 0 and w > 0:
            self.regions.append((c, r, w, h, payload))
    def _draw(self, _area, cr, width, height):
        self.app.pal = Palette()
        cw, ch = self.metrics()
        cols, rows = int(width // cw), int(height // ch)
        self.ops, self.regions = [], []
        self.grid = (cols, rows)
        try:
            self.app.render(self.view, self, cols, rows)
        except Exception as e:  # noqa: BLE001 – Fehler sichtbar machen statt leerem Fenster
            import traceback
            traceback.print_exc()
            self.ops = [("t", 1, 1, f"Fehler beim Zeichnen: {e}", (1, 0.4, 0.4), 1, True)]
        layout = self.create_pango_layout("")
        for op in self.ops:
            if op[0] == "f":
                _, c, r, w, h, color, a = op
                cr.set_source_rgba(*color, a)
                cr.rectangle(c * cw, r * ch, w * cw, h * ch)
                cr.fill()
        for op in self.ops:
            if op[0] == "t":
                _, c, r, s, color, a, bold = op
                layout.set_font_description(self.font if bold else self.font_n)
                layout.set_text(s, -1)
                cr.set_source_rgba(*color, a)
                cr.move_to(c * cw, r * ch)
                PangoCairo.show_layout(cr, layout)
        for op in self.ops:
            if op[0] == "l":
                _, c, rf, w, color, a, lw, dot = op
                y = round(rf * ch) + (0.5 if lw % 2 else 0)
                cr.set_source_rgba(*color, a)
                cr.set_line_width(lw)
                cr.move_to(c * cw, y)
                cr.line_to((c + w) * cw, y)
                cr.stroke()
                if dot:
                    cr.arc(c * cw, y, lw * 2.2, 0, 2 * math.pi)
                    cr.fill()
        self.draw_ghost(cr, cw, ch, layout)

    def _click(self, gesture, n, x, y):
        self.grab_focus()
        cw, ch = self.metrics()
        c, r = x / cw, y / ch
        hit = None
        for rc, rr, rw, rh, payload in reversed(self.regions):   # zuletzt gezeichnet = oben
            if rc <= c < rc + rw and rr <= r < rr + rh:
                hit = payload
                break
        if hit and self.click_owned_by_drag(hit, gesture.get_current_button()):
            return                                  # Termin: die Zieh-Geste entscheidet (Klick oder Verschieben)
        if hit:
            self.app.on_hit(self.view, hit, n, gesture.get_current_button())


class WrapLayout(Gtk.LayoutManager):
    """Kinder nebeneinander, bei Platzmangel in die nächste Zeile (für schmale Fenster)."""

    def __init__(self, spacing=8, row_spacing=4):
        super().__init__()
        self.spacing, self.row_spacing = spacing, row_spacing

    def do_get_request_mode(self, widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def kids(self, widget):
        c = widget.get_first_child()
        while c:
            if c.should_layout():
                yield c
            c = c.get_next_sibling()

    def rows(self, widget, width):
        rows, cur, x = [], [], 0
        for c in self.kids(widget):
            w = c.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            if cur and x + self.spacing + w > width:
                rows.append(cur)
                cur, x = [], 0
            x += (self.spacing if cur else 0) + w
            cur.append((c, min(w, width)))
        if cur:
            rows.append(cur)
        return rows

    def do_measure(self, widget, orientation, for_size):
        kids = list(self.kids(widget))
        if orientation == Gtk.Orientation.HORIZONTAL:
            mins = [c.measure(orientation, -1)[0] for c in kids]
            nats = [c.measure(orientation, -1)[1] for c in kids]
            return max(mins or [0]), sum(nats) + self.spacing * max(0, len(kids) - 1), -1, -1
        width = for_size if for_size > 0 else 10 ** 6
        h = 0
        for i, row in enumerate(self.rows(widget, width)):
            h += max(c.measure(Gtk.Orientation.VERTICAL, w)[1] for c, w in row) + (self.row_spacing if i else 0)
        return h, h, -1, -1

    def do_allocate(self, widget, width, height, baseline):
        y = 0
        for row in self.rows(widget, width):
            rh = max(c.measure(Gtk.Orientation.VERTICAL, w)[1] for c, w in row)
            x = 0
            for c, w in row:
                r = Gdk.Rectangle()
                r.x, r.y, r.width, r.height = int(x), int(y), int(w), int(rh)
                c.size_allocate(r, -1)
                x += w + self.spacing
            y += rh + self.row_spacing


def wrapbox(*children, spacing=8):
    b = Gtk.Box(hexpand=True)
    b.set_layout_manager(WrapLayout(spacing=spacing))
    for c in children:
        if c is not None:
            b.append(c)
    return b


# =====================================================================
# Editor
# =====================================================================
class ToneSwatches(Gtk.Box):
    """Farbwahl als Kacheln (gleiche Schnittstelle wie tui.Select: options, current, set_options).
    Überfahren zeigt die Farbe sofort in der Vorschau des Editors (on_hover)."""
    SIZE = 18

    def __init__(self, app, callback, on_hover):
        super().__init__(spacing=3, valign=Gtk.Align.CENTER)
        self.app, self.callback, self.on_hover = app, callback, on_hover
        self.options, self.current, self.hover = None, None, None
        self.btns = {}
        self.name = label("", "dim")
        self.name.set_margin_start(6)

    def cat_color(self, pal):
        ed = self.app.editor if hasattr(self.app, "editor") else None
        return pal.cat(ed.cat.current if ed else None)

    def set_options(self, options, current):
        if options != self.options:
            self.options = list(options)
            tui.clear(self)
            self.btns = {}
            for oid, text in self.options:
                da = Gtk.DrawingArea(content_width=self.SIZE, content_height=self.SIZE)
                da.set_draw_func(self._draw, oid)
                b = Gtk.Button(child=da, tooltip_text=text, focus_on_click=False)
                b.add_css_class("swatch")
                b.connect("clicked", self._pick, oid)
                mo = Gtk.EventControllerMotion()
                mo.connect("enter", lambda *_a, o=oid: self._hover(o))
                mo.connect("leave", lambda *_a: self._hover(None))
                b.add_controller(mo)
                self.append(b)
                self.btns[oid] = da
            self.append(self.name)
        self.current = current
        self.refresh()

    def refresh(self):
        for da in self.btns.values():
            da.queue_draw()
        oid = self.hover if self.hover is not None else self.current
        self.name.set_label(next((t for o, t in self.options or [] if o == oid), ""))

    def _hover(self, oid):
        self.hover = oid
        self.refresh()
        self.on_hover()

    def _pick(self, _b, oid):
        if oid != self.current:
            self.callback(oid)

    def _draw(self, _da, cr, w, h, oid):
        pal = Palette()
        col = pal.tones.get(oid) if oid else self.cat_color(pal)
        sel = oid == (self.current or "")
        cr.set_line_width(1.5)
        if sel or oid == self.hover:                   # Ring um die gewählte Farbe
            cr.set_source_rgba(*pal.fg, 1.0 if sel else 0.5)
            cr.rectangle(0.75, 0.75, w - 1.5, h - 1.5)
            cr.stroke()
        cr.set_source_rgb(*col)
        if oid:
            cr.rectangle(3.5, 3.5, w - 7, h - 7)
            cr.fill()
        else:                                          # „auto“: Rahmen in Typ-Farbe mit Punkt
            cr.rectangle(4, 4, w - 8, h - 8)
            cr.stroke()
            cr.arc(w / 2, h / 2, 2, 0, 2 * math.pi)
            cr.fill()


class Editor(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.app = app
        self.add_css_class("editor-card")
        self.panel = tui.Panel("termin")
        self.panel.set_active(True)
        # in kleinen Fenstern scrollt der Editor statt abgeschnitten zu werden
        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                           child=self.panel)
        self.append(self.scroller)
        b = self.panel.body
        self.ev, self.orig, self.master, self.anchor = None, None, None, None
        self.rep_ok = True
        self.cat_manual = False

        def row(name, *ws, wrap=False):
            r = hbox(label(name, "flabel"), wrapbox(*ws) if wrap else None, *([] if wrap else ws), spacing=8)
            b.append(r)
            return r
        self.title = tui.Entry("Titel, z. B. V Analysis", activate=self.save)
        self.title.connect("changed", self.on_title)
        row("titel", self.title)
        self.cat = tui.Select(self.on_cat)
        self.tone = ToneSwatches(app, self.on_tone, self.show_preview)
        self.cal = tui.Select(self.on_cal, max_chars=22)
        row("typ", self.cat, self.cal, wrap=True)
        row("farbe", self.tone)
        # Vorschau: so erscheint der Termin in Woche / Monat (und welche Farbe Google bekommt)
        self.preview = Cells(app, "preview")
        self.preview.set_can_target(False)
        self.preview.set_focusable(False)
        self.preview.set_vexpand(False)
        row("", self.preview)
        self.date = tui.Entry("Datum", width=14, activate=self.save)
        self.date.connect("changed", lambda *_: self.update_hint())
        self.date_to = tui.Entry("bis: gleicher Tag", width=16, activate=self.save)
        self.date_to.set_tooltip_text("mehrtägig: letzter Tag (z. B. fr, +2, 23.10.) – leer = gleicher Tag")
        self.date_to.connect("changed", lambda *_: self.update_hint())
        self.date_hint = label("", "dim", ellipsize=True, hexpand=True)
        row("datum", self.date, hbox(label("bis", "dim"), self.date_to, spacing=6), self.date_hint, wrap=True)
        self.ds_btns = []
        dsbox = hbox(spacing=4)
        for n, a, e in DS:
            btn = Gtk.Button(label=str(n), tooltip_text=f"{n}. DS {a[0]:02d}:{a[1]:02d}–{e[0]:02d}:{e[1]:02d} "
                                                         f"(Alt+{n}; Umschalt+Klick: bis hier)")
            btn.add_css_class("ds")
            ctl = Gtk.GestureClick()
            ctl.connect("pressed", lambda g, nn, x, y, k=n: self.pick_ds(
                k, extend=bool(g.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)))
            btn.add_controller(ctl)
            dsbox.append(btn)
            self.ds_btns.append(btn)
        row("ds", dsbox, wrap=True)
        self.t_from = tui.Entry("von", width=6, activate=self.save)
        self.t_to = tui.Entry("bis", width=6, activate=self.save)
        for e in (self.t_from, self.t_to):
            e.connect("changed", lambda *_: (self.sync_ds(), self.preview.queue_draw()))
        self.allday = tui.Check("ganztägig", callback=lambda on: self.on_allday(on))
        row("zeit", hbox(self.t_from, label("–", "dim"), self.t_to, spacing=6), self.allday, wrap=True)
        self.remind = tui.Entry("", width=16, activate=self.save)
        self.remind.set_tooltip_text("Meldung vor dem Termin: 10, 30 min, 2 h, 1 tag, zum beginn, keine – leer = Standard")
        self.remind_pick = tui.Select(lambda v: self.remind.set_text(v), tooltip="Vorlauf wählen", max_chars=1)
        self.remind_pick.set_options([("", "standard"), ("keine", "keine"), ("zum beginn", "zum beginn")] +
                                     [(reminders.fmt_lead(m), reminders.fmt_lead(m))
                                      for m in (5, 10, 15, 30, 60, 120, 1440)], None)
        self.remind_pick.lbl.set_label("")
        row("erinnerung", self.remind, self.remind_pick, wrap=True)
        self.tz = tui.Entry("", width=22, activate=self.save)
        self.tz.set_tooltip_text("Zeitzone des Termins, z. B. America/New_York – leer = deine Zeit. "
                                 "Die Uhrzeiten oben gelten dann in dieser Zone.")
        self.tz.connect("changed", lambda *_: self.update_tz_hint())
        self.tz_pick = tui.Select(lambda v: self.tz.set_text(v), tooltip="häufige Zeitzonen", max_chars=1)
        self.tz_pick.set_options([("", "lokal")] + [(z, z) for z in (
            "UTC", "Europe/London", "Europe/Paris", "Europe/Istanbul", "America/New_York", "America/Chicago",
            "America/Los_Angeles", "Asia/Dubai", "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney")], None)
        self.tz_pick.lbl.set_label("")
        self.tz_hint = label("", "dim", hexpand=True, ellipsize=True)
        self.tz_row = row("zeitzone", self.tz, self.tz_pick, self.tz_hint, wrap=True)
        self.guests = tui.Entry("anna@example.org, ben@example.org", activate=self.save)
        self.guest_hint = label("", "dim", wrap=True)
        self.guest_row = row("gäste", self.guests)
        self.guest_hint_row = row("", self.guest_hint)
        self.meet_chk = tui.Check("Google Meet-Link erstellen", False,
                                  tooltip="Beim Speichern legt Google einen Meet-Link am Termin an")
        self.meet_lbl = label("", "dim", ellipsize=True, hexpand=True)
        self.meet_open = tui.Button("öffnen", lambda: self.meet_url and Gio.AppInfo.launch_default_for_uri(self.meet_url, None))
        self.meet_copy = tui.Button("kopieren", self.copy_meet)
        self.meet_row = row("meet", self.meet_chk, self.meet_lbl, self.meet_open, self.meet_copy, wrap=True)
        self.send_chk = tui.Check("Einladungen / Änderungen an Gäste senden (nur dieses Speichern)", False,
                                  tooltip="Standard: es geht keine Mail raus. Hier anhaken, wenn Google die Gäste "
                                          "benachrichtigen soll.")
        self.send_row = row("einladung", self.send_chk, wrap=True)
        self.meet_url, self.guest_orig, self.guest_org = "", [], True
        self.bar_chk = tui.Check("in der Waybar zeigen", True, self.on_bar_toggle,
                                 tooltip="Aus: dieser Termin (bei Serien die ganze Serie) erscheint nicht als nächster Termin in der Leiste")
        self.bar_row = row("waybar", self.bar_chk, wrap=True)
        self._bar_o = None
        self.loc = tui.Entry("Hörsaal, z. B. MA/041", activate=self.save)
        self.loc_pick = tui.Select(lambda v: self.loc.set_text(v), tooltip="zuletzt benutzte Orte", max_chars=1)
        row("ort", self.loc, self.loc_pick)
        self.link = tui.Entry("ISIS / BigBlueButton / Zoom …", activate=self.save)
        row("link", self.link, tui.Button("öffnen", self.open_link))
        self.notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False, hexpand=True)
        nb = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=52, max_content_height=110,
                                propagate_natural_height=True, child=self.notes, hexpand=True)
        nb.add_css_class("notes-box")
        row("notiz", nb)
        self.sem = tui.Check("ganzes semester", False, self.on_sem,
                             tooltip="1× pro Woche über die ganze Vorlesungszeit – ohne Feiertage und Pausen")
        self.sem_week = tui.Select(self.on_sem_week, max_chars=28)
        self.sem_week.set_options(raster.WEEKS, "all")
        self.sem_plan = None
        row("semester", self.sem, self.sem_week, wrap=True)
        self.rep = tui.Select(self.on_rep, max_chars=32)
        self.until = tui.Entry("bis (Datum)", width=12)
        self.until.connect("changed", lambda *_: self.update_hint())
        row("wdh.", self.rep, hbox(label("bis", "dim"), self.until, spacing=6), wrap=True)
        self.custom = tui.Entry("RRULE, z. B. FREQ=WEEKLY;BYDAY=MO,WE;COUNT=10")
        self.custom.connect("changed", lambda *_: self.update_hint())
        self.custom_row = row("regel", self.custom)
        self.rep_hint = label("", "dim", wrap=True)
        b.append(self.rep_hint)
        self.scope_inst = tui.Check("nur dieser termin", True, lambda on: self.set_scope("instance"))
        self.scope_series = tui.Check("ganze serie", False, lambda on: self.set_scope("series"))
        self.scope_row = row("serie", self.scope_inst, self.scope_series, wrap=True)
        self.msg = label("", "warn", wrap=True)
        b.append(self.msg)
        self.del_btn = tui.Button("löschen", self.delete, danger=True)
        self.keys_hint = label("1–7 ds (alt+1–7 beim tippen) · strg+⏎ speichern · esc abbrechen", "dim")
        btns = wrapbox(tui.Button("speichern ⏎", self.save), self.del_btn, tui.Button("abbrechen", self.close),
                       self.keys_hint)
        btns.set_margin_top(6)
        b.append(btns)
        self.scope = "single"
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

    # ----- Öffnen -----
    def open(self, ev=None, day=None, ds=None, orig=None):
        app = self.app
        self.orig = orig
        self.master = None
        # Datum der angeklickten Instanz: bei „ganze serie“ wird die Serie relativ dazu verschoben
        self.anchor = orig["s"].date() if orig and orig.get("s") else None
        new = ev is None
        if new:
            day = day or dt.date.today()
            a, e = raster.ds_times(ds or 1)
            ev = {"cal": app.store.default_cal(), "title": "", "allday": False,
                  "start": st.iso(dt.datetime.combine(day, a)), "end": st.iso(dt.datetime.combine(day, e)),
                  "location": "", "link": "", "notes": "", "cat": "", "tone": "", "rrule": None}
        self.ev = copy.deepcopy(ev)
        self.ro = (not new) and app.store.is_readonly(ev)
        self.cat_manual = bool(ev.get("cat")) and not new
        self.panel.set_title("neuer termin" if new else "termin bearbeiten")
        self.del_btn.set_visible(not new)
        self.fill(self.ev)
        is_series = bool(orig and (orig.get("series") or orig.get("rrule")))
        self.scope_row.set_visible(is_series)
        self.scope = "instance" if is_series else "single"
        self.scope_inst.set_active(True)
        self.scope_series.set_active(False)
        self.msg.set_label("🔒 nur lesbar (Abo oder Kalender ohne Schreibrecht) – esc schließt" if self.ro else "")
        self.del_btn.set_visible(not new and not self.ro)
        self.set_visible(True)
        self.opened = self.form()
        GLib.idle_add(lambda: (self.title.grab_focus(), self.title.set_position(-1)) and False)

    def dismiss(self):
        """Wegklicken: unverändert → einfach zu; geändert → speichern (bei Fehler bleibt er offen)."""
        if getattr(self, "ro", False):
            self.close()
            return
        now, was = self.form(), dict(getattr(self, "opened", None) or {})
        now.pop("cat_manual", None)
        was.pop("cat_manual", None)
        if now == was or not now["title"].strip() and not was.get("title", "").strip():
            self.close()
        else:
            self.save()

    def fill(self, ev):
        app = self.app
        self.title.set_text(ev.get("title", ""))
        self.cat.set_options([(k, f"{s} {n}") for k, n, s, _ in CATS], ev.get("cat") or raster.guess_cat(ev.get("title")))
        self.tone.hover = None
        self.tone.set_options([("", "auto (typ)")] + TONES, ev.get("tone") or "")
        cals = app.store.writable()
        if ev.get("gid") or ev.get("uid", "").startswith("local-") or app.store.is_readonly(ev):
            cals = [c for c in app.store.all_calendars() if c["id"] == ev["cal"]] or cals   # Kalender nicht wechselbar
        self.cal.set_options([(c["id"], ("◆ " if c["id"] == "local" else "◇ ") + c["name"]) for c in cals], ev["cal"])
        allday = bool(ev.get("allday"))
        s, e = st.parse_when(ev["start"], allday), st.parse_when(ev["end"], allday)
        tzname = None if allday else ev.get("tz")
        if tzname:                                       # Termin in fremder Zeitzone: Zeiten in dieser Zone zeigen
            try:
                zone = ZoneInfo(tzname)
                s = dt.datetime.fromisoformat(ev["start"]).astimezone(zone).replace(tzinfo=None)
                e = dt.datetime.fromisoformat(ev["end"]).astimezone(zone).replace(tzinfo=None)
            except (ValueError, KeyError):
                tzname = None
        if allday:
            e -= dt.timedelta(days=1)
        self.date.set_text(raster.fmt_date(s.date()))
        last = e.date()
        if not allday and e.time() == dt.time() and last == s.date() + dt.timedelta(days=1):
            last = s.date()                       # bis 24:00 zählt noch als derselbe Tag
        self.date_to.set_text(raster.fmt_date(last) if last > s.date() else "")
        self.t_from.set_text("" if allday else f"{s:%H:%M}")
        self.t_to.set_text("" if allday else f"{e:%H:%M}")
        self.allday.set_active(allday)
        self.on_allday(allday)
        self.tz.set_text(tzname or "")
        self.meet_url = ev.get("meet") or ""
        self.meet_chk.set_active(False)
        self.meet_lbl.set_label(self.meet_url.replace("https://", "") if self.meet_url else "")
        self.guest_orig = [a for a in (ev.get("attendees") or [])]
        self.guest_org = bool(ev.get("organizer_self", True))
        self.guests.set_text(", ".join(a["email"] for a in self.guest_orig if not a.get("self")))
        self.send_chk.set_active(False)
        self._bar_o = None if not ev.get("uid") else {**ev, "s": None}        # neuer Termin: erst nach dem Speichern
        self.bar_chk.set_active(not (self._bar_o and barstate.is_hidden(self._bar_o)))
        self.bar_chk.set_sensitive(self._bar_o is not None)
        self.sync_google_rows()
        self.update_tz_hint()
        self.remind.set_text(reminders.fmt_lead(ev.get("remind")))
        dflt = reminders.fmt_lead(app.reminders.default_lead()) if getattr(app, "reminders", None) else "10 min"
        self.remind.set_placeholder_text(f"standard ({dflt})")
        self.loc.set_text(ev.get("location", ""))
        locs = app.store.recent_locations()
        self.loc_pick.set_options([(l, l) for l in locs], None)
        self.loc_pick.lbl.set_label("")
        self.loc_pick.set_visible(bool(locs))
        self.link.set_text(ev.get("link", ""))
        self.notes.get_buffer().set_text(ev.get("notes", ""))
        rule = ev.get("rrule")
        pid = rrule.preset_of(rule, s) if rule else "none"
        self.rep.set_options(rrule.PRESETS, pid)
        u = rrule.until_of(rule) if rule else None
        self.until.set_text(f"{u:%d.%m.%Y}" if u else "")
        self.custom.set_text(rule or "")
        self.custom_row.set_visible(pid == "custom")
        # Wiederholung nur bei neuen Terminen, lokalen Serien oder 'ganze Serie' änderbar
        self.rep_ok = not ev.get("series")
        sem = ev.get("sem") or {}
        self.sem.set_active(bool(sem))
        self.sem_week.set_options(raster.WEEKS, sem.get("week", "all"))
        self.sem_sensitive()
        self.sync_ds()
        self.update_hint()
        self.show_preview()

    # ----- Felder -----
    def show_preview(self, *_):
        cw, ch = self.preview.metrics()
        self.preview.set_content_height(int(math.ceil(ch * 5)))
        self.preview.queue_draw()
        self.tone.refresh()

    def preview_event(self):
        """Termin aus den Feldern für die Vorschau (ohne Prüfungen, Lücken mit Standardwerten)."""
        d = self.day() or dt.date.today()
        try:
            a = raster.parse_time(self.t_from.get_text())
            e = raster.parse_time(self.t_to.get_text())
        except ValueError:
            a, e = raster.ds_times(1)
        s, f = dt.datetime.combine(d, a), dt.datetime.combine(d, e)
        if f <= s:
            f = s + dt.timedelta(minutes=90)
        tone = self.tone.hover if self.tone.hover is not None else self.tone.current
        return {"uid": "preview", "title": self.title.get_text().strip() or "(ohne Titel)",
                "cat": self.cat.current, "tone": tone or "", "location": self.loc.get_text().strip(),
                "link": "", "s": s, "e": f, "allday": self.allday.active}

    def render_preview(self, g, cols, rows):
        app, p = self.app, self.app.pal
        o = self.preview_event()
        col = p.cat(o["cat"], o["tone"])
        bw = min(cols, 26)
        g.text(0, 0, "woche", p.fg, 0.45)
        app.draw_event(g, dict(o, location=""), 0, 1, bw, 4)
        x = bw + 2
        if cols - x < 14:
            return
        w = cols - x
        g.text(x, 0, "monat", p.fg, 0.45)
        t = ("" if o["allday"] else f"{o['s']:%H:%M} ") + o["title"]
        g.text(x, 1, "▌", col)
        g.text(x + 1, 1, t, p.fg, 0.85, maxw=min(w, 22) - 1)
        gid = google_color(col)
        g.text(x, 3, "google", p.fg, 0.45)
        g.text(x, 4, "■", _hex_rgb(GOOGLE_COLORS[gid]))
        g.text(x + 2, 4, GOOGLE_NAMES[gid].lower(), p.fg, 0.75, maxw=w - 2)

    def on_title(self, *_):
        if not self.cat_manual:
            self.cat.set_options(self.cat.options, raster.guess_cat(self.title.get_text()))
        self.show_preview()

    def on_cat(self, v):
        self.cat_manual = True
        self.cat.set_options(self.cat.options, v)
        self.show_preview()

    def on_tone(self, v):
        self.tone.set_options(self.tone.options, v)
        self.show_preview()

    def on_cal(self, v):
        self.cal.set_options(self.cal.options, v)
        self.sync_google_rows()

    def sem_sensitive(self):
        on = self.sem.active
        self.sem.set_sensitive(self.rep_ok)
        self.sem_week.set_sensitive(self.rep_ok and on)
        for w in (self.rep, self.until, self.custom):
            w.set_sensitive(self.rep_ok and not on)

    def on_sem(self, on):
        self.sem_sensitive()
        self.update_hint()

    def on_sem_week(self, v):
        self.sem_week.set_options(self.sem_week.options, v)
        self.update_hint()

    def on_allday(self, on):
        for w in (self.t_from, self.t_to, *self.ds_btns):
            w.set_sensitive(not on)

    def on_rep(self, v):
        self.rep.set_options(self.rep.options, v)
        self.custom_row.set_visible(v == "custom")
        if v == "custom" and not self.custom.get_text():
            self.custom.set_text("FREQ=WEEKLY;BYDAY=" + rrule.DAYS[self.day().weekday()])
        self.update_hint()

    def day(self):
        try:
            return raster.parse_date(self.date.get_text())
        except ValueError:
            return None

    def day_to(self):
        """Letzter Tag (mehrtägig) oder None; relative Angaben (fr, +2) zählen ab dem Beginn."""
        t = self.date_to.get_text().strip()
        d = self.day()
        if not t or d is None:
            return None
        try:
            return raster.parse_date(t, d)
        except ValueError:
            raise ValueError(f"„bis“ nicht erkannt: {t}")

    def eff_day(self):
        """Beginn der Serie: bei „ganze serie“ zeigt das Datumsfeld die angeklickte Instanz –
        die Serie verschiebt sich nur um das, was dort geändert wurde."""
        d = self.day()
        if d and self.scope == "series" and self.master and self.anchor:
            ms = st.parse_when(self.master["start"], self.master.get("allday")).date()
            return ms + (d - self.anchor)
        return d

    def pick_ds(self, n, extend=False):
        a, e = raster.ds_times(n)
        if extend and self.t_from.get_text():
            try:
                first = raster.parse_time(self.t_from.get_text())
                if a > first:
                    a = first
            except ValueError:
                pass
        self.allday.set_active(False)
        self.on_allday(False)
        self.t_from.set_text(f"{a:%H:%M}")
        self.t_to.set_text(f"{e:%H:%M}")

    def sync_ds(self):
        try:
            a, e = raster.parse_time(self.t_from.get_text()), raster.parse_time(self.t_to.get_text())
        except ValueError:
            a = e = None
        for (n, s, f), b in zip(DS, self.ds_btns):
            on = a is not None and a <= dt.time(*s) and e >= dt.time(*f)
            (b.add_css_class if on else b.remove_css_class)("on")

    def rule(self):
        """(rrule, start_date) aus den Feldern."""
        d = self.eff_day()
        if self.sem.active and self.day():
            show = self.day()
            sem = raster.semester_for(show)
            if not sem:
                raise ValueError("kein Semester bekannt")
            every, hit = raster.semester_days(sem, show.weekday(), self.sem_week.current or "all")
            if not hit:
                raise ValueError(f"kein passender Termin im {sem['name']}")
            r = rrule.build({"FREQ": "WEEKLY", "BYDAY": rrule.DAYS[show.weekday()],
                             "UNTIL": sem["end"].strftime("%Y%m%d") + "T225959Z"})
            self.sem_plan = (sem, [x for x in every if x >= hit[0] and x not in hit], hit)
            return r, hit[0]
        pid = self.rep.current
        if pid == "none" or d is None:
            return None, d
        until = None
        if self.until.get_text().strip():
            until = raster.parse_date(self.until.get_text())
        if pid == "custom":
            r = self.custom.get_text().strip()
            if r.upper().startswith("RRULE:"):
                r = r[6:]
            rrule.parse(r)
            return r, d
        r, start = rrule.preset_rule(pid, dt.datetime.combine(d, dt.time()), until=until)
        return r, start.date()

    def update_hint(self):
        d = self.day()
        if d:
            par = raster.parity(d)
            txt = f"→ {WEEKDAYS_LONG[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]} · KW {raster.kw(d)} {par}"
            try:
                last = self.day_to()
                if last and last > d:
                    txt += f" · {(last - d).days + 1} Tage bis {raster.fmt_date(last, False)}"
                elif last and last < d:
                    txt += " · ✗ „bis“ liegt davor"
            except ValueError as e:
                txt += f" · ✗ {e}"
            self.date_hint.set_label(txt)
        else:
            self.date_hint.set_label("→ ? (heute, morgen, mi, +3, 20.10.)")
        if self.ev and self.ev.get("series") and self.scope != "series":
            self.rep_hint.set_label("↻ Teil einer Serie – „ganze serie“ wählen, um Wiederholung oder alle Termine zu ändern")
            return
        try:
            r, start = self.rule()
            if self.sem.active:
                sem, ex, hit = self.sem_plan
                wk = {"all": "jede Woche", "a": "A-Woche (ungerade KW)", "b": "B-Woche (gerade KW)"}
                txt = (f"{sem['name']} · {WEEKDAYS[start.weekday()]} {wk.get(self.sem_week.current, '')} · "
                       f"{raster.fmt_date(hit[0], False)}–{raster.fmt_date(hit[-1], False)} · {len(hit)} Termine")
                if any(a <= x <= b for x in ex for a, b in sem["free"]):
                    txt += " · ohne Feiertage/Pausen"
                if sem.get("guess"):
                    txt += " · Zeitraum geschätzt (eigene Daten: konto → semester)"
                self.rep_hint.set_label("↻ " + txt)
                return
            txt = rrule.describe(r, dt.datetime.combine(start, dt.time())) if r else "einmalig"
            ed = self.eff_day()
            if r and start and ed and start != ed:
                txt += f" · beginnt {raster.fmt_date(start)} (passende KW)"
            elif r and start and d and start != d:
                txt += f" · Serie beginnt {raster.fmt_date(start)}"
            if r and "INTERVAL=2" in r and "WEEKLY" in r:
                txt += " · Achtung: 2026 hat KW 53 – über den Jahreswechsel kippt die Parität, " \
                       "dafür „jede gerade/ungerade KW (exakt)“ wählen"
            self.rep_hint.set_label("↻ " + txt)
        except ValueError as e:
            self.rep_hint.set_label(f"✗ {e}")

    def form(self):
        """Was gerade im Editor steht – bleibt beim Umschalten nur dieser termin ↔ ganze serie erhalten."""
        buf = self.notes.get_buffer()
        return {"title": self.title.get_text(), "cat": self.cat.current, "cat_manual": self.cat_manual,
                "tone": self.tone.current, "loc": self.loc.get_text(), "link": self.link.get_text(),
                "notes": buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False),
                "from": self.t_from.get_text(), "to": self.t_to.get_text(), "allday": self.allday.active,
                "date": self.date.get_text(), "date_to": self.date_to.get_text(), "remind": self.remind.get_text(),
                "tz": self.tz.get_text(), "guests": self.guests.get_text(), "meet": self.meet_chk.active}

    def restore(self, f):
        self.title.set_text(f["title"])
        self.cat_manual = f["cat_manual"]
        self.cat.set_options(self.cat.options, f["cat"])
        self.tone.set_options(self.tone.options, f["tone"] or "")
        self.loc.set_text(f["loc"])
        self.link.set_text(f["link"])
        self.notes.get_buffer().set_text(f["notes"])
        self.allday.set_active(f["allday"])
        self.on_allday(f["allday"])
        self.t_from.set_text(f["from"])
        self.t_to.set_text(f["to"])
        self.date.set_text(f["date"])
        self.date_to.set_text(f["date_to"])
        self.remind.set_text(f.get("remind", ""))
        self.tz.set_text(f.get("tz", ""))
        self.guests.set_text(f.get("guests", ""))
        self.meet_chk.set_active(f.get("meet", False))
        self.sync_ds()
        self.update_hint()

    def set_scope(self, scope):
        f = self.form()
        self.scope = scope
        self.scope_inst.set_active(scope == "instance")
        self.scope_series.set_active(scope == "series")
        if scope == "series":
            self.load_master(f)
        else:
            self.fill(self.ev)
            self.restore(f)

    def load_master(self, f):
        o = self.orig
        if o.get("cal") == "local" or not o.get("series"):     # lokal oder noch nicht hochgeladen
            self.master = self.app.store.find(o["uid"]) or self.ev
            self.fill({**self.master, "series": None})
            self.restore(f)
            return
        self.msg.set_label("lade serie …")

        def done(res):
            if self.scope != "series" or self.orig is not o:
                return                                  # inzwischen umgeschaltet/geschlossen
            if isinstance(res, Exception):
                self.msg.set_label(f"Serie nicht geladen (offline?): {res}")
                self.set_scope("instance")
                return
            self.master = res
            self.msg.set_label("")
            self.fill({**res, "series": None})
            self.restore(f)
        tui.background(gcal.master, o["cal"], o["series"], o.get("acct", gcal.MAIN), done=done)

    def open_link(self):
        url = self.link.get_text().strip()
        if url.startswith(st.NOTIST_LINK):           # Erinnerung aus notist → Eintrag dort öffnen
            import shutil, subprocess
            exe = shutil.which("notist") or os.path.expanduser("~/.local/bin/notist")
            try:
                subprocess.Popen([exe, "--note", url[len(st.NOTIST_LINK):]], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.win.say("notist nicht gefunden", error=True)
            return
        if url:
            if "://" not in url:
                url = "https://" + url
            Gio.AppInfo.launch_default_for_uri(url, None)

    def on_key(self, ctrl, kv, code, state):
        if kv == Gdk.KEY_Escape:
            self.close()
            return True
        if state & Gdk.ModifierType.CONTROL_MASK and kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_s):
            self.save()
            return True
        root = self.get_root()
        typing = isinstance(root.get_focus() if root else None, (Gtk.Text, Gtk.TextView))
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)
        if Gdk.KEY_1 <= kv <= Gdk.KEY_7 and (state & Gdk.ModifierType.ALT_MASK or (not mods and not typing)):
            self.pick_ds(kv - Gdk.KEY_0, extend=bool(state & Gdk.ModifierType.SHIFT_MASK))
            return True
        return False

    # ----- Speichern -----
    def collect(self):
        d = self.day()
        if d is None:
            raise ValueError("Datum nicht erkannt")
        last = self.day_to()
        span = (last - d).days if last else 0
        if span < 0:
            raise ValueError("„bis“ liegt vor dem Beginn")
        d = self.eff_day()
        ex_days = None
        ev = dict(self.master if self.scope == "series" and self.master else self.ev)
        ev["title"] = self.title.get_text().strip() or "(ohne Titel)"
        ev["cat"] = self.cat.current
        ev["tone"] = self.tone.current or ""
        ev["cal"] = self.cal.current
        ev["location"] = self.loc.get_text().strip()
        try:
            ev["remind"] = reminders.parse_lead(self.remind.get_text())
        except ValueError as e:
            raise ValueError("Erinnerung: " + str(e)) from None
        ev["link"] = self.link.get_text().strip()
        buf = self.notes.get_buffer()
        ev["notes"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if self.scope != "instance" and not ev.get("series"):
            r, d2 = self.rule()
            if r:
                d = d2
            ev["rrule"] = r if r else ("" if ev.get("gid") and self.scope == "series" else None)
            if self.sem.active and r:
                sem, ex_days, _hit = self.sem_plan
                ev["sem"] = {"name": sem["name"], "week": self.sem_week.current or "all"}
            elif ev.get("sem"):                     # war Semester-Serie: deren Auslassungen gelten nicht mehr
                ev["sem"] = None
                ev["exdates"] = []
        tzname = self.tz.get_text().strip()
        zone = None
        if tzname and not self.allday.active:
            try:
                zone = ZoneInfo(tzname)
            except Exception:  # noqa: BLE001
                raise ValueError(f"Zeitzone „{tzname}“ kenne ich nicht (z. B. America/New_York, Asia/Tokyo)") from None
            if ev.get("rrule") and ev["cal"] == "local":
                raise ValueError("Eigene Zeitzone geht im lokalen Kalender nicht mit Wiederholung")
        if self.allday.active:
            ev["allday"] = True
            ev["start"] = d.isoformat()
            ev["end"] = (d + dt.timedelta(days=span + 1)).isoformat()
            ev["tz"] = None
        else:
            a = raster.parse_time(self.t_from.get_text())
            e = raster.parse_time(self.t_to.get_text())
            s, f = dt.datetime.combine(d, a), dt.datetime.combine(d + dt.timedelta(days=span), e)
            if f <= s:
                if span:
                    raise ValueError("Ende liegt vor dem Beginn")
                f += dt.timedelta(days=1) if e < a else dt.timedelta(minutes=90)
            ev["allday"] = False
            if zone is not None:
                ev["start"] = s.replace(tzinfo=zone).isoformat(timespec="seconds")
                ev["end"] = f.replace(tzinfo=zone).isoformat(timespec="seconds")
                ev["tz"] = tzname
            else:
                ev["start"], ev["end"] = st.iso(s), st.iso(f)
                ev["tz"] = None
        if ev["cal"] != "local" and not self.ro:
            self.collect_guests(ev)
        if ex_days is not None:
            ev["exdates"] = [x.isoformat() if ev["allday"] else
                             st.iso(dt.datetime.combine(x, st.parse_when(ev["start"], False).time())) for x in ex_days]
        return ev

    def on_bar_toggle(self, on):
        o = self._bar_o
        if not o:
            return
        if on:
            barstate.show(barstate.key_of(o))
        else:
            barstate.hide({**o, "s": self.orig["s"]} if self.orig and self.orig.get("s") else o)
        barstate.signal_waybar()
        self.app.win.say(("in der Waybar wieder gezeigt: " if on else "in der Waybar versteckt: ") + (o.get("title") or "Termin"))

    def copy_meet(self):
        if self.meet_url:
            Gdk.Display.get_default().get_clipboard().set_content(Gdk.ContentProvider.new_for_value(self.meet_url))
            self.app.win.say("Meet-Link kopiert")

    def sync_google_rows(self):
        """Gäste/Meet/Einladung gibt es nur bei Google-Terminen; Gäste ändert nur, wer den Termin organisiert."""
        google = self.cal.current not in (None, "", "local")
        for w in (self.guest_row, self.guest_hint_row, self.meet_row, self.send_row):
            w.set_visible(google)
        self.guests.set_sensitive(self.guest_org and not getattr(self, "ro", False))
        self.meet_chk.set_visible(not self.meet_url)
        self.meet_open.set_visible(bool(self.meet_url))
        self.meet_copy.set_visible(bool(self.meet_url))
        self.guest_hint.set_label("" if self.guest_org else "Du bist hier nur eingeladen – Gäste kann nur der Organisator ändern.")

    def update_tz_hint(self):
        """Zeigt, wie spät es bei dir ist, wenn eine fremde Zeitzone eingetragen ist."""
        name = self.tz.get_text().strip()
        if not name:
            self.tz_hint.set_label("")
            return
        try:
            zone = ZoneInfo(name)
            d = self.day()
            a, b = raster.parse_time(self.t_from.get_text()), raster.parse_time(self.t_to.get_text())
            s = dt.datetime.combine(d, a, tzinfo=zone).astimezone(TZ)
            f = dt.datetime.combine(d, b, tzinfo=zone).astimezone(TZ)
            self.tz_hint.set_label(f"bei dir: {s:%H:%M}–{f:%H:%M}" + ("" if s.date() == d else f" ({s:%a %d.%m.})"))
        except Exception:  # noqa: BLE001 – unfertige Eingabe
            self.tz_hint.set_label("Zeitzone unbekannt" if name and "/" in name else "")

    def collect_guests(self, ev):
        """Gästefeld → ev["attendees"] (+ attendees_edit nur bei Änderung, damit Google sonst unangetastet bleibt)."""
        if not self.guest_org:
            return
        raw = [x for x in re.split(r"[,;\s]+", self.guests.get_text().strip()) if x]
        for x in raw:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", x):
                raise ValueError(f"„{x}“ ist keine E-Mail-Adresse")
        want = list(dict.fromkeys(x.lower() for x in raw))
        have = {a["email"].lower(): a for a in self.guest_orig}
        mine = [a for a in self.guest_orig if a.get("self")]
        shown = [e for e in have if not have[e].get("self")]
        if set(want) != set(shown):
            ev["attendees"] = mine + [have.get(e) or {"email": e} for e in want]
            ev["attendees_edit"] = True
        if self.meet_chk.active and not self.meet_url:
            ev["meet_create"] = True

    def save(self):
        if getattr(self, "ro", False):
            self.msg.set_label("✗ nur lesbar – hier lässt sich nichts speichern")
            return
        try:
            ev = self.collect()
        except ValueError as e:
            self.msg.set_label(f"✗ {e}")
            return
        scope = self.scope
        if scope == "series" and self.master:
            ev["gid"] = self.master.get("gid")
            ev["uid"] = self.master.get("uid")
            ev["series"] = None
        shown = self.day()            # dort bleiben, wo man den Termin sieht (Serie: nicht zum Serienbeginn)
        try:
            self.app.store.save_event(ev, scope=scope, original=self.orig, send=self.send_chk.active)
        except ValueError as e:
            self.msg.set_label(f"✗ {e}")
            return
        self.close()
        self.app.after_edit(f"gespeichert: {ev['title']}")
        if shown:
            self.app.cursor = shown
        self.app.redraw()

    def delete(self):
        if getattr(self, "ro", False):
            return
        if self.del_btn.get_label() != "wirklich?":
            self.del_btn.set_label("wirklich?")
            GLib.timeout_add(2500, lambda: self.del_btn.set_label("löschen") and False)
            return
        ev = self.master if self.scope == "series" and self.master else self.ev
        self.app.store.delete_event(ev, scope=self.scope, original=self.orig)
        self.close()
        self.app.after_edit(f"gelöscht: {ev.get('title')}")

    def close(self):
        self.set_visible(False)
        self.del_btn.set_label("löschen")
        self.app.focus_view()


# =====================================================================
# App
# =====================================================================
ACCT_PAGES = [("allgemein", "allgemein"), ("google", "google"), ("kalender", "kalender"),
              ("erinnerungen", "erinnerungen"), ("leiste", "leiste & desktop")]

class Kalender(AcctMixin, Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.win = None
        self.daemon = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        act = Gio.SimpleAction.new("show-tab", GLib.VariantType.new("s"))
        act.connect("activate", lambda a, v: self.show_tab_now(v.get_string()))
        self.add_action(act)
        act = Gio.SimpleAction.new("toggle-desk", None)
        act.connect("activate", lambda *_: self.toggle_desk())
        self.add_action(act)

    def show_tab_now(self, tid):
        if not self.win:
            self.build()
        getattr(tui.glass, "bring_here", lambda w: None)(self.win)
        self.win.present()
        if tid in ("day", "week", "month", "agenda", "tasks"):
            self.win.show_tab(tid)
        elif tid in ("acct", "konto", "settings") or tid.startswith("acct:") or tid in ("bar", "desk-settings"):
            self.open_account()
            page = {"bar": "leiste", "desk-settings": "leiste"}.get(tid, tid.split(":", 1)[1] if ":" in tid else None)
            if page in self.acct_tabs:
                self.acct_tabs[page].set_active(True)

    def do_activate(self):
        if self.daemon:             # --daemon: Fenster vorbereiten, aber erst beim nächsten Aufruf zeigen
            self.daemon = False
            if not self.win:
                self.build()
            self.hold()
            return
        if self.win and self.win.get_visible() and self.win.is_active():
            self.win.close()               # Super+K zum Ein-/Ausblenden
            return
        if not self.win:
            self.build()
        getattr(tui.glass, "bring_here", lambda w: None)(self.win)   # offen auf anderem Arbeitsbereich → hierher holen
        self.win.present()
        self.focus_view()

    def remind_tick(self):
        try:
            self.reminders.tick()
        except Exception as e:  # noqa: BLE001 – der Takt darf nie sterben
            print("erinnerung:", e, file=sys.stderr)
        return True

    # ----- Aufbau -----
    def build(self):
        self.store = st.Store()
        self.store.listeners.append(self.redraw)
        self.reminders = reminders.Reminders(self.store, lambda t, b, k: reminders.send(self, t, b, k))
        GLib.timeout_add_seconds(20, self.remind_tick)
        GLib.timeout_add_seconds(3, lambda: self.remind_tick() and False)       # gleich nach dem Start
        self.start_background()
        self.deskcard = deskcard.DeskCard(self)
        self.store.listeners.append(lambda: self.deskcard.refresh())
        GLib.timeout_add(1500, lambda: (self.deskcard.apply(), False)[1])     # nach dem ersten Zeichnen
        self.pal = None
        self.cursor = dt.date.today()
        self.slot = self.current_slot()
        self.focus_uid = None
        self.day_scroll = 0
        self.week_scroll = 0
        self.week_overflow = False
        self.syncing = False
        self.sync_note = ""
        self.last_errors = []
        self.login = None
        self.del_armed = None

        if CSS not in tui.CSS:          # im selben Stylesheet wie tui, damit @primary usw. auflösen
            tui.CSS += CSS + deskcard.CSS
            tui.Theme.get().load()
        tabs = [("day", "tag", "󰃭"), ("week", "woche", "󰸗"), ("month", "monat", "󰃰"), ("agenda", "agenda", "󰃯"), ("tasks", "aufgaben", "󰄬")]
        win = tui.TuiWindow(self, "datist", tabs, size=(1180, 780),
                            hints=(("hjkl", "nav"), ("n", "neu"), ("a", "schnell"), ("t", "heute"), ("?", "hilfe")))
        win.APP_ID = APP_ID
        self.win = win
        win.connect("notify::visible", lambda w, _p: w.get_visible() or
                    GLib.timeout_add_seconds(3, lambda: (tui.trim_memory(), False)[-1]))   # versteckt: Heap zurückgeben
        self.kw_badge = label("", "kw-badge")
        self.sync_badge = label("", "sync-badge")
        self.prev_btn = tui.Button("‹", lambda: self.step_period(-1), tooltip="voriger Zeitraum (H)")
        self.today_btn = tui.Button("heute", self.go_today, tooltip="zu heute springen (t)")
        self.next_btn = tui.Button("›", lambda: self.step_period(1), tooltip="nächster Zeitraum (L)")
        self.kw_badge.set_tooltip_text("Kalenderwoche des markierten Tages")
        self.relogin_btn = tui.Button("⚠ neu anmelden", self.start_login, danger=True,
                                      tooltip="Google-Anmeldung abgelaufen (im Testmodus alle 7 Tage) – "
                                              "klicken, um dich im Browser neu anzumelden")
        self.relogin_btn.set_visible(False)
        self.exam_btn = tui.Button("", self.goto_exam)
        self.exam_btn.set_visible(False)
        for w in (self.exam_btn, self.relogin_btn, self.sync_badge, self.prev_btn, self.today_btn, self.next_btn, self.kw_badge):
            win.header_extra.append(w)
        win.add_changelog("datist", os.path.dirname(os.path.realpath(__file__)))
        # Konto & Einstellungen: eigenes Fenster, Knopf rechts neben der Version
        self.acct_btn = tui.Button("󰀄 konto", self.open_account,
                                   tooltip="konto & einstellungen – google, kalender, farben, semester")
        self.acct_btn.set_visible(False)           # ersetzt durch den Einstellungs-Knopf (Zahnrad) ganz rechts
        # Einstellungs-Knopf wie in mailist: Zahnrad zwischen Version und Glas-Schalter
        self.gear_btn = tui.Button("\U000F0493", self.open_account, tooltip="Einstellungen")
        self.gear_btn.set_margin_start(6)
        win.header_extra.get_parent().insert_child_after(self.gear_btn, win.header_extra)
        self.acct_win = None
        self._gpal = None
        self._color_tried = set()
        self.store.color_for = self.google_color_for
        self.header_compact = False
        win.on_resize = self.on_resize
        # Kopfleiste darf die Mindestbreite nicht bestimmen: in einen Container, der notfalls abschneidet,
        # bis on_resize die passende Stufe (Symbole statt Text) gewählt hat
        root = win.root
        root.remove(win.topbar)
        self.top_clip = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                           vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                           child=win.topbar)
        root.prepend(self.top_clip)
        # Tastenhinweise auch im kleinen Fenster: abschneiden statt ausblenden (bestimmen nie die Mindestbreite)
        win.statusbar.remove(win.hint_box)
        self.hint_clip = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                            vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True,
                                            propagate_natural_height=True, child=win.hint_box)
        win.statusbar.append(self.hint_clip)
        win.on_compact = lambda compact: win.hint_box.set_visible(True)
        # Abgleich-Anzeige (✓ 14:32 …): Klick = jetzt mit Google abgleichen
        sc = Gtk.GestureClick()
        sc.connect("released", lambda *_: self.sync(force=True))
        self.sync_badge.add_controller(sc)
        self.sync_badge.set_cursor(Gdk.Cursor.new_from_name("pointer"))

        self.views = {}
        for v in ("day", "week", "month"):
            c = Cells(self, v)
            self.views[v] = c
            win.add_page(v, c, scroll=False)
        self.agenda = agendaview.AgendaView(self)
        win.add_page("agenda", self.agenda, scroll=False)
        self.tasksview = agendaview.TasksView(self)
        win.add_page("tasks", self.tasksview, scroll=False)
        self.build_account()
        # Editor als Ebene über dem Inhalt; darunter 2-Finger-Zurück (swipe.py, Seitenstapel) – endet in der Woche
        # Das Wischen umfasst auch Editor und Hilfe: über einem offenen Termin schließt 2-Finger-Zurück ihn
        win.content.remove(win.stack)
        self.nav_back, self.nav_cur, self._nav_skip = [], None, False
        self.overlay = Gtk.Overlay(child=win.stack, vexpand=True)
        # 2-Finger-Zoom: zusammenziehen = Tag → Woche → Monat, auseinander = zurück
        zoom = Gtk.GestureZoom()
        zoom.connect("begin", lambda *_: setattr(self, "_zoom_done", False))
        zoom.connect("scale-changed", self.on_zoom)
        self.overlay.add_controller(zoom)
        # Fläche hinter dem Editor: Klick daneben schließt ihn („wegklicken“)
        self.scrim = Gtk.Box(hexpand=True, vexpand=True, visible=False)
        self.scrim.add_css_class("editor-scrim")
        sclick = Gtk.GestureClick(button=1)
        sclick.connect("released", lambda g, *_: (g.set_state(Gtk.EventSequenceState.CLAIMED),
                                                   GLib.idle_add(lambda: (self.dismiss_overlays(), False)[1])))
        self.scrim.add_controller(sclick)
        self.overlay.add_overlay(self.scrim)
        self.editor = Editor(self)
        self.editor.set_visible(False)
        self.editor.connect("notify::visible", lambda *_: self.sync_scrim())
        self.overlay.add_overlay(self.editor)
        self.help = self.build_help()
        self.help.set_visible(False)
        self.help.connect("notify::visible", lambda *_: self.sync_scrim())
        self.overlay.add_overlay(self.help)
        self.srch = searchview.SearchBox(self)
        self.srch.set_visible(False)
        self.srch.connect("notify::visible", lambda *_: self.sync_scrim())
        self.overlay.add_overlay(self.srch)
        self.apply_see_through()
        self.swipe = swipe.SwipeBack(self.overlay, self.nav_can_back, self.nav_go_back,
                                     where=self.nav_where, target=self.nav_target,
                                     goto=self.nav_goto)
        win.content.append(self.swipe.widget)
        # Schnelleingabe
        self.quick = tui.Entry("schnell: V Mathe nächsten mi 14 Uhr für 2h @MA/041 #v !w   (esc abbrechen)",
                               activate=self.quick_add)
        self.quick_rev = Gtk.Revealer(child=hbox(label("󰐕", "accent"), self.quick, spacing=8),
                                      transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        self.quick_rev.get_child().add_css_class("quick")
        win.content.append(self.quick_rev)
        qk = Gtk.EventControllerKey()
        qk.connect("key-pressed", lambda c, kv, *_: kv == Gdk.KEY_Escape and (self.close_quick() or True))
        self.quick.add_controller(qk)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        win.add_controller(keys)
        win.on_tab = lambda tid: (self.store.settings.__setitem__("view", tid), self.store.save_settings(),
                                  self.nav_note(tid), self.update_header(), self.focus_view())
        win.on_refresh = lambda: self.sync(force=True)
        win.theme.listeners.append(self.redraw)
        win.theme.listeners.append(lambda: setattr(self, "_gpal", None))
        orig_key = win._key

        def key_guard(c, kv, code, state):
            # Esc zuerst an Editor/Hilfe/Schnelleingabe, erst dann Fenster schließen
            if kv == Gdk.KEY_Escape:
                if self.editor.get_visible():
                    self.editor.close()
                    return True
                if self.srch.get_visible():
                    self.srch.close()
                    return True
                if self.help.get_visible():
                    self.help.set_visible(False)
                    return True
                if self.quick_rev.get_reveal_child():
                    self.close_quick()
                    return True
            if self.editor.get_visible() and not isinstance(win.get_focus(), (Gtk.Text, Gtk.TextView)) \
                    and Gdk.KEY_1 <= kv <= Gdk.KEY_9:
                return False
            return orig_key(c, kv, code, state)
        win._key = key_guard
        # TuiWindow hat seinen Controller schon mit der alten Methode verbunden → ersetzen
        c = win.observe_controllers()
        for i in range(c.get_n_items()):
            ctl = c.get_item(i)
            if isinstance(ctl, Gtk.EventControllerKey) and ctl.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE:
                win.remove_controller(ctl)
                break
        k2 = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        k2.connect("key-pressed", key_guard)
        win.add_controller(k2)

        view = self.store.settings.get("view", "week")
        view = view if view in ("day", "week", "month") else "week"
        self.nav_cur = view
        win.show_tab(view)
        self.update_header()
        GLib.timeout_add_seconds(SYNC_EVERY, lambda: self.sync() or True)
        GLib.timeout_add_seconds(30, lambda: self.redraw() or True)      # Jetzt-Linie
        Gio.NetworkMonitor.get_default().connect("network-changed", lambda m, up: up and self.sync())
        GLib.idle_add(lambda: self.sync() and False)
        self.watch_notist()

    # ----- Erinnerungen aus notist -----
    def watch_notist(self):
        """notist schreibt seine Erinnerungen nach data/notist.json → als Termine übernehmen, sobald sie sich ändert."""
        self.take_notist()
        try:
            f = Gio.File.new_for_path(os.path.join(st.DATA, st.NOTIST_FILE))
            self._notist_mon = f.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._notist_mon.connect("changed", lambda *_: self._notist_soon())
        except GLib.Error:
            pass
        self._notist_id = None

    def _notist_soon(self):
        if getattr(self, "_notist_id", None):
            GLib.source_remove(self._notist_id)
        self._notist_id = GLib.timeout_add(300, self.take_notist)

    def take_notist(self):
        self._notist_id = None
        try:
            if self.store.sync_notist() and self.store.pending:
                GLib.timeout_add(800, lambda: self.sync() and False)      # gleich zu Google
        except Exception as e:  # noqa: BLE001 – notist ist ein Extra, darf datist nie stören
            print("notist:", e, file=sys.stderr)
        return False

    def apply_see_through(self):
        on = self.store.settings.get("see_through", True)
        for w in (self.editor, self.help, self.srch):
            (w.add_css_class if on else w.remove_css_class)("see-through")
        if not getattr(self, "_typing_hook", False):
            self._typing_hook = True
            # Beim Tippen rechnet der Blur hinter dem Editor bei jedem Cursor-Bild neu → ruckelt. Dort ohne Blur.
            def focus(win, *_):
                f = win.get_focus()
                typing = f is not None and isinstance(f, (Gtk.Text, Gtk.TextView)) and f.is_ancestor(self.editor)
                (self.editor.add_css_class if typing else self.editor.remove_css_class)("typing")
            hooked = []
            self.editor.connect("map", lambda w: hooked or hooked.append(w.get_root().connect("notify::focus-widget", focus)))

    # ----- 2-Finger-Zurück: Tab-Verlauf, endet immer in der Wochenansicht -----
    NAV_NAMES = {"day": "¹ tag", "week": "² woche", "month": "³ monat", "agenda": "⁴ agenda", "tasks": "⁵ aufgaben"}

    def nav_where(self):
        if getattr(self, "editor", None) and self.editor.get_visible():
            return "editor", "termin"
        if getattr(self, "srch", None) and self.srch.get_visible():
            return "search", "suche"
        if getattr(self, "help", None) and self.help.get_visible():
            return "help", "hilfe"
        t = self.win.current_tab() if self.win else None
        return t, self.NAV_NAMES.get(t, t or "")

    def overlay_open(self):
        return (self.editor.get_visible() or self.help.get_visible() or
                getattr(self, "srch", None) is not None and self.srch.get_visible())

    def sync_scrim(self):
        self.scrim.set_visible(self.overlay_open())

    def dismiss_overlays(self):
        """Wegklicken / 2-Finger-Zurück über Editor oder Hilfe."""
        if self.editor.get_visible():
            self.editor.dismiss()
        elif self.srch.get_visible():
            self.srch.close()
        elif self.help.get_visible():
            self.help.set_visible(False)
            self.focus_view()

    def nav_note(self, tid):
        skip, self._nav_skip = self._nav_skip, False
        if tid == self.nav_cur:
            return
        if tid == "week":
            self.nav_back = []                       # Woche ist das Ende der Zurück-Kette
        elif not skip and self.nav_cur and (not self.nav_back or self.nav_back[-1] != self.nav_cur):
            self.nav_back.append(self.nav_cur)
            del self.nav_back[:-40]
        self.nav_cur = tid

    def nav_can_back(self):
        return self.overlay_open() or self.win.current_tab() != "week"

    def _nav_next(self, pop):
        cur = self.win.current_tab()
        stack = self.nav_back if pop else list(self.nav_back)
        while stack:
            t = stack.pop()
            if t != cur:
                return t
        return "week"

    def nav_target(self):
        if self.overlay_open():
            t = self.win.current_tab()                # zurück = Editor/Hilfe zu, Ansicht bleibt
            return t, self.NAV_NAMES.get(t, t)
        t = self._nav_next(False)
        return t, self.NAV_NAMES.get(t, t)

    def nav_goto(self, t):
        if t in ("editor", "help") or not t:
            return False
        self.win.show_tab(t)
        return True

    def nav_go_back(self):
        if self.overlay_open():
            self.dismiss_overlays()
            return
        t = self._nav_next(True)
        self._nav_skip = True
        self.win.show_tab(t)

    # ----- 2-Finger-Zoom -----
    ZOOM_ORDER = ["day", "week", "month"]

    def on_zoom(self, gesture, scale):
        if getattr(self, "_zoom_done", False) or self.overlay_open():
            return
        if 0.8 <= scale <= 1.25:
            return
        cur = self.win.current_tab()
        if cur not in self.ZOOM_ORDER:
            return
        i = self.ZOOM_ORDER.index(cur) + (1 if scale < 0.8 else -1)
        self._zoom_done = True                       # pro Geste nur ein Schritt
        if 0 <= i < len(self.ZOOM_ORDER):
            self.focus_uid = None
            self.win.show_tab(self.ZOOM_ORDER[i])

    # ----- Google-Farben -----
    def google_color_for(self, ev):
        if self._gpal is None:
            self._gpal = Palette()
        return google_color(self._gpal.cat(ev.get("cat"), ev.get("tone")))

    def push_colors(self):
        n = len(self.store.color_fixes(all_events=True))
        self.win.say(f"{n} termin{'e' if n != 1 else ''}/serie{'n' if n != 1 else ''} bekommen die datist-farbe in google"
                     if n else "farben in google passen schon")
        if n:
            self.update_header()
            GLib.timeout_add(500, lambda: self.sync(force=True) and False)

    # ----- Konto-Fenster -----
    def acct_open(self):
        return bool(self.acct_win and self.acct_win.get_visible())

    def quit_app(self):
        """Ganz schließen (nicht nur verstecken): Fenster, Konto-Fenster und Prozess."""
        if self.acct_win is not None:
            self.acct_win.destroy()
        self.quit()

    def open_account(self):
        if self.acct_win is None:
            w = Gtk.Window(application=self, title="datist · konto", transient_for=self.win, modal=False, hide_on_close=True)
            w.add_css_class("pb-window")
            w.add_css_class("tui")
            w.set_default_size(*getattr(tui.glass, "fit_size", lambda a, b: (a, b))(760, 720))
            getattr(tui.glass, "frame_window", lambda x: x.set_decorated(False))(w)
            top = hbox(label("datist", "brand"), label("konto & einstellungen", "accent"), label("", hexpand=True),
                       spacing=10)
            top.add_css_class("topbar")
            top.append(tui.Button("󰗼 datist beenden", self.quit_app, tooltip="datist ganz schließen (nicht nur verstecken)"))
            close = tui.Button("✕", w.close, tooltip="Schließen (Esc)")
            close.add_css_class("close")
            close.set_margin_start(4)
            top.append(close)
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.acct)
            scroll.set_margin_start(14)
            scroll.set_margin_end(14)
            scroll.set_margin_bottom(10)
            w.set_child(vbox(Gtk.WindowHandle(child=top), scroll, spacing=0))
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", lambda c, kv, *_: kv == Gdk.KEY_Escape and (w.close() or True))
            w.add_controller(keys)
            self.acct_win = w
        self.refresh_account()
        getattr(tui.glass, "bring_here", lambda x: None)(self.acct_win)
        self.acct_win.present()

    def go_today(self):
        self.cursor = dt.date.today()
        self.slot = self.current_slot()
        self.focus_uid = None
        self.day_scroll = 0
        self.after_move()
        self.focus_view()

    def step_period(self, d):
        view = self.win.current_tab()
        if view == "month":
            self.cursor = self.add_months(self.cursor, d)
            self.after_move()
        else:
            self.move_day(d * (1 if view == "day" else 7))
        self.focus_view()

    def on_resize(self, w, h):
        """Kopfleiste und Editor an die Fenstergröße anpassen (halber Bildschirm und kleiner)."""
        compact, tiny = w < 820, w < 640
        top = self.win.topbar.get_child()
        c = top.get_first_child()
        while c:
            if c.has_css_class("brand"):          # App-Name oben links (wie filist), erst ganz schmal weg
                c.set_visible(not tiny)
            elif c.has_css_class("glass-toggle"):
                c.set_visible(not compact)
            c = c.get_next_sibling()
        self.prev_btn.set_visible(not tiny)
        self.next_btn.set_visible(not tiny)
        if tiny:                                  # sehr schmal: Tabs nur als Symbol
            for name_lbl, icon_lbl in self.win.tab_names.values():
                if icon_lbl is not None:
                    name_lbl.set_visible(False)
                    icon_lbl.set_visible(True)
        elif self.win.compact is not None:
            self.win._apply_compact()
        self.today_btn.set_label("◉" if compact else "heute")
        self.acct_btn.set_label("󰀄" if compact else "󰀄 konto")
        self.header_compact = compact
        self.editor.set_size_request(max(240, min(640, w - 20)), -1)
        self.editor.scroller.set_max_content_height(max(160, h - 110))
        self.editor.keys_hint.set_visible(not compact)
        self.update_header()

    def focus_view(self):
        v = self.win.current_tab() if self.win else None
        if v in self.views:
            self.views[v].grab_focus()
        elif v == "agenda":
            self.agenda.focus_first()
        elif v == "tasks":
            self.tasksview.focus_first()

    # ----- Zustand -----
    def current_slot(self):
        now = dt.datetime.now()
        n = raster.ds_of(now.time())
        if n:
            return n - 1
        m = now.hour * 60 + now.minute
        for i, (_, a, b) in enumerate(DS):
            if m < raster.minutes(a):
                return i
        return 6

    def redraw(self):
        if not self.win:
            return
        for c in self.views.values():
            c.queue_draw()
        if getattr(self, "agenda", None) is not None:
            self.agenda.refresh()
        if getattr(self, "tasksview", None) is not None:
            self.tasksview.refresh()
        self.update_header()
        if self.acct_open():
            self.refresh_account()

    def update_exam_badge(self):
        ex = self.store.upcoming("pruefung", 90)
        self.exam_btn.set_visible(bool(ex))
        if not ex:
            return
        today = dt.date.today()
        o = ex[0]
        n = (o["s"].date() - today).days
        when = "heute" if n <= 0 else "morgen" if n == 1 else f"{n} d"
        name = re.sub(r"^[!·]:?\s*", "", o["title"])
        self.exam_btn.set_label(f"! {when}" if self.header_compact else f"! {name[:18]} · {when}")
        self.exam_btn.set_tooltip_text("Nächste Prüfungen (Klick = zum Termin):\n" + "\n".join(
            f"{x['s']:%d.%m.} {agendaview.rel_days(x['s'].date(), today)} – {x['title']}" for x in ex[:5]))

    def goto_exam(self):
        ex = self.store.upcoming("pruefung", 90)
        if ex:
            self.cursor = ex[0]["s"].date()
            self.focus_uid = ex[0].get("uid")
            self.win.show_tab("day")
            self.redraw()

    # Zuerst ausgeblendet, wenn die Kopfzeile nicht passt (Zahnrad, Version, ✕ und die Tabs bleiben immer)
    HEADER_DROP = ("kw_badge", "sync_badge", "exam_btn", "today_btn", "next_btn", "prev_btn")

    def fit_header(self):
        """Kopfzeile an die Fensterbreite anpassen: lieber Nebensächliches weglassen, als rechts etwas abzuschneiden
        (dort sitzen Einstellungen und Schließen)."""
        w = self.win.get_width() if self.win else 0
        if w <= 0:
            return
        for x in getattr(self, "_hdr_hidden", []):
            x.set_visible(True)
        self._hdr_hidden = []
        top = self.win.topbar
        for name in self.HEADER_DROP:
            if top.measure(Gtk.Orientation.HORIZONTAL, -1)[1] <= w - 24:
                break
            x = getattr(self, name, None)
            if x is not None and x.get_visible():
                x.set_visible(False)
                self._hdr_hidden.append(x)

    def update_header(self):
        d = self.cursor
        even = raster.kw(d) % 2 == 0
        if self.header_compact:
            self.kw_badge.set_label(f"KW {raster.kw(d)} {'g' if even else 'u'}")
        else:
            self.kw_badge.set_label(f"KW {raster.kw(d)} · {'gerade' if even else 'ungerade'}")
        self.kw_badge.set_css_classes(["kw-badge", "even" if even else "odd"])
        n = len(self.store.pending)
        self.update_exam_badge()
        exp = gcal.logged_in() and gcal.expired()
        soon = self.expiry_soon()
        self.relogin_btn.set_visible(exp or soon is not None)
        self.relogin_btn.set_sensitive(self.login is None)
        if self.login is not None:
            self.relogin_btn.set_label("… browser" if self.header_compact else "… warte auf browser")
        elif exp:
            self.relogin_btn.set_label("⚠" if self.header_compact else "⚠ neu anmelden")
        else:
            h = max(0, int((soon or 0) // 3600))
            self.relogin_btn.set_label("⏳" if self.header_compact else f"⏳ erneuern (noch {h} h)")
            self.relogin_btn.set_tooltip_text("Die Google-Anmeldung läuft bald ab (Testmodus, 7 Tage) – ein Klick erneuert sie")
        if self.syncing:
            s = "⟳ gleiche ab …"
        elif exp:
            s = f"⚠ abgelaufen · {n} offen" if n else "⚠ abgelaufen"
        elif not gcal.logged_in():
            s = "◆ lokal"
        elif n:
            s = f"⟳ {n} offen"
        elif self.store.synced:
            t = dt.datetime.fromisoformat(self.store.synced)
            s = f"✓ {t:%H:%M}"
        else:
            s = "○ noch nicht abgeglichen"
        tips = {"✓": f"mit Google abgeglichen, zuletzt um {s[2:]} Uhr", "◆": "nur lokal – nicht bei Google angemeldet",
                "⟳": "Änderungen warten auf den Abgleich", "○": "noch nicht mit Google abgeglichen"}
        self.sync_badge.set_tooltip_text((s if self.syncing else tips.get(s[:1], s)) + (" · klicken = jetzt abgleichen (strg+r)"
                                                               if gcal.logged_in() else ""))
        self.sync_badge.set_visible(not exp)        # bei abgelaufener Anmeldung reicht der ⚠-Knopf
        if self.header_compact and not s.startswith("✓"):
            s = s.split(" ")[0]                  # schmal: nur das Symbol, Text im Tooltip (Uhrzeit bleibt)
        self.sync_badge.set_label(s)
        self.fit_header()

    # ----- Abgleich -----
    def sync(self, force=False):
        self.refresh_subs(force=force)               # ICS-Abos laufen unabhängig von Google mit
        if self.syncing and gcal.logged_in():
            self._resync = True                      # Änderung während eines Abgleichs: gleich danach noch einmal
            return False
        if self.syncing or not gcal.logged_in() or not gcal.client():
            self.update_header()
            return False
        if not gcal.active_accounts():           # nicht ständig gegen abgelaufene Anmeldungen laufen
            if force:
                self.win.say("Google-Anmeldung abgelaufen – oben auf „⚠ neu anmelden“ klicken", error=True)
            self.update_header()
            return False
        center = self.cursor
        win = self.store.window
        if win:
            a = dt.datetime.fromisoformat(win[0]).date()
            b = dt.datetime.fromisoformat(win[1]).date()
            if not (a + dt.timedelta(days=30) <= center <= b - dt.timedelta(days=60)):
                win = None
        window = tuple(win) if win else gcal.window_around(center)
        self.syncing = True
        self.update_header()
        pend = copy.deepcopy(self.store.pending)

        def done(res):
            self.syncing = False
            if getattr(self, "_resync", False):
                self._resync = False
                GLib.timeout_add(400, lambda: self.sync() and False)
            if isinstance(res, gcal.ExpiredError):
                self.win.say("Google-Anmeldung abgelaufen (Testmodus: alle 7 Tage) – oben auf „⚠ neu anmelden“ "
                             "klicken. Änderungen bleiben gespeichert.", error=True)
                if self.acct_open():
                    self.refresh_account()
            elif isinstance(res, gcal.AuthError):
                self.win.say(f"Google-Anmeldung: {res}", error=True)
            elif isinstance(res, Exception):
                self.win.say(f"Abgleich fehlgeschlagen: {res}", error=True)
            else:
                self.store.apply_sync(res)
                self.last_errors = res.get("errors", [])
                if res.get("expired"):
                    who = ", ".join(self.acct_name(a) for a in res["expired"])
                    self.last_errors.insert(0, f"Anmeldung abgelaufen: {who} – oben „⚠ neu anmelden“")
                if not res.get("offline") and res.get("events") is not None:
                    # ältere datist-Termine haben in Google noch keine Farbe (blau) → einmal nachziehen
                    fixed = self.store.color_fixes(skip=self._color_tried)
                    if fixed:
                        self._color_tried.update(fixed)
                        GLib.timeout_add(1500, lambda: self.sync() and False)
                if res.get("offline"):
                    self.win.say("offline – Änderungen bleiben gespeichert und gehen später raus")
                elif self.last_errors:
                    self.win.say(self.last_errors[0], error=True)
                elif force:
                    self.win.say("abgeglichen")
            self.update_header()
            self.redraw()
        tui.background(gcal.sync, pend, window, dict(self.store.settings.get("accounts", {})), self.store.tasks_on(),
                       done=done)
        return False

    def after_edit(self, msg):
        self.win.say(msg + ("   ·   u = rückgängig" if self.store.can_undo() else ""))
        self.redraw()
        if gcal.logged_in():
            GLib.timeout_add(800, lambda: self.sync() and False)

    # =================================================================
    # Ansichten
    # =================================================================
    def render(self, view, g, cols, rows):
        p = self.pal
        g.fill(0, 0, cols, rows, p.bg, 0.0)
        if view == "preview":
            self.editor.render_preview(g, cols, rows)
        elif view == "week":
            self.render_week(g, cols, rows)
        elif view == "day":
            self.render_day(g, cols, rows)
        else:
            self.render_month(g, cols, rows)

    def occ(self, a, b):
        return self.store.mark_conflicts(
            self.store.occurrences(dt.datetime.combine(a, dt.time()), dt.datetime.combine(b, dt.time())))

    @staticmethod
    def clock(d):
        return f"{d:%H:%M}"

    @staticmethod
    def last_day(o):
        """Letzter Tag, den ein Termin berührt (Ende exklusiv)."""
        return max(o["s"].date(), (o["e"] - dt.timedelta(seconds=1)).date())

    @staticmethod
    def is_long(o):
        """Ganztägig oder ≥ 20 h → in die Leiste über dem Raster statt ins DS-Raster."""
        return bool(o.get("allday")) or (o["e"] - o["s"]) >= dt.timedelta(hours=20)

    def span_text(self, o):
        """„Fr 18:00 – So 14:00“ bzw. „Mi 21.10. – Fr 23.10.“ für mehrtägige Termine, sonst None."""
        last = self.last_day(o)
        if last <= o["s"].date():
            return None
        a, b = o["s"], o["e"]
        if o.get("allday"):
            return f"{WEEKDAYS[a.weekday()]} {a.day}.{a.month}. – {WEEKDAYS[last.weekday()]} {last.day}.{last.month}."
        return f"{WEEKDAYS[a.weekday()]} {a:%H:%M} – {WEEKDAYS[b.weekday()]} {b:%H:%M}"

    # ----- Zeitachse: Zeilen für DS und Pausen -----
    def time_rows(self, k, early, late, extra=0, pauses=True):
        """Segmente [(art, nr, beginn_min, ende_min, erste_zeile, zeilen)]. extra: Zusatzzeilen für die ersten DS.
        pauses=False: Pausen bekommen keine eigene Zeile (sehr niedrige Fenster)."""
        segs, r = [], 0
        if early:
            segs.append(("early", 0, 0, raster.minutes(DS[0][1]), r, 1))
            r += 1
        for i, (n, a, b) in enumerate(DS):
            kk = k + (1 if i < extra else 0)
            segs.append(("ds", n, raster.minutes(a), raster.minutes(b), r, kk))
            r += kk
            if i < len(DS) - 1:
                if pauses:
                    segs.append(("pause", n, raster.minutes(b), raster.minutes(DS[i + 1][1]), r, 1))
                    r += 1
                else:
                    segs.append(("pause", n, raster.minutes(b), raster.minutes(DS[i + 1][1]), r, 0))
        if late:
            segs.append(("late", 0, raster.minutes(DS[-1][2]), 24 * 60, r, 1))
            r += 1
        return segs, r


    @staticmethod
    def row_at(segs, minute):
        for kind, n, a, b, r0, h in segs:
            if a <= minute < b or (kind == "late" and minute >= a):
                return r0 + (minute - a) / max(1, b - a) * h
        if segs and minute < segs[0][2]:
            return segs[0][4]
        return segs[-1][4] + segs[-1][5] if segs else 0

    def lanes(self, items):
        """Überlappende Termine nebeneinander: [(occ, lane, n_lanes)]."""
        out, active = [], []
        groups, cur, cur_end = [], [], None
        for o in sorted(items, key=lambda o: (o["s"], -(o["e"] - o["s"]).total_seconds())):
            if cur and o["s"] >= cur_end:
                groups.append(cur)
                cur, cur_end = [], None
            cur.append(o)
            cur_end = max(cur_end, o["e"]) if cur_end else o["e"]
        if cur:
            groups.append(cur)
        for grp in groups:
            ends = []
            placed = []
            for o in grp:
                for i, e in enumerate(ends):
                    if e <= o["s"]:
                        ends[i] = o["e"]
                        placed.append((o, i))
                        break
                else:
                    ends.append(o["e"])
                    placed.append((o, len(ends) - 1))
            out.extend((o, lane, len(ends)) for o, lane in placed)
        return out

    def event_lines(self, o, w):
        icons = ""
        if o.get("pending"):
            icons += "⟳"
        if o.get("series") or o.get("rrule"):
            icons += "↻"
        short = CAT_SHORT.get(o.get("cat"), "○")
        title = o["title"] if o["title"].split(" ", 1)[0] in (short, short + ":", "VL", "Ü:", "V:") else f"{short} {o['title']}"
        if o.get("conflict"):
            icons += "⚡"
        if icons:
            title += " " + icons
        lines = [title]
        if o.get("location"):
            lines.append("⌂ " + o["location"])
        lines.append(self.span_text(o) or f"{self.clock(o['s'])}–{self.clock(o['e'])}")
        if o.get("conflict"):
            lines.append("⚡ überschneidet: " + ", ".join(dict.fromkeys(o["conflict"])))
        if o.get("meet"):
            lines.append("󰍬 Meet")
        if o.get("tz") and not o.get("allday"):
            try:
                z = ZoneInfo(o["tz"])
                a = o["s"].replace(tzinfo=TZ).astimezone(z)
                lines.append(f"󰖟 {a:%H:%M} {a.tzname()}")
            except Exception:  # noqa: BLE001
                pass
        if o.get("link"):
            lines.append("󰂚 notist" if o["link"].startswith(st.NOTIST_LINK) else
                         "󰌹 " + re.sub(r"^https?://(www\.)?", "", o["link"]))
        return lines

    def draw_event(self, g, o, c, r, w, h, selected=False):
        p = self.pal
        col = p.cat(o.get("cat"), o.get("tone"))
        g.region(c, r, w, h, ("event", o))
        g.fill(c, r, w, h, col, 0.34 if selected else 0.16)
        lines = self.event_lines(o, w)
        if h >= 3 and w >= 6:
            g.box(c, r, w, h, col, 1.0 if selected else 0.85, heavy=o.get("cat") == "pruefung")
            inner = w - 2
            for i, line in enumerate(lines[:h - 2]):
                g.text(c + 1, r + 1 + i, line, p.fg if i == 0 else col, 1.0 if i == 0 else 0.95, maxw=inner)
            if selected:
                g.text(c, r, "┏", col)
            if o.get("conflict"):                       # Überschneidung: Blitz in der Rahmenecke (immer sichtbar)
                g.erase(c + w - 3, r, 2)
                g.text(c + w - 3, r, "⚡", p.tones["alert"])
        else:
            for i in range(h):
                g.text(c, r + i, "▌", col)
            for i, line in enumerate(lines[:h]):
                g.text(c + 1, r + i, line, p.fg if i == 0 else col, maxw=w - 1)
            if o.get("conflict") and w >= 3:
                g.text(c + w - 2, r, "⚡", p.tones["alert"])

    # ----- Woche -----
    def week_days(self, cols=None, gut=8):
        """Sichtbare Tage: ganze Woche, bei wenig Breite Mo–Fr, 3 Tage um den Cursor oder nur der Cursor-Tag."""
        ws = raster.week_start(self.cursor)
        full = [ws + dt.timedelta(days=i) for i in range(7 if self.store.settings.get("weekend", True) else 5)]
        if cols is None:
            return full
        avail = cols - gut - 1
        if avail // len(full) >= 9:
            return full
        if avail // 5 >= 9 and self.cursor.weekday() < 5:
            return full[:5]
        if avail // 3 >= 8:
            i = self.cursor.weekday()
            s = min(max(i - 1, 0), 4)
            return [ws + dt.timedelta(days=s + j) for j in range(3)]
        return [self.cursor]


    def render_week(self, g, cols, rows):
        p = self.pal
        gut = 8 if cols >= 70 else 6
        days = self.week_days(cols, gut)
        nd = len(days)
        a, b = days[0], days[-1] + dt.timedelta(days=1)
        occ = self.occ(a, b)
        allday = [o for o in occ if self.is_long(o)]
        timed = [o for o in occ if not self.is_long(o)]
        early = any(o["s"].time() < dt.time(*DS[0][1]) or (o["s"].date() < o["e"].date() and o["e"].time() > dt.time())
                    for o in timed)
        late = any(o["e"].time() > dt.time(*DS[-1][2]) or o["e"].date() > o["s"].date() for o in timed)
        # ganztägige/mehrtägige Termine als Balken über die Tage, in Bahnen übereinander
        bars, ends = [], []
        for o in sorted(allday, key=lambda o: (o["s"], -(o["e"] - o["s"]).total_seconds())):
            fi = max(0, (o["s"].date() - a).days)
            li = min(nd - 1, (self.last_day(o) - a).days)
            if fi > li:
                continue
            for lane, end in enumerate(ends):
                if end < fi:
                    ends[lane] = li
                    break
            else:
                ends.append(li)
                lane = len(ends) - 1
            bars.append((o, fi, li, lane))
        max_lanes = 3 if rows >= 30 else 2 if rows >= 22 else 1
        n_lanes = min(len(ends), max_lanes)
        top = 2 + n_lanes                            # Rahmen-Titel + Tageszeile (+ Balken)
        r0 = top + 1                                  # nach der Trennlinie
        avail = rows - r0 - 1                         # Zeilen für das Raster (unten der Rahmen)
        free = avail - (1 if early else 0) - (1 if late else 0)
        if free >= 7 * 2 + 6:                         # genug Platz: DS mit Pausenzeilen
            k, pauses = (free - 6) // 7, True
            extra = (free - 6) - 7 * k
        elif free >= 7:                               # eng: Pausen ohne eigene Zeile
            k, pauses = free // 7, False
            extra = free - 7 * k
        else:                                         # sehr eng: kleinstes Raster, scrollt mit dem Cursor
            k, pauses, extra = 1, False, 0
        segs, grid_h = self.time_rows(k, early, late, extra, pauses)
        dw = max(4, (cols - gut - 1) // nd)
        width = min(cols, gut + dw * nd + 1)
        kwn = raster.kw(self.cursor)
        even = kwn % 2 == 0
        par_col = p.primary if even else p.tones["tertiary"]
        title = f"KW {kwn} ◆ {'gerade' if even else 'ungerade'}" if width >= 30 else f"KW {kwn} {'g' if even else 'u'}"
        wk = [d for d in days if d.weekday() < 5]
        wstate = self.store.week_state(wk) if wk else None
        if wstate in ("frei", "pruefung") and width >= 44:
            title += "  ·  " + ("vorlesungsfrei" if wstate == "frei" else "prüfungsphase")
        if nd >= 5:
            last = days[-1]
            rng = f"{a.day}.{'' if a.month == last.month else f'{a.month}.'}–{last.day}. {MONTHS[last.month - 1]} {last.year}"
            if width < 70:
                rng = f"{a.day}.{a.month}.–{last.day}.{last.month}."
        else:
            rng = f"{MONTHS[a.month - 1]} {a.year}"
        box_h = min(rows, r0 + min(grid_h, avail) + 1)
        g.box(0, 0, width, box_h, p.primary, 0.55, title=title, title_color=par_col, rounded=True, right=rng)
        today = dt.date.today()
        # Tage
        for i, d in enumerate(days):
            c = gut + i * dw
            if dw >= 11:
                lab = f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}."
            elif dw >= 6:
                lab = f"{WEEKDAYS[d.weekday()]} {d.day}"
            else:
                lab = f"{d.day}"
            if nd == 1 and width >= 24:
                lab = f"{WEEKDAYS_LONG[d.weekday()]} {d.day}.{d.month}."
            x = c + 1 + max(0, (dw - 1 - len(lab)) // 2)
            hname = self.store.day_state(d)
            if d == today:
                g.fill(c + 1, 1, dw - 1, 1, p.primary, 1.0)
                g.text(x, 1, lab, p.on_primary, maxw=dw - 1)
            elif hname:                                 # Feiertag: Tag in der Warnfarbe, Name im Tooltip der Region
                g.text(x, 1, lab, p.tones["tertiary"], 1.0, maxw=dw - 1)
            else:
                g.text(x, 1, lab, p.fg, 0.55 if d.weekday() >= 5 else 1.0, maxw=dw - 1)
            if d == self.cursor and d != today and nd > 1:
                g.text(c + 1, 1, "▸", p.primary)
            g.region(c + 1, 1, dw - 1, 1, ("day", d))
        if nd < len(self.week_days()):               # Hinweis: es gibt weitere Tage links/rechts
            if days[0] > raster.week_start(self.cursor):
                g.text(gut, 1, "‹", p.primary)
            if days[-1] < self.week_days()[-1]:
                g.text(width - 2, 1, "›", p.primary)
        if bars:
            g.text(1, 2, "ganzt." if gut >= 8 else "gzt", p.fg, 0.5)
            hidden = [0] * nd
            for o, fi, li, lane in bars:
                if lane >= n_lanes:
                    for i in range(fi, li + 1):
                        hidden[i] += 1
                    continue
                c = gut + fi * dw + 1
                w = (li - fi + 1) * dw - 1
                rr = 2 + lane
                col = p.cat(o.get("cat"), o.get("tone"))
                sel = o["uid"] == self.focus_uid
                g.fill(c, rr, w, 1, col, 0.4 if sel else 0.25)
                cont_l = o["s"].date() < days[fi]
                cont_r = self.last_day(o) > days[li]
                t = ("◂" if cont_l else "▌") + ("" if o.get("allday") or cont_l else f"{o['s']:%H:%M} ") + o["title"]
                g.text(c, rr, t, col, maxw=w - (1 if cont_r else 0))
                if cont_r:
                    g.text(c + w - 1, rr, "▸", col)
                g.region(c, rr, w, 1, ("event", o))
            for i, n in enumerate(hidden):
                if n:
                    lab = f"+{n}"
                    g.text(gut + i * dw + dw - len(lab), 1 + n_lanes, lab, p.fg, 0.8, bg=(p.bg, 0.9))
        g.text(0, top, "├" + "─" * (width - 2) + "┤", p.primary, 0.35)
        # Scrollen, wenn das Raster nicht ganz passt: Cursor-DS bleibt sichtbar
        cur = next((s for s in segs if s[0] == "ds" and s[1] - 1 == self.slot), None)
        self.week_overflow = grid_h > avail
        if self.week_overflow and cur:
            sr, sh = cur[4], cur[5]
            if sr < self.week_scroll:
                self.week_scroll = sr
            elif sr + sh > self.week_scroll + avail:
                self.week_scroll = sr + sh - avail
            self.week_scroll = max(0, min(self.week_scroll, grid_h - avail))
        else:
            self.week_scroll = 0
        g.off, g.clip = -self.week_scroll, (r0, r0 + avail)
        now = dt.datetime.now()
        for kind, n, sa, sb, sr, sh in segs:
            rr = r0 + sr
            if kind == "ds":
                if sh >= 2:
                    g.text(1, rr, f"{n}.DS", p.primary)
                    g.text(1, rr + 1, f"{sa // 60:02d}:{sa % 60:02d}", p.fg, 0.6)
                    if sh >= 3 and gut >= 6:
                        g.text(1, rr + sh - 1, f"{sb // 60:02d}:{sb % 60:02d}", p.fg, 0.35)
                elif gut >= 8:
                    g.text(1, rr, f"{n}·{sa // 60}:{sa % 60:02d}", p.primary)
                else:
                    g.text(1, rr, f"{n}.DS", p.primary)
                if not pauses:                         # ohne Pausenzeilen: feine Linie oben im DS
                    for i in range(nd):
                        if n > 1:
                            g.text(gut + i * dw + 1, rr, "╌" * (dw - 1), p.fg, 0.08)
                for i, d in enumerate(days):
                    g.region(gut + i * dw + 1, rr, dw - 1, sh, ("slot", d, n - 1))
            elif kind == "pause" and sh:
                g.text(1, rr, " ┄┄┄ "[:gut - 1], p.fg, 0.25)
                for i in range(nd):
                    g.text(gut + i * dw + 1, rr, "┄" * (dw - 1), p.fg, 0.12)
            elif kind in ("early", "late"):
                g.text(1, rr, "früh" if kind == "early" else "spät", p.fg, 0.5)
                for i in range(nd):
                    g.text(gut + i * dw + 1, rr, "·" * (dw - 1), p.fg, 0.1)
        for i in range(1, nd):
            c = gut + i * dw
            for rr in range(r0, r0 + grid_h):
                g.text(c, rr, "│", p.fg, 0.1)
        if self.cursor in days and cur:
            i = days.index(self.cursor)
            rr, sh = r0 + cur[4], cur[5]
            g.fill(gut + i * dw + 1, rr, dw - 1, sh, p.primary, 0.09)
            g.text(gut + i * dw, rr, "▶", p.primary)
        if today in days:                              # heutige Spalte leicht hinterlegt
            g.fill(gut + days.index(today) * dw + 1, r0, dw - 1, grid_h, p.tones["alert"], 0.07)
        day_a, day_b = raster.minutes(DS[0][1]), raster.minutes(DS[-1][2])
        for i, d in enumerate(days):
            items = [o for o in timed if o["s"].date() <= d <= self.last_day(o)]     # auch über Mitternacht
            for o, lane, nl in self.lanes(items):
                sm = o["s"].hour * 60 + o["s"].minute if o["s"].date() == d else 0
                em = o["e"].hour * 60 + o["e"].minute if o["e"].date() == d else 24 * 60
                if em <= day_a:
                    ra = self.row_at(segs, 0)
                    rb = ra + 1
                elif sm >= day_b:
                    ra = self.row_at(segs, 24 * 60 - 1)
                    rb = ra + 1
                else:
                    ra = self.row_at(segs, max(sm, day_a))
                    rb = self.row_at(segs, min(em, day_b))
                top_r = r0 + int(math.floor(ra + 0.001))
                h = max(1, int(math.ceil(rb - 0.001)) - int(math.floor(ra + 0.001)))
                lw = max(1, (dw - 1) // nl)
                c = gut + i * dw + 1 + lane * lw
                w = lw if lane < nl - 1 else (dw - 1) - lane * lw
                span = raster.ds_span(o["s"].time(), o["e"].time())
                sel = o["uid"] == self.focus_uid or (self.focus_uid is None and d == self.cursor and span and
                                                    span[0] <= self.slot + 1 <= span[1])
                self.draw_event(g, o, c, top_r, w, h, sel)
        if today in days:
            i = days.index(today)
            rf = r0 + self.row_at(segs, now.hour * 60 + now.minute)
            rr = int(rf)
            if r0 <= rr < r0 + grid_h:
                al = p.tones["alert"]
                rf = min(rf, r0 + grid_h - 0.05)
                g.hline(gut, rf, i * dw, al, 0.45, 1)          # übrige Tage: dünn
                g.hline(gut + i * dw, rf, dw, al, 1.0, 2, dot=True)    # heute: kräftig mit Punkt
                g.hline(gut + (i + 1) * dw, rf, (nd - i - 1) * dw, al, 0.45, 1)
                g.erase(0, rr, gut)                    # Uhrzeit links statt DS-Beschriftung
                lab = f"{now:%H:%M}" if gut >= 6 else "▶"
                g.fill(0, rr, len(lab), 1, al, 1.0)
                g.text(0, rr, lab, p.bg)
        g.off, g.clip = 0, None
        if self.week_overflow:                       # Scroll-Anzeige am rechten Rand
            pos = r0 + int(self.week_scroll / max(1, grid_h - avail) * (avail - 1))
            g.text(width - 1, pos, "┃", p.primary)

    def render_day(self, g, cols, rows):
        p = self.pal
        d = self.cursor
        occ = self.occ(d, d + dt.timedelta(days=1))
        width = cols
        even = raster.kw(d) % 2 == 0
        title = f"{WEEKDAYS_LONG[d.weekday()]}, {d.day}. {MONTHS[d.month - 1]} {d.year}"
        right = f"KW {raster.kw(d)} ◆ {'gerade' if even else 'ungerade'}"
        lines = []        # [(art, payload)]  – art: text/ds/pause/event
        allday = [o for o in occ if self.is_long(o)]
        timed = [o for o in occ if not self.is_long(o)]
        for o in allday:
            lines.append(("allday", o))
        # Zeiten auf diesen Tag begrenzt (Termine über Mitternacht)
        d0, d1 = dt.datetime.combine(d, dt.time()), dt.datetime.combine(d + dt.timedelta(days=1), dt.time())
        cs = lambda o: max(o["s"], d0)
        ce = lambda o: min(o["e"], d1)
        at = lambda t: dt.datetime.combine(d, t)
        early = [o for o in timed if ce(o) <= at(dt.time(*DS[0][1]))]
        if early:
            lines.append(("head", ("vor 07:30", None, None)))
            lines.extend(("event", o) for o in early)
        shown = {o["uid"] + str(o["s"]) for o in early}
        for i, (n, a, b) in enumerate(DS):
            sa, sb = dt.time(*a), dt.time(*b)
            lines.append(("ds", (n, sa, sb)))
            hits = [o for o in timed if cs(o) < at(sb) and ce(o) > at(sa) and o["uid"] + str(o["s"]) not in shown]
            for o in hits:
                shown.add(o["uid"] + str(o["s"]))
                lines.append(("event", o))
            if not hits:
                lines.append(("free", n - 1))
            if i < len(DS) - 1:
                pa, pb = sb, dt.time(*DS[i + 1][1])
                ph = [o for o in timed if o["uid"] + str(o["s"]) not in shown and cs(o) < at(pb)
                      and ce(o) > at(pa)]
                lines.append(("pause", (pa, pb)))
                for o in ph:
                    shown.add(o["uid"] + str(o["s"]))
                    lines.append(("event", o))
        late = [o for o in timed if o["uid"] + str(o["s"]) not in shown]
        if late:
            lines.append(("head", ("nach 20:00", None, None)))
            lines.extend(("event", o) for o in late)
        now = dt.datetime.now()
        if d == now.date():                           # „jetzt“-Linie an die passende Stelle
            hm = lambda t: t.hour * 60 + t.minute
            def when(k, x):
                if k == "allday":
                    return -1
                if k == "ds":
                    return hm(x[1])
                if k == "free":
                    return raster.minutes(DS[x][1])
                if k == "pause":
                    return hm(x[0])
                if k == "event":
                    return hm(cs(x).time()) if cs(x).date() == d else 0
                return 0 if x[0].startswith("vor") else raster.minutes(DS[-1][2])
            nm = hm(now.time())
            at_i = next((i for i, (k, x) in enumerate(lines) if when(k, x) > nm), len(lines))
            lines.insert(at_i, ("now", now))
        # Höhe je Zeile
        def height(kind, x):
            if kind == "event":
                n = 2 + 1 + (1 if x.get("link") else 0) + min(3, len((x.get("notes") or "").splitlines()))
                return max(3, n)
            return 1
        total = sum(height(k, x) for k, x in lines)
        avail = rows - 2
        # Cursor-DS sichtbar halten
        pos, cursor_row = 0, 0
        for k, x in lines:
            if k == "ds" and x[0] - 1 == self.slot:
                cursor_row = pos
            pos += height(k, x)
        if cursor_row < self.day_scroll:
            self.day_scroll = cursor_row
        elif cursor_row + 6 > self.day_scroll + avail:
            self.day_scroll = max(0, cursor_row + 6 - avail)
        self.day_scroll = max(0, min(self.day_scroll, max(0, total - avail)))
        g.box(0, 0, width, rows, p.primary, 0.55, title=title, rounded=True, right=right,
              title_color=p.primary if d == dt.date.today() else p.fg)
        r = 1 - self.day_scroll
        for k, x in lines:
            h = height(k, x)
            if r + h <= 1:
                r += h
                continue
            if r >= rows - 1:
                break
            vis = 1 <= r < rows - 1
            if k == "ds":
                n, sa, sb = x
                active = d == now.date() and sa <= now.time() < sb
                sel = n - 1 == self.slot
                head = f" {n}. DS  {sa:%H:%M} – {sb:%H:%M} "
                if vis:
                    if sel:
                        g.fill(1, r, width - 2, 1, p.primary, 0.14)
                        g.text(1, r, "▶", p.primary)
                    g.text(2, r, head, p.tones["alert"] if active else p.primary)
                    g.text(2 + len(head), r, "─" * (width - 4 - len(head)), p.primary, 0.25)
                    if active:
                        g.text(width - 9, r, " jetzt ", p.tones["alert"])
                    g.region(1, r, width - 2, 1, ("slot", d, n - 1))
            elif k == "now":
                if vis:
                    al = p.tones["alert"]
                    lab = f"━━ ● jetzt {x:%H:%M} "
                    g.fill(1, r, width - 2, 1, al, 0.16)
                    g.text(1, r, lab, al)
                    g.text(1 + len(lab), r, "━" * max(0, width - 3 - len(lab)), al, 0.8)
            elif k == "pause":
                pa, pb = x
                if vis:
                    g.text(4, r, f"┄┄ Pause {pa:%H:%M}–{pb:%H:%M} ┄┄", p.fg, 0.3)
            elif k == "head":
                if vis:
                    g.text(2, r, f" {x[0]} ", p.fg, 0.6)
            elif k == "free":
                if vis:
                    g.text(6, r, "· frei", p.fg, 0.25)
                    g.region(1, r, width - 2, 1, ("slot", d, x))
            elif k == "allday":
                if vis:
                    col = p.cat(x.get("cat"), x.get("tone"))
                    g.fill(2, r, width - 4, 1, col, 0.22)
                    rng = self.span_text(x)
                    if rng:
                        n_days = (self.last_day(x) - x["s"].date()).days + 1
                        lab = f"tag {(d - x['s'].date()).days + 1}/{n_days} · {rng}"
                    else:
                        lab = "ganztägig" if x.get("allday") else f"{x['s']:%H:%M}–{x['e']:%H:%M}"
                    sel = x["uid"] == self.focus_uid
                    if sel:
                        g.fill(2, r, width - 4, 1, col, 0.4)
                    g.text(2, r, f"▌{lab}  {x['title']}", col, maxw=width - 4)
                    g.region(2, r, width - 4, 1, ("event", x))
            elif k == "event":
                o = x
                col = p.cat(o.get("cat"), o.get("tone"))
                c0, w = 6, width - 8
                top = max(r, 1)
                hh = min(r + h, rows - 1) - top
                if hh > 0:
                    sel = o["uid"] == self.focus_uid
                    past = o["e"] <= now
                    running = o["s"] <= now < o["e"]
                    fade = 0.5 if past and not sel else 1.0
                    g.fill(c0, top, w, hh, col, 0.3 if sel else 0.2 if running else 0.13 * fade)
                    g.region(c0, top, w, hh, ("event", o))
                    if r >= 1:
                        span = raster.ds_span(o["s"].time(), o["e"].time())
                        ds_txt = (f"{span[0]}. DS" if span[0] == span[1] else f"{span[0]}.–{span[1]}. DS") if span else ""
                        right = self.span_text(o) or f"{o['s']:%H:%M}–{o['e']:%H:%M} {ds_txt}"
                        if running:
                            right = f"● läuft · bis {o['e']:%H:%M}"
                        g.box(c0, r, w, h if r + h < rows else rows - r, p.tones["alert"] if running else col,
                              1.0 if sel or running else 0.85 * fade,
                              title=f"{CAT_NAMES.get(o.get('cat'), '')} · {o['title']}",
                              title_color=p.fg if fade == 1.0 else col, right=right, heavy=running)
                    body = []
                    meta = []
                    head_len = len(f"{CAT_NAMES.get(o.get('cat'), '')} · {o['title']}") + 22
                    if head_len > w - 2:              # Zeit passt nicht in den Rahmen → in die Detailzeile
                        meta.append(f"{o['s']:%H:%M}–{o['e']:%H:%M}")
                    if o.get("location"):
                        meta.append("⌂ " + o["location"])
                    cal = next((c["name"] for c in self.store.all_calendars() if c["id"] == o["cal"]), "")
                    if o.get("series") or o.get("rrule"):
                        meta.append("↻ " + (rrule.describe(o["rrule"], o["s"]) if o.get("rrule") else "Serie"))
                    if o.get("pending"):
                        meta.append("⟳ noch nicht bei Google")
                    meta.append("◇ " + cal)
                    body.append(("   ".join(meta), col))
                    if o.get("link"):
                        body.append(("󰂚 aus notist – im Termin „öffnen“ springt hin" if o["link"].startswith(st.NOTIST_LINK)
                                     else "󰌹 " + o["link"], p.tones["secondary"]))
                    for ln in (o.get("notes") or "").splitlines()[:3]:
                        body.append((ln, p.fg))
                    for i, (txt, cc) in enumerate(body):
                        rr = r + 1 + i
                        if 1 <= rr < min(r + h - 1, rows - 1):
                            g.text(c0 + 2, rr, txt, cc, 0.9 * fade, maxw=w - 4)
            r += h
        if total > avail:
            frac = self.day_scroll / max(1, total - avail)
            g.text(width - 1, 1 + int(frac * (rows - 3)), "┃", p.primary)

    # ----- Monat -----
    def render_month(self, g, cols, rows):
        p = self.pal
        first = self.cursor.replace(day=1)
        start = raster.week_start(first)
        weeks = 6
        end = start + dt.timedelta(days=7 * weeks)
        occ = self.occ(start, end)
        by_day = {}
        for o in occ:
            d = o["s"].date()
            last = max(d, (o["e"] - dt.timedelta(seconds=1)).date())
            while d <= last and d < end:
                by_day.setdefault(d, []).append(o)
                d += dt.timedelta(days=1)
        kwc = 5 if cols >= 48 else 4
        dw = max(3, (cols - kwc - 1) // 7)
        width = min(cols, kwc + dw * 7 + 1)
        lines = rows - 3                               # ohne Titel-, Wochentags- und Abschlusszeile
        sep = lines >= weeks * 3                       # Trennlinien zwischen Wochen nur, wenn Platz ist
        hh = max(1, lines // weeks)
        height = min(rows, 2 + hh * weeks + 1)
        right = f"KW {raster.kw(start)}–{raster.kw(end - dt.timedelta(days=1))}"
        g.box(0, 0, width, height, p.primary, 0.55, title=f"{MONTHS[first.month - 1]} {first.year}",
              title_color=p.fg, rounded=True, right=right)
        for i in range(7):
            lab = WEEKDAYS_LONG[i] if dw >= 12 else WEEKDAYS[i] if dw >= 3 else WEEKDAYS[i][0]
            g.text(kwc + i * dw + 1 + (1 if dw >= 5 else 0), 1, lab, p.fg, 0.5 if i >= 5 else 0.85, maxw=dw - 1)
        g.text(1, 1, "KW", p.fg, 0.5)
        today = dt.date.today()
        now = dt.datetime.now()
        maxn = max([len(v) for v in by_day.values()] + [1])
        for w in range(weeks):
            r = 2 + w * hh
            wd0 = start + dt.timedelta(days=7 * w)
            kwn = raster.kw(wd0)
            even = kwn % 2 == 0
            pc = p.primary if even else p.tones["tertiary"]
            body = r + (1 if sep else 0)              # erste Inhaltszeile
            bh = hh - (1 if sep else 0)
            if sep:
                g.text(0, r, "├" + "─" * (width - 2) + "┤", p.primary, 0.3)
                for i in range(8):
                    g.text(kwc + i * dw, r, "┼" if i < 7 else "┤", p.primary, 0.3)
            g.text(1, body, f"{kwn:>2}" + ("" if bh > 1 else ("g" if even else "u")), pc)
            if bh > 1:
                g.text(1, body + 1, "g" if even else "u", pc, 0.7)
            if even:
                g.fill(1, body, kwc - 1, bh, pc, 0.06)
            g.region(1, body, kwc - 1, bh, ("week", wd0))
            for rr in range(body, body + bh):
                for i in range(8):
                    g.text(kwc + i * dw, rr, "│", p.primary, 0.3)
            for i in range(7):
                d = wd0 + dt.timedelta(days=i)
                c = kwc + i * dw + 1
                cw = dw - 1
                inmonth = d.month == first.month
                al = 1.0 if inmonth else 0.35
                g.region(c, body, cw, bh, ("day", d))
                g.region(c, body, min(cw, 4), 1, ("dayhead", d))
                if d == self.cursor:
                    g.fill(c, body, cw, bh, p.primary, 0.16)
                num = f"{d.day:>2}"
                nx = c + (1 if cw >= 4 else 0)
                if d == today:
                    sig = p.tones["alert"]
                    g.fill(c, body, cw, bh, sig, 0.09)
                    g.fill(nx, body, 2, 1, p.primary, 1.0)
                    g.text(nx, body, num, p.on_primary)
                    for rr in range(body, body + bh):    # Rahmen links/rechts in Signalfarbe
                        g.erase(c - 1, rr, 1)
                        g.erase(c + cw, rr, 1)
                        g.text(c - 1, rr, "┃", sig)
                        g.text(c + cw, rr, "┃", sig)
                    if cw >= 13:
                        g.text(nx + 3, body, f"{now:%H:%M}", sig)
                elif self.store.day_state(d):                       # Feiertag: Zahl in der Warnfarbe
                    g.text(nx, body, num, p.tones["tertiary"], al)
                else:
                    g.text(nx, body, num, p.fg, al * (0.6 if d.weekday() >= 5 else 1.0))
                evs = by_day.get(d, [])
                if not evs:
                    continue
                # Dichte: ▁…█ relativ zum vollsten Tag (+ Anzahl, wenn Platz ist)
                lvl = "▁▂▃▄▅▆▇█"[min(7, round(len(evs) / maxn * 7))]
                dens = f"{lvl}{len(evs)}" if cw >= 7 else lvl
                g.text(c + cw - len(dens), body, dens, p.primary, al)
                room = bh - 1
                if room <= 0:
                    continue
                if cw < 5:                     # schmale Zellen: ein farbiger Punkt je Termin
                    for j, o in enumerate(evs[:cw]):
                        g.text(c + j, body + 1, "▪", p.cat(o.get("cat"), o.get("tone")), al)
                        g.region(c + j, body + 1, 1, 1, ("event", o))
                    continue
                show = evs[:room] if len(evs) <= room else evs[:room - 1]
                for j, o in enumerate(show):
                    col = p.cat(o.get("cat"), o.get("tone"))
                    ea = 0.45 if d == today and o["e"] <= now else al
                    cont = o["s"].date() < d                     # mehrtägig: Folgetag
                    t = ("↦ " if cont else "" if o.get("allday") or cw < 12 else f"{o['s']:%H:%M} ") + o["title"]
                    if self.last_day(o) > o["s"].date():
                        g.fill(c, body + 1 + j, cw, 1, col, 0.2 * ea)
                    g.text(c, body + 1 + j, "▌", col, ea)
                    g.text(c + 1, body + 1 + j, t, p.fg, 0.85 * ea, maxw=cw - 1)
                    g.region(c, body + 1 + j, cw, 1, ("event", o))
                if len(evs) > room and room >= 2:
                    g.text(c + 1, body + room, f"+{len(evs) - len(show)} weitere", p.fg, 0.5 * al, maxw=cw - 1)
                    g.region(c, body + room, cw, 1, ("dayhead", d))
        g.text(0, height - 1, "╰" + "─" * (width - 2) + "╯", p.primary, 0.55)
        for i in range(7):
            g.text(kwc + i * dw, height - 1, "┴", p.primary, 0.3)

    def on_hit(self, view, hit, n, button):
        kind = hit[0]
        if kind == "event" and hit[1].get("cal") == "tasks":
            self.toggle_task(hit[1])                 # Aufgabe anklicken = abhaken / wieder öffnen
            return
        if kind == "event":
            o = hit[1]
            self.focus_uid = o["uid"]
            self.cursor = o["s"].date()
            if o["s"].time() and not o.get("allday"):
                span = raster.ds_span(o["s"].time(), o["e"].time())
                if span:
                    self.slot = span[0] - 1
            self.edit(o)                     # ein Klick öffnet den Termin (in jeder Ansicht)
        elif kind == "slot":
            self.cursor, self.slot = hit[1], hit[2]
            self.focus_uid = None
            if n >= 2:
                self.editor.open(day=self.cursor, ds=self.slot + 1)
        elif kind == "day":                  # Wochen-Kopf / Monatsfeld
            self.cursor = hit[1]
            self.focus_uid = None
            if n >= 2 or view == "week":
                self.win.show_tab("day")
        elif kind == "dayhead":              # Monat: Tageszahl oder „+N weitere“ → Tagesansicht
            self.cursor = hit[1]
            self.focus_uid = None
            self.win.show_tab("day")
        elif kind == "week":
            self.cursor = hit[1]
            self.win.show_tab("week")
        self.after_move()

    def edit(self, o):
        src = self.store.find(o["uid"]) or o
        ev = {k: v for k, v in o.items() if k not in ("s", "e", "occ")}
        if src.get("rrule"):          # lokale Serie: diese Instanz mit ihrem Datum zeigen
            dur = o["e"] - o["s"]
            ev["start"], ev["end"] = st.iso(o["s"], o.get("allday")), st.iso(o["s"] + dur, o.get("allday"))
        self.editor.open(ev, orig=o)

    def move_event(self, o, tgt):
        """Termin o (Anzeige-Instanz) auf das Ziel tgt (dragmove.target_at) verschieben; die Dauer bleibt."""
        if self.store.is_readonly(o):
            self.win.say("nur lesbar – lässt sich nicht verschieben", error=True)
            return
        d, ds = tgt["day"], tgt.get("ds")
        allday = bool(o.get("allday"))
        dur = o["e"] - o["s"]
        long_ = allday or dur >= dt.timedelta(hours=20)
        if ds is not None and not long_:
            ns = dt.datetime.combine(d, raster.ds_times(ds + 1)[0])        # auf den Beginn der Doppelstunde
        else:
            ns = dt.datetime.combine(d, o["s"].time())                      # nur den Tag wechseln
        if ns == o["s"]:
            return
        ev = {k: v for k, v in o.items() if k not in ("s", "e", "occ", "conflict")}
        ev["start"], ev["end"] = st.iso(ns, allday), st.iso(ns + dur, allday)
        scope = "instance" if (o.get("series") or o.get("rrule")) else "single"
        try:
            self.store.save_event(ev, scope=scope, original=o)
        except ValueError as e:
            self.win.say(str(e), error=True)
            return
        self.cursor = d
        when = f"{WEEKDAYS[ns.weekday()]} {ns.day}.{ns.month}." + ("" if allday else f" {ns:%H:%M}")
        self.focus_uid = o.get("uid")
        self.after_edit(f"verschoben: {o.get('title')} → {when}")

    def toggle_task(self, o):
        tid, done = o.get("task_id"), not o.get("done")
        self.store.set_task_done(tid, done)
        self.win.say(("☑ erledigt: " if done else "☐ wieder offen: ") + o["title"][2:])
        self.redraw()
        if gcal.logged_in():
            GLib.timeout_add(800, lambda: self.sync() and False)

    def resize_event(self, o, tgt):
        """Dauer ändern: neues Ende aus dragmove.resize_target_at (Ende einer Doppelstunde)."""
        if self.store.is_readonly(o):
            self.win.say("nur lesbar – lässt sich nicht ändern", error=True)
            return
        end = tgt["end"]
        if end == o["e"]:
            return
        ev = {k: v for k, v in o.items() if k not in ("s", "e", "occ", "conflict")}
        ev["start"], ev["end"] = st.iso(o["s"], False), st.iso(end, False)
        scope = "instance" if (o.get("series") or o.get("rrule")) else "single"
        try:
            self.store.save_event(ev, scope=scope, original=o)
        except ValueError as e:
            self.win.say(str(e), error=True)
            return
        self.focus_uid = o.get("uid")
        self.after_edit(f"Dauer geändert: {o.get('title')} → bis {end:%H:%M}")

    def after_move(self):
        self.store.settings["cursor"] = self.cursor.isoformat()
        self.redraw()
        win = self.store.window
        if win and gcal.logged_in():
            a = dt.datetime.fromisoformat(win[0]).date()
            b = dt.datetime.fromisoformat(win[1]).date()
            if not (a + dt.timedelta(days=30) <= self.cursor <= b - dt.timedelta(days=60)):
                self.sync()

    def on_scroll(self, view, n):
        """n: gesammelte Rasten (Touchpad wird in Cells.gebremst). Blättern höchstens alle 0,25 s."""
        if view == "day":
            self.day_scroll = max(0, self.day_scroll + 3 * n)
            self.views["day"].queue_draw()
            return
        if view == "week" and getattr(self, "week_overflow", False):
            self.slot = max(0, min(6, self.slot + (1 if n > 0 else -1)))   # kleines Fenster: im Raster scrollen
            self.focus_uid = None
            self.redraw()
            return
        now = time.monotonic()
        if now - getattr(self, "_last_flip", 0) < 0.25:
            return
        self._last_flip = now
        d = 1 if n > 0 else -1
        if view == "week":
            self.move_day(7 * d)
        else:
            self.cursor = self.add_months(self.cursor, d)
            self.after_move()

    @staticmethod
    def add_months(d, n):
        m = d.month - 1 + n
        y = d.year + m // 12
        m = m % 12 + 1
        import calendar
        return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))

    def move_day(self, n):
        self.cursor += dt.timedelta(days=n)
        self.focus_uid = None
        self.after_move()

    def day_events(self, d):
        return [o for o in self.occ(d, d + dt.timedelta(days=1))]

    def cycle(self, step):
        evs = self.day_events(self.cursor)
        if not evs:
            return
        uids = [o["uid"] for o in evs]
        i = uids.index(self.focus_uid) if self.focus_uid in uids else -1
        o = evs[(i + step) % len(evs)]
        self.focus_uid = o["uid"]
        span = raster.ds_span(o["s"].time(), o["e"].time()) if not o.get("allday") else None
        if span:
            self.slot = span[0] - 1
        self.redraw()

    def focused(self):
        evs = self.day_events(self.cursor)
        o = next((o for o in evs if o["uid"] == self.focus_uid), None)
        if o:
            return o
        for o in evs:
            span = raster.ds_span(o["s"].time(), o["e"].time()) if not o.get("allday") else None
            if span and span[0] <= self.slot + 1 <= span[1]:
                return o
        return None

    def on_key(self, ctrl, kv, code, state):
        if self.editor.get_visible() or self.quick_rev.get_reveal_child():
            return False
        if (state & Gdk.ModifierType.ALT_MASK and not state & Gdk.ModifierType.CONTROL_MASK
                and Gdk.KEY_1 <= kv <= Gdk.KEY_9):          # Alt+Zahl = Tab wechseln (auch beim Tippen)
            i = kv - Gdk.KEY_1
            if i < len(self.win.tab_btns):
                self.focus_uid = None
                self.win.tab_btns[i][1].set_active(True)
            return True
        focus = self.win.get_focus()
        if isinstance(focus, (Gtk.Text, Gtk.TextView)):
            return False
        view = self.win.current_tab()
        if view == "acct":
            return False
        if view == "agenda" and not state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            if kv in (Gdk.KEY_j, Gdk.KEY_Down):
                self.agenda.move(1)
                return True
            if kv in (Gdk.KEY_k, Gdk.KEY_Up):
                self.agenda.move(-1)
                return True
            if kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
                return False                       # der fokussierte Termin-Knopf öffnet sich selbst
            if kv in (Gdk.KEY_h, Gdk.KEY_l, Gdk.KEY_H, Gdk.KEY_L, Gdk.KEY_Left, Gdk.KEY_Right):
                return True
        if state & Gdk.ModifierType.CONTROL_MASK and not state & Gdk.ModifierType.ALT_MASK \
                and kv in (Gdk.KEY_z, Gdk.KEY_Z):
            self.undo()
            return True
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        ch = Gdk.keyval_to_unicode(kv)
        k = chr(ch) if ch else ""
        if kv in (Gdk.KEY_Left,):
            k = "h"
        elif kv == Gdk.KEY_Right:
            k = "l"
        elif kv == Gdk.KEY_Up:
            k = "k"
        elif kv == Gdk.KEY_Down:
            k = "j"
        if k == "h":
            self.move_day(-1)
        elif k == "l":
            self.move_day(1)
        elif k in ("j", "k"):
            d = 1 if k == "j" else -1
            if view == "month":
                self.move_day(7 * d)
            else:
                self.slot = max(0, min(6, self.slot + d))
                self.focus_uid = None
                self.redraw()
        elif k in ("H", "L", "[", "]"):
            d = -1 if k in ("H", "[") else 1
            if view == "month":
                self.cursor = self.add_months(self.cursor, d)
                self.after_move()
            else:
                self.move_day(d * (1 if view == "day" else 7))
        elif k == "b":
            self.toggle_desk()
        elif k == "d":
            self.win.show_tab("day")
        elif k == "w":
            self.win.show_tab("week")
        elif k == "m":
            self.win.show_tab("month")
        elif k == "t":
            self.go_today()
        elif k == "n":
            self.editor.open(day=self.cursor, ds=self.slot + 1)
        elif k == "a":
            self.open_quick()
        elif kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) or k == "e":
            o = self.focused()
            if o:
                self.edit(o)
            elif view == "month":
                self.win.show_tab("day")
            else:
                self.editor.open(day=self.cursor, ds=self.slot + 1)
        elif kv == Gdk.KEY_Tab:
            self.cycle(1)
        elif kv == Gdk.KEY_ISO_Left_Tab:
            self.cycle(-1)
        elif k == "x" or kv == Gdk.KEY_Delete:
            self.delete_focused()
        elif k == "s":
            self.sync(force=True)
        elif k == "g":
            self.open_quick(goto=True)
        elif k == "/":
            self.srch.open()
        elif k == "u":
            self.undo()
        elif k == "?":
            self.help.set_visible(not self.help.get_visible())
        elif k == "+" or k == "-":
            size = self.store.settings.get("font_size", 10) + (1 if k == "+" else -1)
            self.store.settings["font_size"] = max(7, min(16, size))
            self.store.save_settings()
            self.redraw()
        else:
            return False
        return True

    def undo(self):
        ok_, msg = self.store.undo()
        self.win.say(msg + ("   ·   u noch einmal für den davor" if ok_ and self.store.can_undo() else ""))
        self.redraw()
        if ok_ and gcal.logged_in():
            GLib.timeout_add(800, lambda: self.sync() and False)

    def delete_focused(self):
        o = self.focused()
        if not o:
            return
        if self.store.is_readonly(o):
            self.win.say(f"„{o['title']}“ ist nur lesbar (Abo oder Kalender ohne Schreibrecht)", error=True)
            return
        if self.del_armed != o["uid"]:
            self.del_armed = o["uid"]
            scope = " (nur dieser termin – serie im editor)" if o.get("series") or o.get("rrule") else ""
            self.win.say(f"„{o['title']}“ löschen? nochmal x{scope}")
            GLib.timeout_add(3000, lambda: setattr(self, "del_armed", None) or False)
            return
        self.del_armed = None
        scope = "instance" if (o.get("series") or o.get("rrule")) else "single"
        src = self.store.find(o["uid"]) or o
        self.store.delete_event(src if scope == "single" else o, scope=scope, original=o)
        self.focus_uid = None
        self.after_edit(f"gelöscht: {o['title']}")

    # ----- Schnelleingabe -----
    def open_quick(self, goto=False):
        self.quick_goto = goto
        self.quick.set_placeholder_text("gehe zu: heute, mi, +2w, 20.10., 2027-01-15" if goto else
                                        "schnell: V Mathe nächsten mi 14 Uhr für 2h @MA/041 #v !w   (esc abbrechen)")
        self.quick.set_text("")
        self.quick_rev.set_reveal_child(True)
        GLib.idle_add(lambda: self.quick.grab_focus() and False)

    def close_quick(self):
        self.quick_rev.set_reveal_child(False)
        self.focus_view()

    def quick_add(self):
        text = self.quick.get_text().strip()
        if not text:
            self.close_quick()
            return
        if self.quick_goto:
            try:
                self.cursor = raster.parse_date(text, self.cursor)
            except ValueError as e:
                self.win.say(str(e), error=True)
                return
            self.close_quick()
            self.after_move()
            return
        try:
            ev, rule_pid, until = self.parse_quick(text)
        except ValueError as e:
            self.win.say(str(e), error=True)
            return
        if rule_pid:
            s = st.parse_when(ev["start"], False)
            r, s2 = rrule.preset_rule(rule_pid, s, until=until)
            if s2 != s:
                dur = st.parse_when(ev["end"], False) - s
                ev["start"], ev["end"] = st.iso(s2), st.iso(s2 + dur)
            ev["rrule"] = r
        self.store.save_event(ev)
        self.cursor = st.parse_when(ev["start"], ev.get("allday")).date()
        self.close_quick()
        self.after_edit(f"angelegt: {ev['title']} · {raster.fmt_date(self.cursor)}"
                        + (f" · {rrule.describe(ev['rrule'], st.parse_when(ev['start'], False))}" if ev.get("rrule") else ""))

    def parse_quick(self, text):
        return quickparse.parse(text, self.cursor, raster.ds_times(self.slot + 1), self.store.default_cal())

    # =================================================================
    # Hilfe & Konto
    # =================================================================
    def build_help(self):
        rows = [("h j k l / ←↓↑→", "Tag bzw. Doppelstunde wechseln (Monat: Tag/Woche)"),
                ("H L / [ ]", "voriger/nächster Zeitraum"), ("d w m", "Tag-, Wochen-, Monatsansicht"),
                ("t", "heute"), ("b", "Termine auf dem Hintergrundbild ein/aus"), ("g", "gehe zu Datum"), ("/", "suchen (Titel, Ort, Notiz)"), ("n", "neuer Termin im markierten DS"),
                ("a", "Schnelleingabe:  V Mathe mi 2ds @MA/041 #v !u bis 5.2."),
                ("⏎ / e", "markierten Termin bearbeiten"), ("tab", "nächster Termin des Tages"),
                ("4", "Agenda: die nächsten 7/14/30 Tage (j k wählen, ⏎ öffnen)"), ("x x", "Termin löschen"), ("u / strg+z", "letzte Änderung rückgängig (Serien bei Google nicht)"), ("s / strg+r", "mit Google abgleichen"), ("+ −", "Schrift größer/kleiner"),
                ("1–3", "Tag / Woche / Monat"), ("esc", "schließen"),
                ("2 finger ← / maus 8", "zurück (endet in der Woche)"),
                ("2 finger zoom", "zusammen: Tag → Woche → Monat · auseinander: zurück"),
                ("klick", "Termin öffnen · Wochentag → Tagesansicht · KW / Tageszahl im Monat → Woche / Tag"),
                ("✓ 12:34 (oben)", "letzter Google-Abgleich – klicken = jetzt abgleichen")]
        quick = [("2ds  2-3ds  14-16  14 Uhr  2pm", "Zeit: Doppelstunde(n) oder Uhrzeit (um 14 Uhr, von 14 bis 16)"),
                 ("für 2h  90min  ganztägig", "Dauer bzw. ganztägig"),
                 ("mi  morgen  +3  20.10.", "Tag"),
                 ("nächsten mo  in 2 wochen  next fri", "Tag, auch übernächsten, nächste Woche, in 3 Tagen, English"),
                 ("@MA/041", "Ort"), ("#v #ü #s #p #! #privat", "Typ"),
                 ("!w !g !u !kg !ku !m", "wöchentl., 2-wö. gerade/ungerade, jede gerade/ungerade KW, monatl."),
                 ("bis 5.2.", "Serienende"), ("https://…", "Link")]
        p = tui.Panel("tasten")
        p.set_active(True)
        for k, v in rows:
            p.body.append(hbox(label(k, "accent", xalign=0), label(v, "help"), spacing=12))
            p.body.get_last_child().get_first_child().set_size_request(170, -1)
        p.body.append(label("schnelleingabe", "dim", xalign=0))
        for k, v in quick:
            p.body.append(hbox(label(k, "accent"), label(v, "help"), spacing=12))
            p.body.get_last_child().get_first_child().set_size_request(170, -1)
        box = vbox(p, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.add_css_class("editor-card")
        return box

    def build_account(self):
        self.acct = vbox(spacing=8)
        self.acct.set_margin_top(4)
        self.acct_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=90,
                                    vhomogeneous=False, hhomogeneous=True)
        pages = {}
        tabrow = hbox(spacing=2)
        tabrow.add_css_class("topbar")
        group = None
        self.acct_tabs = {}
        for pid, name in ACCT_PAGES:
            pages[pid] = vbox(spacing=8)
            self.acct_stack.add_named(pages[pid], pid)
            b = Gtk.ToggleButton()
            b.add_css_class("tab")
            b.set_child(label(name))
            if group:
                b.set_group(group)
            group = group or b
            b.connect("toggled", lambda b, pid=pid: b.get_active() and self.acct_stack.set_visible_child_name(pid))
            self.acct_tabs[pid] = b
            tabrow.append(b)
        self.acct.append(tabrow)
        self.acct.append(self.acct_stack)
        pages["allgemein"].append(tui.theme_panel())
        # Google
        self.g_panel = tui.Panel("google kalender")
        self.g_status = label("", markup=True, wrap=True)
        self.g_steps = vbox(spacing=4)
        self.g_btns = hbox(spacing=8)
        self.g_panel.body.append(self.g_status)
        self.g_panel.body.append(self.g_steps)
        self.g_panel.body.append(self.g_btns)
        pages["google"].append(self.g_panel)
        pages["google"].append(self.build_accounts_panel())
        pages["google"].append(self.build_tasks_panel())
        pages["leiste"].append(self.build_bar_panel())
        self.c_panel = tui.Panel("kalender")
        self.c_list = vbox(spacing=2)
        self.c_panel.body.append(self.c_list)
        pages["google"].append(self.c_panel)
        pages["kalender"].append(self.build_subs_panel())
        pages["kalender"].append(self.build_ics_panel())
        self.f_panel = tui.Panel("farben · aus dem design")
        self.f_area = Gtk.DrawingArea(content_height=60, hexpand=True)
        self.f_area.set_draw_func(self.draw_legend)
        self.f_panel.body.append(self.f_area)
        pages["allgemein"].append(self.f_panel)
        self.v_panel = tui.Panel("darstellung")
        self.v_week = tui.Check("wochenende in der wochenansicht", self.store.settings.get("weekend", True),
                                lambda on: (self.store.settings.__setitem__("weekend", on), self.store.save_settings(),
                                            self.redraw()))
        self.v_see = tui.Check("interne fenster durchsichtig (editor, hilfe)", self.store.settings.get("see_through", True),
                               lambda on: (self.store.settings.__setitem__("see_through", on), self.store.save_settings(),
                                           self.apply_see_through()))
        self.v_panel.body.append(wrapbox(self.v_week, self.v_see, label("schrift: + / − in den ansichten", "dim")))
        pages["allgemein"].append(self.v_panel)
        self.d_panel = tui.Panel("termine auf dem hintergrundbild")
        self.v_desk = tui.Check("termine auf dem hintergrundbild", self.store.settings.get("desk", False),
                                self.set_desk, tooltip="Karte mit den nächsten Terminen dauerhaft auf dem Desktop, unter "
                                                       "allen Fenstern. Braucht Wayland mit layer-shell (Hyprland, Sway …).")
        self.v_desk_pos = tui.Select(self.set_desk_pos, tooltip="Wo auf dem Bildschirm")
        self.v_desk_pos.set_options(deskcard.POSITIONS, self.store.settings.get("desk_pos", "top-left"))
        self.d_panel.body.append(wrapbox(self.v_desk, self.v_desk_pos))
        if not deskcard.supported():
            self.v_desk.set_sensitive(False)
            self.v_desk_pos.set_sensitive(False)
            self.d_panel.body.append(label("hier nicht verfügbar: braucht gtk4-layer-shell und einen Wayland-Compositor "
                                           "mit layer-shell.", "dim", wrap=True))
        self.d_panel.body.append(label("Ein-/Ausschalten per Tastenkürzel: Super+Shift+K, in datist die Taste b oder im Terminal "
                                       "„datist --desk“.", "dim", wrap=True))
        pages["leiste"].append(self.d_panel)
        self.r_panel = tui.Panel("erinnerungen")
        self.r_on = tui.Check("desktop-meldung vor Terminen", self.store.settings.get("remind_on", True),
                              lambda on: (self.store.settings.__setitem__("remind_on", on), self.store.save_settings()),
                              tooltip="Läuft, solange datist im Hintergrund ist (startet beim Login).")
        self.r_def = tui.Entry("", width=10, text=reminders.fmt_lead(self.reminders.default_lead()),
                               activate=lambda: self.set_remind_default())
        self.r_def.connect("changed", lambda *_: self.r_msg.set_label(""))
        self.r_msg = label("", "warn")
        self.r_panel.body.append(wrapbox(self.r_on, label("standard-vorlauf", "dim"), self.r_def,
                                         tui.Button("übernehmen", self.set_remind_default),
                                         tui.Button("test-meldung", lambda: reminders.send(
                                             self, "in 10 min: Testtermin", "so sieht eine Erinnerung aus", "test"))))
        self.r_panel.body.append(label("im Termin lässt sich der Vorlauf einzeln ändern (z. B. 30 min, 2 h, 1 tag, keine). "
                                       "ganztägige Termine melden nur, wenn dort ein Vorlauf steht.", "dim", wrap=True))
        self.r_panel.body.append(self.r_msg)
        pages["erinnerungen"].append(self.r_panel)
        self.s_panel = tui.Panel("semester · vorlesungszeit")
        self.s_state = tui.Select(self.set_holiday_state, max_chars=26, tooltip="Gesetzliche Feiertage dieses Landes")
        self.s_state.set_options(holidays.STATES, self.store.settings.get("holiday_state", ""))
        self.s_panel.body.append(wrapbox(label("feiertage für", "dim"), self.s_state,
                                         label("(Kalender „Feiertage & Semester“ oben ein-/ausblendbar)", "dim")))
        self.s_list = vbox(spacing=2)
        self.s_panel.body.append(self.s_list)
        self.s_panel.body.append(label(
            "für „ganzes semester“ im termin – A = 1. woche (ungerade KW), B = 2. woche (gerade KW). Aus diesen Zeiten "
            "kommen Vorlesungsbeginn/-ende, freie Tage und „vorlesungsfrei“ in der Wochenansicht; optional je Semester "
            "\"exams\": [[\"2027-02-08\", \"2027-03-12\"]] für die Prüfungsphase.", "dim", wrap=True, xalign=0))
        self.s_panel.body.append(wrapbox(
            tui.Button("zeiten bearbeiten", self.edit_semesters,
                       tooltip=f"öffnet {raster.SEMESTER_FILE.replace(os.path.expanduser('~'), '~')}")))
        pages["kalender"].append(self.s_panel)
        self.refresh_account()
        return self.acct

    def set_desk(self, on):
        self.store.settings["desk"] = bool(on)
        self.store.save_settings()
        self.deskcard.apply()
        chk = getattr(self, "v_desk", None)
        if chk is not None and chk.active != bool(on):
            chk.set_active(bool(on))

    def toggle_desk(self):
        self.set_desk(not self.store.settings.get("desk", False))
        if self.win:
            self.win.say("termine auf dem hintergrundbild: " + ("an" if self.store.settings["desk"] else "aus"))

    def set_desk_pos(self, v):
        self.store.settings["desk_pos"] = v
        self.store.save_settings()
        self.deskcard.apply()

    def set_holiday_state(self, v):
        self.store.settings["holiday_state"] = v
        self.store.save_settings()
        self.redraw()

    def set_remind_default(self):
        try:
            v = reminders.parse_lead(self.r_def.get_text())
        except ValueError as e:
            self.r_msg.set_label(f"✗ {e}")
            return
        v = reminders.DEFAULT_LEAD if v is None else max(0, v)
        self.store.settings["remind_default"] = v
        self.store.save_settings()
        self.r_def.set_text(reminders.fmt_lead(v))
        self.r_msg.set_label(f"✓ standard: {reminders.fmt_lead(v)}")

    def draw_legend(self, area, cr, w, h):
        p = Palette()
        lay = area.create_pango_layout("")
        lay.set_font_description(Pango.FontDescription.from_string(f"{tui.FONT} Bold 10"))
        x, y = 0, 4
        for k, name, short, _ in CATS:
            col = p.cat(k)
            text = f"▌{short} {name}"
            lay.set_text(text, -1)
            tw, th = lay.get_pixel_size()
            if x + tw > w:
                x, y = 0, y + th + 6
            cr.set_source_rgba(*col, 0.2)
            cr.rectangle(x, y - 1, tw + 8, th + 2)
            cr.fill()
            cr.set_source_rgba(*col, 1)
            cr.move_to(x + 2, y)
            PangoCairo.show_layout(cr, lay)
            x += tw + 22
        area.set_content_height(y + 30)

    def refresh_account(self):
        self.refresh_ics_panel()
        self.refresh_accounts_panel()
        self.refresh_tasks_panel()
        self.refresh_bar_panel()
        tui.clear(self.g_steps)
        tui.clear(self.g_btns)
        has_client = bool(gcal.client())
        logged = gcal.logged_in(gcal.MAIN)
        if logged and gcal.expired(gcal.MAIN):
            n = len(self.store.pending)
            self.g_status.set_markup(
                f"<span foreground='{self.hex('tertiary')}'>⚠ Anmeldung abgelaufen</span> – im Testmodus lässt Google "
                f"sie nach 7 Tagen verfallen. Deine Termine bleiben im Cache"
                + (f", {n} Änderung{'en' if n != 1 else ''} warten auf den Abgleich." if n else "."))
            self.g_btns.set_layout_manager(WrapLayout(spacing=8))
            self.g_btns.append(tui.Button("abbrechen" if self.login else "neu anmelden",
                                          self.cancel_login if self.login else self.start_login))
            self.g_btns.append(tui.Button("abmelden", self.logout, danger=True))
        elif logged:
            n = len(self.store.pending)
            when = dt.datetime.fromisoformat(self.store.synced).strftime("%d.%m. %H:%M") if self.store.synced else "–"
            since = gcal.signed_in_at()
            valid = ""
            if since:
                a = dt.datetime.fromtimestamp(since)
                left = gcal.seconds_left() or 0
                rest = f"noch {left / 86400:.1f} Tage" if left >= 86400 else f"noch {max(0, int(left // 3600))} Std."
                valid = f" · angemeldet am {a:%d.%m.} (Testmodus: gültig bis {a + dt.timedelta(days=7):%d.%m. %H:%M}, {rest})"
            self.g_status.set_markup(f"<span foreground='{self.hex('primary')}'>●</span> angemeldet · zuletzt "
                                     f"abgeglichen {when} · {n} änderung{'en' if n != 1 else ''} offen{valid}")
            for e in self.last_errors[:3]:
                self.g_steps.append(label("✗ " + e, "warn", wrap=True))
            self.g_btns.set_layout_manager(WrapLayout(spacing=8))
            self.g_btns.append(tui.Button("jetzt abgleichen", lambda: self.sync(force=True)))
            self.g_btns.append(tui.Button("anmeldung erneuern", self.start_login,
                                          tooltip="Fängt die 7 Tage neu an – am besten kurz vor dem Ablauf, dann bricht "
                                                  "der Abgleich nie ab"))
            self.g_btns.append(tui.Button("farben an google übertragen", self.push_colors,
                                          tooltip="alle in datist angelegten Termine bekommen in Google die "
                                                  "passende Farbe (nächste der 11 Google-Farben)"))
            self.g_btns.append(tui.Button("abmelden", self.logout, danger=True))
        else:
            self.g_status.set_markup("○ nicht angemeldet – alles läuft lokal (Kalender „Lokal“), "
                                     "Google kommt dazu, sobald du angemeldet bist")
            steps = [
                ("1", "Google-Cloud-Projekt anlegen und „Google Calendar API“ aktivieren",
                 "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com"),
                ("2", "Google Auth Platform einrichten: Zielgruppe „Extern“, App-Name z. B. datist, unter "
                      "„Zielgruppe → Testnutzer“ dein Google-Konto eintragen. Nicht veröffentlichen (geht nur mit "
                      "eigener Domain) – im Testmodus läuft die Anmeldung alle 7 Tage ab, der Kalender zeigt dann "
                      "„⚠ neu anmelden“.",
                 "https://console.cloud.google.com/auth/overview"),
                ("3", "Clients → „+ Client erstellen“ → Anwendungstyp „Desktop-App“ → Erstellen. Im Fenster danach "
                      "„JSON herunterladen“ – oder Client-ID und Clientschlüssel kopieren (Schritt 4b)",
                 "https://console.cloud.google.com/auth/clients"),
            ]
            for n, text, url in steps:
                self.g_steps.append(hbox(label(n, "accent"), label(text, wrap=True, hexpand=True),
                                         tui.Button("öffnen", lambda u=url: Gio.AppInfo.launch_default_for_uri(u, None)),
                                         spacing=10))
            ok = "✓ geladen" if has_client else ""
            self.g_steps.append(hbox(label("4", "accent"), label("heruntergeladene client_secret_….json laden",
                                                                hexpand=True, wrap=True),
                                     label(ok, "accent"), tui.Button("json laden", self.pick_client), spacing=10))
            # ohne JSON: Client-ID und Schlüssel von Hand
            self.cid_entry = tui.Entry("Client-ID (…apps.googleusercontent.com)")
            self.csec_entry = tui.Entry("Clientschlüssel (GOCSPX-…)", password=True)
            self.g_steps.append(hbox(label("4b", "accent"), wrapbox(label("oder von hand:", "dim"), self.cid_entry,
                                                                    self.csec_entry,
                                                                    tui.Button("übernehmen", self.manual_client)),
                                     spacing=10))
            self.cid_entry.set_width_chars(34)
            self.csec_entry.set_width_chars(24)
            self.g_steps.append(hbox(label("5", "accent"), label("im Browser (Zen) anmelden und Zugriff erlauben",
                                                                hexpand=True, wrap=True),
                                     tui.Button("abbrechen" if self.login else "mit google anmelden",
                                                self.cancel_login if self.login else self.start_login), spacing=10))
            if not has_client:
                self.g_steps.get_last_child().set_sensitive(False)
        # Kalenderliste
        tui.clear(self.c_list)
        default = self.store.default_cal()
        for c in self.store.all_calendars():
            vis = self.store.visible(c["id"])
            chk = tui.Check(c["name"], vis, lambda on, cid=c["id"]: self.set_visible(cid, on))
            writable = c.get("role") in ("owner", "writer")
            std = tui.Button("● standard" if c["id"] == default else "standard für neue",
                             lambda cid=c["id"]: self.set_default(cid))
            std.set_sensitive(writable and c["id"] != default)
            role = {"owner": "eigener", "writer": "schreiben", "reader": "nur lesen",
                    "freeBusyReader": "nur frei/belegt"}.get(c.get("role"), "")
            self.c_list.append(wrapbox(chk, label(role, "dim"), std, spacing=10))
        self.f_area.queue_draw()
        tui.clear(self.s_list)
        today = dt.date.today()
        for sem in raster.semesters():
            if sem["end"] < today - dt.timedelta(days=60) or sem["start"] > today + dt.timedelta(days=420):
                continue
            now = sem["start"] <= today <= sem["end"]
            txt = (f"{sem['name']:<11} {raster.fmt_date(sem['start'])} – {raster.fmt_date(sem['end'])}"
                   + (f" · {len(sem['free'])} pause{'n' if len(sem['free']) != 1 else ''}" if sem["free"] else ""))
            self.s_list.append(hbox(label("●" if now else "○", "accent" if now else "dim"), label(txt),
                                    label("geschätzt" if sem.get("guess") else "", "dim"), spacing=8))

    def edit_semesters(self):
        path = raster.SEMESTER_FILE
        if not os.path.exists(path):          # Vorlage aus den (geschätzten) Zeiten anlegen
            import json
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump([{"name": s["name"], "start": s["start"].isoformat(), "end": s["end"].isoformat(),
                            "free": [[a.isoformat(), b.isoformat()] for a, b in s["free"]], "exams": []}
                           for s in raster.semesters()], f, ensure_ascii=False, indent=1)
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)

    def hex(self, name):
        c = tui.colors().get(name)
        return "#%02x%02x%02x" % (int(c.red * 255), int(c.green * 255), int(c.blue * 255)) if c else "#ffffff"

    def set_visible(self, cid, on):
        self.store.settings.setdefault("visible", {})[cid] = on
        self.store.save_settings()
        self.redraw()

    def set_default(self, cid):
        self.store.settings["default_cal"] = cid
        self.store.save_settings()
        self.refresh_account()

    def manual_client(self):
        try:
            gcal.install_client_manual(self.cid_entry.get_text(), self.csec_entry.get_text())
        except ValueError as e:
            self.win.say(str(e), error=True)
            return
        self.win.say("OAuth-Client übernommen – jetzt anmelden (Schritt 5)")
        self.refresh_account()

    def pick_client(self):
        dlg = Gtk.FileDialog(title="client_secret.json wählen")
        f = Gtk.FileFilter()
        f.set_name("JSON")
        f.add_pattern("*.json")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)
        dl = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if dl:
            dlg.set_initial_folder(Gio.File.new_for_path(dl))

        def done(d, res):
            try:
                path = d.open_finish(res).get_path()
                gcal.install_client(path)
                self.win.say("OAuth-Client geladen – jetzt anmelden (Schritt 5)")
            except GLib.Error:
                return
            except (ValueError, OSError) as e:
                self.win.say(str(e), error=True)
            self.refresh_account()
        dlg.open(self.win, None, done)

    def acct_name(self, acct):
        """Anzeigename eines Kontos (nie die E-Mail): vom Nutzer vergeben, das Hauptkonto heißt „Google“."""
        return self.store.settings.get("accounts", {}).get(acct) or ("Google" if acct == gcal.MAIN else acct)

    def start_login(self, acct=None, tasks=False):
        if acct is None or not isinstance(acct, str):          # Klick im Kopf: das erste abgelaufene Konto
            exp = gcal.expired_accounts()
            acct = exp[0] if exp else (getattr(self, "_expiry_acct", None) or gcal.MAIN)
        self.login = gcal.Login(lambda url: GLib.idle_add(
            lambda: Gio.AppInfo.launch_default_for_uri(url, None) and False), acct, tasks)
        self.login_acct = acct
        self.win.say("Browser geöffnet – bei Google anmelden und Zugriff erlauben")
        self.refresh_account()
        self.update_header()

        def done(res):
            self.login = None
            if isinstance(res, Exception):
                self.win.say(f"Anmeldung: {res}", error=True)
            else:
                self.win.say("angemeldet ✓ – gleiche ab …")
                if tasks:
                    self.store.settings["tasks_on"] = True
                    self.store.save_settings()
                self.store.window = None
                self.sync(force=True)
            self.refresh_account()
            self.update_header()
        tui.background(self.login.run, done=done)

    def cancel_login(self):
        if self.login:
            self.login.cancelled = True

    def logout(self, acct=None):
        acct = acct or gcal.MAIN
        gcal.logout(acct)
        self.store.drop_account(acct)
        self.win.say("abgemeldet – Google-Termine dieses Kontos aus dem Cache entfernt, lokale bleiben")
        self.refresh_account()
        self.redraw()


if __name__ == "__main__":
    if "--desk" in sys.argv:                 # datist --desk: läuft nichts, Karte umschalten und im Hintergrund starten
        sys.argv.remove("--desk")
        app = Kalender()
        app.register(None)
        if app.get_is_remote():
            app.activate_action("toggle-desk", None)
            sys.exit(0)
        app.daemon = True
        app.connect("startup", lambda a: GLib.idle_add(lambda: (a.toggle_desk(), False)[1]))
        sys.exit(app.run([sys.argv[0]]))
    if "--tab" in sys.argv:                  # datist --tab acct: direkt einen Tab zeigen (z. B. aus scourge)
        tab = sys.argv[sys.argv.index("--tab") + 1]
        app = Kalender()
        app.register(None)
        if app.get_is_remote():
            app.activate_action("show-tab", GLib.Variant("s", tab))
            sys.exit(0)
        app.connect("activate", lambda a: GLib.idle_add(lambda: (a.show_tab_now(tab), False)[1]))
        sys.exit(app.run([sys.argv[0]]))
    app = Kalender()
    if "--daemon" in sys.argv:               # datist --daemon: beim Login vorladen, Super+K zeigt dann sofort
        sys.argv.remove("--daemon")
        app.daemon = True
        app.register(None)
        if app.get_is_remote():              # läuft schon → nichts tun (sonst würde es das Fenster umschalten)
            sys.exit(0)
    sys.exit(app.run(sys.argv))
