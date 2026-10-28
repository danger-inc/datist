# datist – Desktop-Karte: die nächsten Termine (und Aufgaben) dauerhaft auf dem Hintergrundbild, unter allen Fenstern.
# Wie bei musicalist: Layer-Shell (Ebene BOTTOM), Namespace "datist-desk" (Hyprland kann dafür Weichzeichnen einstellen).
# Braucht gtk4-layer-shell; fehlt es (oder läuft es nicht unter Wayland), bleibt die Karte aus.
import datetime as dt

import gi
from gi.repository import GLib, Gtk
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as Layer
except (ImportError, ValueError):
    Layer = None

import tui
from tui import label, hbox, vbox

import agendaview
from raster import WEEKDAYS

POSITIONS = [("top-left", "oben links"), ("top-right", "oben rechts"), ("bottom-left", "unten links"),
             ("bottom-right", "unten rechts")]
WIDTH = 380
CSS = """
window.desk-win.tui:not(.glass), window.desk-win { background-color: rgba(0, 0, 0, 0.01); }
.desk-card .panel { background-color: alpha(@background, 0.80); border-radius: 6px; }
.desk-card .pbody { padding: 6px 14px 10px 14px; border-color: alpha(@primary, 0.7); }

.desk-card .desk-now { color: @primary; }
.desk-card .desk-soon { color: @tertiary; }
"""


def supported():
    try:
        return Layer is not None and Layer.is_supported()
    except Exception:  # noqa: BLE001
        return False


class DeskContent(Gtk.Box):
    """Inhalt der Karte (ohne Fenster-/Layer-Teil, deshalb auch ohne Wayland testbar)."""

    def __init__(self, app, limit=7):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.app, self.limit = app, limit
        self.add_css_class("desk-card")
        self.set_size_request(WIDTH, -1)
        self.panel = tui.Panel("datist")
        self.append(self.panel)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.app.show_tab_now("agenda"))
        self.add_controller(click)

    def refresh(self, now=None):
        st = self.app.store
        now = now or dt.datetime.now()
        today = now.date()
        tui.clear(self.panel.body)
        self.panel.set_title(f"datist · {WEEKDAYS[today.weekday()]} {today.day}.{today.month}. · KW {today.isocalendar()[1]}")
        t0 = dt.datetime.combine(today, dt.time())
        occ = st.mark_conflicts(st.occurrences(t0, t0 + dt.timedelta(days=4)))
        occ = [o for o in occ if o["e"] > now and o.get("cal") != "tasks"]
        shown, cur = 0, None
        for o in occ:
            if shown >= self.limit:
                break
            d = max(o["s"].date(), today)
            if d != cur:
                cur = d
                if d != today:
                    tag = "morgen" if d == today + dt.timedelta(days=1) else f"{WEEKDAYS[d.weekday()]} {d.day}.{d.month}."
                    h = label(tag, "dim", xalign=0)
                    h.set_margin_top(6)
                    self.panel.body.append(h)
            self.panel.body.append(self.row(o, now))
            shown += 1
        if not shown:
            self.panel.body.append(label("keine Termine in den nächsten Tagen", "dim", xalign=0))
        exams = st.upcoming("pruefung", 21, now=now)
        if exams:
            x = exams[0]
            n = (x["s"].date() - today).days
            e = label(f"! {x['title']} · " + ("heute" if n <= 0 else "morgen" if n == 1 else f"{n} d"), "warn", xalign=0,
                      ellipsize=True)
            e.set_margin_top(6)
            self.panel.body.append(e)
        if st.tasks_on():
            tasks = st.open_tasks(3)
            for i, t in enumerate(tasks):
                due = f" · {agendaview.rel_days(dt.date.fromisoformat(t['due']), today)}" if t.get("due") else ""
                lab = label(f"☐ {t.get('title')}{due}", "dim", xalign=0, ellipsize=True)
                if i == 0:
                    lab.set_margin_top(6)
                self.panel.body.append(lab)

    def row(self, o, now):
        allday = o.get("allday") or (o["e"] - o["s"]) >= dt.timedelta(hours=20)
        running = o["s"] <= now < o["e"] and not allday
        if allday:
            when = "ganztägig"
        elif running:
            when = "läuft"
        else:
            mins = int((o["s"] - now).total_seconds() // 60)
            when = f"{o['s']:%H:%M}" + (f" · {mins} min" if 0 <= mins <= 90 and o["s"].date() == now.date() else "")
        cls = "desk-now" if running else "desk-soon" if (not allday and 0 <= (o["s"] - now).total_seconds() <= 900) else "dim"
        title = ("⚡ " if o.get("conflict") else "") + (o.get("title") or "Termin") + \
            (f" · {o['location']}" if o.get("location") else "")
        r = hbox(label(when, cls, xalign=0), label(title, hexpand=True, ellipsize=True, xalign=0), spacing=10)
        r.get_first_child().set_width_chars(11)
        return r


class DeskCard:
    """Die Karte als Layer-Shell-Fenster auf dem Hintergrund. apply() liest die Einstellungen (desk, desk_pos)."""

    def __init__(self, app):
        self.app = app
        self.win = None
        self.content = None
        self._tick = None

    def enabled(self):
        return bool(self.app.store.settings.get("desk", False)) and supported()

    def _build(self):
        self.win = Gtk.Window(application=self.app)
        self.win.add_css_class("desk-win")
        self.win.add_css_class("tui")
        Layer.init_for_window(self.win)
        Layer.set_namespace(self.win, "datist-desk")
        Layer.set_layer(self.win, Layer.Layer.BOTTOM)
        Layer.set_exclusive_zone(self.win, 0)
        Layer.set_keyboard_mode(self.win, Layer.KeyboardMode.NONE)
        self.win.set_default_size(WIDTH, 1)
        self.win.set_resizable(False)
        self.content = DeskContent(self.app)
        self.win.set_child(self.content)

    def place(self):
        pos = self.app.store.settings.get("desk_pos", "top-left")
        edges = {"top-left": ("TOP", "LEFT"), "top-right": ("TOP", "RIGHT"), "bottom-left": ("BOTTOM", "LEFT"),
                 "bottom-right": ("BOTTOM", "RIGHT")}.get(pos, ("TOP", "LEFT"))
        for e in ("TOP", "BOTTOM", "LEFT", "RIGHT"):
            Layer.set_anchor(self.win, getattr(Layer.Edge, e), e in edges)
            Layer.set_margin(self.win, getattr(Layer.Edge, e), 24 if e in edges else 0)

    def apply(self):
        if not self.enabled():
            if self.win is not None:
                self.win.set_visible(False)
            self._stop()
            return
        if self.win is None:
            self._build()
        self.place()
        self.refresh()
        self.win.set_visible(True)
        if self._tick is None:
            self._tick = GLib.timeout_add_seconds(30, lambda: (self.refresh(), True)[1])

    def _stop(self):
        if self._tick is not None:
            GLib.source_remove(self._tick)
            self._tick = None

    def refresh(self):
        if self.content is not None:
            self.content.refresh()
