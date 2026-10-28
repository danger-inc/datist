# datist – Agenda: Liste der nächsten Tage (7 / 14 / 30), gruppiert nach Tag, mit Prüfungs-Countdown oben.
import datetime as dt

import gi
from gi.repository import GLib, Gtk

import tui
from tui import label, hbox, vbox

import quickparse
import gcal
import raster
from raster import WEEKDAYS_LONG, CAT_SHORT

DAYS = [("7", "7 tage"), ("14", "14 tage"), ("30", "30 tage")]


def rel_days(d, today):
    n = (d - today).days
    return "heute" if n == 0 else "morgen" if n == 1 else "übermorgen" if n == 2 else f"in {n} Tagen" if n > 0 else \
        f"vor {-n} Tagen"


class AgendaView(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(6)
        self.sel = tui.Select(self.on_days, tooltip="So viele Tage voraus")
        self.sel.set_options(DAYS, str(self.days()))
        self.head = hbox(label("agenda", "accent"), label("", hexpand=True), label("zeitraum", "dim"), self.sel,
                         spacing=10)
        self.append(self.head)
        self.body = vbox(spacing=0)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.body)
        self.append(self.scroll)
        self.rows = []
        self.task_entry = tui.Entry("neue Aufgabe …  z. B. Blatt 4 abgeben bis freitag", activate=self.add_task)
        self.connect("map", lambda *_: self.refresh())

    def days(self):
        v = self.app.store.settings.get("agenda_days", 14)
        return v if v in (7, 14, 30) else 14

    def on_days(self, v):
        self.app.store.settings["agenda_days"] = int(v)
        self.app.store.save_settings()
        self.refresh()

    # ----- Aufbau -----
    def refresh(self):
        if not self.get_mapped():
            return
        app, st = self.app, self.app.store
        today = dt.date.today()
        n = self.days()
        now = dt.datetime.now()
        t0 = dt.datetime.combine(today, dt.time())
        occ = st.mark_conflicts(st.occurrences(t0, t0 + dt.timedelta(days=n)))
        occ = [o for o in occ if o["e"] > now or o.get("allday") and o["s"].date() >= today]
        by_day = {}
        for o in occ:
            by_day.setdefault(max(o["s"].date(), today), []).append(o)
        had_focus = self.task_entry.has_focus() or self.task_entry.get_focus_child() is not None
        tui.clear(self.body)
        self.rows = []
        exams = st.upcoming("pruefung", 180)
        if exams:
            self.section("prüfungen", "tertiary")
            for o in exams[:6]:
                self.add_row(o, today, exam=True)
        if st.tasks_on():
            self.add_tasks_section(today)
        shown = False
        for d in sorted(by_day):
            shown = True
            hol = st.day_state(d)
            title = f"{WEEKDAYS_LONG[d.weekday()]} {d.day}.{d.month}."
            self.section(title, None, right=rel_days(d, today) + (f" · {hol}" if hol else ""), today=(d == today))
            for o in by_day[d]:
                self.add_row(o, today)
        if not shown:
            self.body.append(label(f"keine Termine in den nächsten {n} Tagen", "empty", xalign=0.5))
        if had_focus and st.tasks_on():
            GLib.idle_add(lambda: self.task_entry.grab_focus() and False)
        return False

    # ----- Aufgaben (Google Tasks) -----
    def add_tasks_section(self, today):
        st = self.app.store
        horizon = today + dt.timedelta(days=self.days())
        tasks = [t for t in st.open_tasks(10 ** 6) if t.get("due") and dt.date.fromisoformat(t["due"]) <= horizon]
        if not tasks:
            return
        self.section("aufgaben", "accent", right=f"{len(tasks)} fällig · alle im Reiter ⁵")
        for t in tasks[:25]:
            self.add_task_row(t, today)
        if len(tasks) > 25:
            self.body.append(label(f"… {len(tasks) - 25} weitere", "dim", xalign=0))

    def add_task_row(self, t, today):
        due = dt.date.fromisoformat(t["due"]) if t.get("due") else None
        over = due is not None and due < today
        chk = Gtk.Button(label="☐", tooltip_text="abhaken")
        chk.add_css_class("mini")
        chk.connect("clicked", lambda *_b, tid=t["id"]: self.task_done(tid))
        title = label(("⟳ " if t.get("pending") else "") + (t.get("title") or "Aufgabe"), hexpand=True, ellipsize=True,
                      xalign=0)
        when = label(("" if due is None else f"{due.day}.{due.month}. · {rel_days(due, today)}"), "warn" if over else "dim")
        rm = Gtk.Button(label="✕", tooltip_text="löschen")
        rm.add_css_class("mini")
        rm.connect("clicked", lambda *_b, tid=t["id"]: self.task_delete(tid))
        row = hbox(chk, title, when, rm, spacing=10)
        self.body.append(row)

    def add_task(self):
        text = self.task_entry.get_text().strip()
        if not text:
            return
        title, due = quickparse.parse_task(text)
        try:
            self.app.store.add_task(title, due)
        except ValueError as e:
            self.app.win.say(str(e), error=True)
            return
        self.app.win.say(f"Aufgabe: {title}" + (f" (bis {due})" if due else ""))
        self.changed(refocus=True)

    def task_done(self, tid):
        self.app.store.set_task_done(tid, True)
        self.app.win.say("☑ erledigt")
        self.changed()

    def task_delete(self, tid):
        self.app.store.delete_task(tid)
        self.app.win.say("Aufgabe gelöscht")
        self.changed()

    def changed(self, refocus=False):
        self.app.redraw()
        if gcal.logged_in():
            GLib.timeout_add(800, lambda: self.app.sync() and False)
        if refocus and getattr(self, "task_entry", None) is not None:
            GLib.idle_add(lambda: self.task_entry.grab_focus() and False)

    def section(self, text, cls, right="", today=False):
        row = hbox(label(text, "accent" if cls is None else cls, xalign=0, hexpand=True),
                   label(right, "dim" if not today else "accent"), spacing=10)
        row.set_margin_top(10)
        row.set_margin_bottom(2)
        self.body.append(row)

    def add_row(self, o, today, exam=False):
        d = o["s"].date()
        if exam:
            when = f"{d.day}.{d.month}. " + ("ganztägig" if o.get("allday") else f"{o['s']:%H:%M}")
            lead = rel_days(d, today)
        elif o.get("allday") or (o["e"] - o["s"]) >= dt.timedelta(hours=20):
            when, lead = ("ganztägig" if (o["e"].date() - o["s"].date()).days <= 1 else
                          f"bis {WEEKDAYS_LONG[(o['e'] - dt.timedelta(seconds=1)).weekday()][:2]} "
                          f"{(o['e'] - dt.timedelta(seconds=1)).day}.{(o['e'] - dt.timedelta(seconds=1)).month}."), ""
        else:
            when, lead = f"{o['s']:%H:%M}–{o['e']:%H:%M}", ""
        icons = ("⚡ " if o.get("conflict") else "") + ("↻ " if o.get("series") or o.get("rrule") else "") + \
                ("⟳ " if o.get("pending") else "") + ("󰍬 " if o.get("meet") else "")
        btn = Gtk.Button(hexpand=True)
        btn.add_css_class("rowhead")
        cells = [label(when, "dim", xalign=0), label(CAT_SHORT.get(o.get("cat"), "○"), "accent")]
        if exam:
            cells.append(label(lead, "warn", xalign=0))
        cells.append(label(icons + (o.get("title") or "?"), hexpand=True, ellipsize=True, xalign=0))
        if o.get("location"):
            cells.append(label("⌂ " + o["location"], "dim", ellipsize=True))
        if o.get("conflict"):
            cells.append(label("mit " + ", ".join(dict.fromkeys(o["conflict"])), "warn", ellipsize=True))
        box = hbox(*cells, spacing=10)
        box.get_first_child().set_width_chars(12 if not exam else 14)
        btn.set_child(box)
        btn.connect("clicked", lambda *_b, o=o: self.app.edit(o))
        self.body.append(btn)
        self.rows.append(btn)

    # ----- Tasten -----
    def focus_first(self):
        if self.rows:
            self.rows[0].grab_focus()

    def move(self, step):
        if not self.rows:
            return
        cur = self.app.win.get_focus()
        i = self.rows.index(cur) if cur in self.rows else (-1 if step > 0 else len(self.rows))
        self.rows[max(0, min(len(self.rows) - 1, i + step))].grab_focus()


class TasksView(AgendaView):
    """Eigener Reiter „aufgaben“: alle offenen Google-Aufgaben (anlegen, abhaken, löschen). Ist Google Tasks noch nicht
    aktiviert, steht hier stattdessen die Erklärung samt Knopf."""

    def __init__(self, app):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(6)
        self.head = hbox(label("aufgaben", "accent"), label("", hexpand=True), spacing=10)
        self.append(self.head)
        self.body = vbox(spacing=0)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.body)
        self.append(self.scroll)
        self.rows = []
        self.task_entry = tui.Entry("neue Aufgabe …  z. B. Blatt 4 abgeben bis freitag", activate=self.add_task)
        self.connect("map", lambda *_: self.refresh())

    def focus_first(self):
        if self.app.store.tasks_on():
            self.task_entry.grab_focus()

    def refresh(self):
        if not self.get_mapped():
            return
        st = self.app.store
        today = dt.date.today()
        had_focus = self.task_entry.has_focus() or self.task_entry.get_focus_child() is not None
        tui.clear(self.body)
        if not st.tasks_on():
            self.section("google aufgaben sind aus", "accent")
            for text in ("Hier erscheinen deine Aufgaben aus Google Kalender / Google Tasks – anlegen, abhaken, löschen.",
                         "Einmalig nötig: „aktivieren“ meldet dich neu an (zusätzliche Berechtigung für Aufgaben), und im "
                         "Google-Cloud-Projekt muss die „Tasks API“ eingeschaltet sein. Nur für das Hauptkonto."):
                t = label(text, "dim", wrap=True, xalign=0)
                t.set_margin_top(6)
                self.body.append(t)
            btns = hbox(tui.Button("aufgaben aktivieren", lambda: self.app.start_login(gcal.MAIN, True)),
                        tui.Button("einstellungen", lambda: self.app.show_tab_now("acct:google")), spacing=8)
            btns.set_margin_top(10)
            self.body.append(btns)
            return False
        tasks = st.open_tasks(10 ** 6)
        self.section("offen", "accent", right=f"{len(tasks)} Aufgaben")
        self.body.append(self.task_entry)
        if not tasks:
            self.body.append(label("alles erledigt", "empty", xalign=0.5))
        for t in tasks:
            self.add_task_row(t, today)
        if had_focus:
            GLib.idle_add(lambda: self.task_entry.grab_focus() and False)
        return False
