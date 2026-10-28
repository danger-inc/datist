# Lokaler Speicher des Kalenders: Offline-Cache der Google-Termine, lokaler Kalender, Warteschlange
# für Änderungen, die noch zu Google müssen. Alles als JSON in ~/.local/share/kalender/data/ (nicht im rice-Backup,
# sonst würden beim Zurückspielen alte Änderungen erneut zu Google geschickt).
#
# Termin (dict):
#   uid      eindeutiger Schlüssel (Google-ID, "local-…" oder "pending-…")
#   cal      Kalender-ID ("local" oder Google-Kalender)
#   gid      Google-ID (None bei lokalen/noch nicht hochgeladenen Terminen)
#   series   Google-ID der Serie, wenn das eine einzelne Wiederholung ist
#   title, location, link, notes, cat, tone
#   allday   True: start/end sind Daten "YYYY-MM-DD" (Ende exklusiv), sonst ISO-Zeit mit Zeitzone
#   rrule    Wiederholungsregel (nur bei Serien, die hier selbst ausgerollt werden), exdates [ISO]
#   pending  True: lokale Änderung, noch nicht bei Google
import copy, datetime as dt, json, os, uuid

import holidays as hol
import rrule
from raster import TZ, guess_cat

DATA = os.path.expanduser("~/.local/share/kalender/data")   # bewusst nicht in rice-apps (Backup)
NOTIST_FILE = "notist.json"      # von notist geschrieben (Erinnerungen), hier nur gelesen
NOTIST_LINK = "notist:"
NOTIST_MINUTES = 15
LOCAL_CAL = {"id": "local", "name": "Lokal (nur dieser Rechner)", "color": None, "role": "owner"}


def _load(name, default):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, name)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # private Daten (Termine, Abo-Adressen)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def parse_when(s, allday):
    if allday:
        return dt.datetime.combine(dt.date.fromisoformat(s[:10]), dt.time())
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ).replace(tzinfo=None)      # intern: naive Ortszeit


def iso(d, allday=False):
    if allday:
        return (d.date() if isinstance(d, dt.datetime) else d).isoformat()
    return d.replace(tzinfo=TZ).isoformat(timespec="seconds") if d.tzinfo is None else d.isoformat()


class Store:
    def __init__(self):
        cache = _load("cache.json", {})
        self.calendars = cache.get("calendars", [])
        self.google = cache.get("events", {})          # uid → Termin (Instanzen von Google)
        self.synced = cache.get("synced")
        self.window = cache.get("window")
        self.local = _load("local.json", {})            # uid → Termin (lokaler Kalender)
        self.tasks = _load("tasks.json", {"lists": [], "items": {}})        # Stand bei Google (Hauptkonto)
        self.ics = _load("ics.json", {})                # Abo-ID → {name, etag, events{uid: Termin}} (nur lesen)
        self.pending = _load("pending.json", [])        # [op]
        self.settings = _load("settings.json", {})
        self.listeners = []
        self.undo_stack = []        # [(Beschreibung, Funktion | None)] – nur in dieser Sitzung, neueste zuletzt
        self._rec = True            # False: Änderungen (z. B. durch notist/Rückgängig) nicht aufzeichnen
        self.color_for = None       # ev → Google-Farb-ID (setzt die Oberfläche, kennt die Palette)

    # ----- Speichern -----
    def save_cache(self):
        _save("cache.json", {"calendars": self.calendars, "events": self.google, "synced": self.synced,
                             "window": self.window})

    def save_local(self):
        _save("local.json", self.local)

    def save_pending(self):
        _save("pending.json", self.pending)

    def save_settings(self):
        _save("settings.json", self.settings)

    def changed(self):
        for fn in self.listeners:
            fn()

    # ----- Kalender -----
    # ----- Aufgaben (Google Tasks) -----
    TASKS_CAL = {"id": "tasks", "name": "Aufgaben", "color": None, "role": "reader", "selected": True}

    def tasks_on(self):
        return bool(self.settings.get("tasks_on"))

    def all_tasks(self):
        """Aufgaben = Stand bei Google + noch nicht hochgeladene Änderungen (angelegt / geändert / gelöscht)."""
        items = {k: dict(v) for k, v in self.tasks.get("items", {}).items()}
        for op in self.pending:
            kind = op["op"]
            if kind == "task_create":
                items[op["tid"]] = {"id": op["tid"], "list": op["list"], "title": op["task"].get("title"),
                                    "notes": op["task"].get("notes", ""), "due": op["task"].get("due"),
                                    "done": bool(op["task"].get("done")), "pending": True}
            elif kind == "task_update" and op["tid"] in items:
                items[op["tid"]].update({k: v for k, v in op["task"].items()}, pending=True)
            elif kind == "task_delete":
                items.pop(op["tid"], None)
        return items

    def open_tasks(self, limit=30):
        """Offene Aufgaben: mit Datum zuerst (früheste zuerst), dann ohne Datum."""
        rows = [t for t in self.all_tasks().values() if not t.get("done")]
        rows.sort(key=lambda t: (t.get("due") is None, t.get("due") or "", (t.get("title") or "").lower()))
        return rows[:limit]

    def default_task_list(self):
        lists = self.tasks.get("lists") or []
        want = self.settings.get("task_list")
        return next((l["id"] for l in lists if l["id"] == want), lists[0]["id"] if lists else None)

    def add_task(self, title, due=None, notes=""):
        lid = self.default_task_list()
        if not lid:
            raise ValueError("Noch keine Aufgabenliste geladen – erst abgleichen")
        tid = "pending-task-" + uuid.uuid4().hex[:10]
        self.queue({"op": "task_create", "list": lid, "tid": tid, "acct": "main",
                    "task": {"title": title, "due": due, "notes": notes, "done": False}})
        self.changed()
        return tid

    def set_task_done(self, tid, done):
        t = self.all_tasks().get(tid)
        if not t:
            return
        for op in self.pending:                                  # noch nicht hochgeladen: im Auftrag ändern
            if op["op"] == "task_create" and op["tid"] == tid:
                op["task"]["done"] = bool(done)
                self.save_pending()
                self.changed()
                return
        self.queue({"op": "task_update", "list": t["list"], "tid": tid, "acct": "main", "task": {"done": bool(done)}})
        self.changed()

    def delete_task(self, tid):
        t = self.all_tasks().get(tid)
        if not t:
            return
        if any(op["op"] == "task_create" and op["tid"] == tid for op in self.pending):     # nie hochgeladen
            self.pending = [op for op in self.pending if op.get("tid") != tid]
            self.save_pending()
        else:
            self.queue({"op": "task_delete", "list": t["list"], "tid": tid, "acct": "main"})
        self.changed()

    def task_events(self, a, b):
        """Aufgaben mit Fälligkeitsdatum als ganztägige, nur lesbare Einträge in den Ansichten."""
        if not self.tasks_on() or not self.visible("tasks"):
            return []
        a_d = a.date() if isinstance(a, dt.datetime) else a
        b_d = b.date() if isinstance(b, dt.datetime) else b
        out = []
        for t in self.all_tasks().values():
            due = t.get("due")
            if not due:
                continue
            d = dt.date.fromisoformat(due)
            if not (a_d <= d < b_d):
                continue
            out.append({"uid": "task:" + t["id"], "ics_uid": None, "gid": None, "series": None, "cal": "tasks",
                        "task_id": t["id"], "done": bool(t.get("done")),
                        "title": ("☑ " if t.get("done") else "☐ ") + (t.get("title") or "Aufgabe"),
                        "start": due, "end": (d + dt.timedelta(days=1)).isoformat(), "allday": True, "location": "",
                        "link": "", "notes": t.get("notes") or "", "cat": "sonst", "tone": "", "rrule": None,
                        "exdates": [], "status": "confirmed"})
        return out

    # ----- ICS-Abos -----
    def subs(self):
        return self.settings.setdefault("ics_subs", [])

    def ics_calendars(self):
        return [{"id": "ics:" + s["id"], "name": s.get("name") or "Abo", "color": None, "role": "reader", "ics": True,
                 "selected": True} for s in self.subs()]

    def ics_events(self):
        return [ev for sub in self.ics.values() for ev in sub.get("events", {}).values()]

    def is_readonly(self, ev_or_cal):
        cal = ev_or_cal.get("cal") if isinstance(ev_or_cal, dict) else ev_or_cal
        if cal == "local":
            return False
        c = next((c for c in self.all_calendars() if c["id"] == cal), None)
        return bool(c and c.get("role") not in ("owner", "writer"))

    def add_sub(self, name, url):
        import subs as _subs
        url = _subs.normalize(url)
        if any(s["url"] == url for s in self.subs()):
            raise ValueError("dieses Abo gibt es schon")
        sub = {"id": uuid.uuid4().hex[:8], "name": (name or "").strip() or _subs.host_of(url), "url": url,
               "every": _subs.EVERY_MINUTES, "last": None, "error": None, "count": 0,
               "auto_name": not (name or "").strip()}
        self.subs().append(sub)
        self.save_settings()
        self.changed()
        return sub

    def remove_sub(self, sub_id):
        self.settings["ics_subs"] = [s for s in self.subs() if s["id"] != sub_id]
        self.ics.pop(sub_id, None)
        vis = self.settings.get("visible", {})
        vis.pop("ics:" + sub_id, None)
        self.save_settings()
        _save("ics.json", self.ics)
        self.changed()

    def sub_due(self, sub, now=None):
        if not sub.get("last"):
            return True
        now = now or dt.datetime.now(TZ).replace(tzinfo=None)
        try:
            last = dt.datetime.fromisoformat(sub["last"]).replace(tzinfo=None)
        except ValueError:
            return True
        # nach einem Fehler früher erneut versuchen (5 min), sonst im eingestellten Takt
        wait = 5 if sub.get("error") else max(5, int(sub.get("every") or 30))
        return now - last >= dt.timedelta(minutes=wait)

    def apply_ics(self, sub_id, res, error=None):
        """Ergebnis eines Abrufs übernehmen (res = subs.refresh(...) oder None bei Fehler)."""
        sub = next((s for s in self.subs() if s["id"] == sub_id), None)
        if sub is None:
            return
        sub["last"] = dt.datetime.now(TZ).replace(tzinfo=None).isoformat(timespec="seconds")
        sub["error"] = error
        if error is None and res is not None:
            entry = self.ics.setdefault(sub_id, {"events": {}})
            entry["etag"] = res.get("etag")
            if not res.get("unchanged"):
                entry["events"] = res["events"]
                if res.get("name") and sub.get("auto_name"):       # Name kam nicht vom Nutzer: den aus der Datei nehmen
                    sub["name"], sub["auto_name"] = res["name"], False
            sub["count"] = len(entry.get("events", {}))
            _save("ics.json", self.ics)
        self.save_settings()
        self.changed()

    # ----- Feiertage & Semester (berechnet, nur lesen) -----
    HOLIDAY_CAL = {"id": "holidays", "name": "Feiertage & Semester", "color": None, "role": "reader", "selected": True}

    def holiday_state(self):
        return self.settings.get("holiday_state", "")

    def holiday_events(self, a, b):
        if not self.visible("holidays"):
            return []
        import raster
        return hol.events(a.date() if isinstance(a, dt.datetime) else a, b.date() if isinstance(b, dt.datetime) else b,
                          self.holiday_state(), raster.semesters())

    def day_state(self, d):
        """Name des Feiertags an d oder None."""
        return hol.holiday_on(d, self.holiday_state()) if self.visible("holidays") else None

    def week_state(self, days):
        import raster
        return hol.span_state(days, raster.semesters()) if self.visible("holidays") else None

    def all_calendars(self):
        return [LOCAL_CAL] + self.calendars + self.ics_calendars() + [self.HOLIDAY_CAL] + \
            ([self.TASKS_CAL] if self.tasks_on() else [])

    def visible(self, cal):
        vis = self.settings.get("visible", {})
        if cal in vis:
            return vis[cal]
        if cal == "local" or cal.startswith("ics:") or cal in ("holidays", "tasks"):
            return True
        c = next((c for c in self.calendars if c["id"] == cal), None)
        return bool(c and c.get("selected", True))

    def writable(self):
        return [c for c in self.all_calendars() if c.get("role") in ("owner", "writer")]

    def default_cal(self):
        want = self.settings.get("default_cal")
        ids = [c["id"] for c in self.writable()]
        if want in ids:
            return want
        prim = next((c["id"] for c in self.calendars if c.get("primary") and c["id"] in ids), None)
        return prim or "local"

    # ----- Abfragen -----
    def occurrences(self, a, b):
        """Alle sichtbaren Termine, die [a, b) berühren, als Anzeige-Instanzen (naive Ortszeit)."""
        out = []
        pend_del = {op["gid"] for op in self.pending if op["op"] == "delete" and op.get("gid")}
        pend_upd = {op["gid"]: op for op in self.pending if op["op"] == "update" and op.get("scope") != "series"}
        sources = (list(self.google.values()) + list(self.local.values()) + self.pending_events() + self.ics_events() +
                   self.holiday_events(a, b) + self.task_events(a, b))
        for ev in sources:
            if not self.visible(ev["cal"]) or ev.get("status") == "cancelled":
                continue
            if ev.get("gid") in pend_del or (ev.get("series") in pend_del and
                                              any(o["op"] == "delete" and o.get("scope") == "series" and
                                                  o["gid"] == ev.get("series") for o in self.pending)):
                continue
            if ev.get("gid") in pend_upd:
                ev = {**ev, **pend_upd[ev["gid"]]["event"], "pending": True}
            out.extend(self.expand(ev, a, b))
        out.sort(key=lambda o: (o["s"], o["e"]))
        return out

    def expand(self, ev, a, b):
        allday = ev.get("allday")
        try:
            s, e = parse_when(ev["start"], allday), parse_when(ev["end"], allday)
        except (KeyError, ValueError):
            return []
        dur = e - s
        if ev.get("rrule"):
            ex = []
            for x in ev.get("exdates", []):
                try:
                    ex.append(parse_when(x, len(x) == 10))
                except ValueError:
                    pass
            try:
                starts = rrule.expand(ev["rrule"], s, a - dur, b, ex)
            except ValueError:
                starts = [s]
        else:
            starts = [s] if s < b and s + dur > a or (dur == dt.timedelta(0) and a <= s < b) else []
        return [{**ev, "s": x, "e": x + dur, "occ": x} for x in starts]

    def upcoming(self, cat, days=180, today=None, limit=12, now=None):
        """Noch nicht vorbeigegangene Termine eines Typs (z. B. "pruefung") in den nächsten `days` Tagen."""
        today = today or dt.date.today()
        now = now or dt.datetime.now(TZ).replace(tzinfo=None)
        t0 = dt.datetime.combine(today, dt.time())
        out = [o for o in self.occurrences(t0, t0 + dt.timedelta(days=days))
               if o.get("cat") == cat and o["e"] > now and o.get("cal") != "holidays"]
        return out[:limit]

    LONG = dt.timedelta(hours=20)

    def mark_conflicts(self, occs):
        """Überschneidende Termine (mit Uhrzeit, mindestens 1 Minute gemeinsam) bekommen o["conflict"] = [Titel …].
        Ganztägige/mehrtägige Termine und Feiertage zählen nicht. Verändert die Instanzen in `occs` (frische Kopien)."""
        timed = sorted((o for o in occs if not o.get("allday") and o["e"] > o["s"] and o["e"] - o["s"] < self.LONG
                        and o.get("cal") != "holidays"), key=lambda o: o["s"])
        active = []
        for o in timed:
            active = [a for a in active if a["e"] > o["s"]]
            for a in active:
                if a["e"] - o["s"] >= dt.timedelta(minutes=1) and (a["uid"], a["s"]) != (o["uid"], o["s"]):
                    a.setdefault("conflict", []).append(o.get("title") or "Termin")
                    o.setdefault("conflict", []).append(a.get("title") or "Termin")
            active.append(o)
        return occs

    def search(self, q, today=None, span_days=540, limit=60):
        """Suche in Titel, Ort, Notiz, Link und Typ aller sichtbaren Termine (±span_days um heute).
        Alle Wörter müssen vorkommen. Kommende zuerst (nächster zuerst), dann vergangene (jüngster zuerst).
        Leere Suche: die nächsten Termine."""
        today = today or dt.date.today()
        words = (q or "").lower().split()
        t0 = dt.datetime.combine(today, dt.time())
        out = []
        for o in self.occurrences(t0 - dt.timedelta(days=span_days), t0 + dt.timedelta(days=span_days)):
            if words:
                from raster import CAT_NAMES
                hay = " ".join(str(o.get(k) or "") for k in ("title", "location", "notes", "link")).lower() + \
                    " " + str(CAT_NAMES.get(o.get("cat"), o.get("cat") or "")).lower()
                if not all(w in hay for w in words):
                    continue
            out.append(o)
        up = [o for o in out if o["e"] >= t0]
        past = [o for o in out if o["e"] < t0]
        past.reverse()
        return (up if not words else up + past)[:limit]

    def find(self, uid):
        if str(uid).startswith("ics:"):
            return next((e for e in self.ics_events() if e["uid"] == uid), None)
        return self.google.get(uid) or self.local.get(uid) or \
            next((op["event"] for op in self.pending if op.get("uid") == uid and op["op"] == "create"), None)

    def recent_locations(self):
        return self.settings.get("locations", [])

    def remember_location(self, loc):
        if not loc:
            return
        locs = [l for l in self.recent_locations() if l != loc]
        self.settings["locations"] = ([loc] + locs)[:25]
        self.save_settings()

    # ----- Ändern -----
    def drop_account(self, acct):
        """Konto entfernt/abgemeldet: seine Kalender, Termine und noch offene Änderungen aus dem Zwischenspeicher nehmen."""
        self.calendars = [c for c in self.calendars if c.get("acct", "main") != acct]
        self.google = {u: e for u, e in self.google.items() if e.get("acct", "main") != acct}
        self.pending = [op for op in self.pending if op.get("acct", "main") != acct]
        self.settings.get("accounts", {}).pop(acct, None)
        if not self.calendars:
            self.synced = None
        self.save_cache()
        self.save_pending()
        self.save_settings()
        self.changed()

    def cal_acct(self, cal):
        """Google-Konto, zu dem ein Kalender gehört (Hauptkonto, wenn unbekannt)."""
        c = next((c for c in self.calendars if c["id"] == cal), None)
        return (c or {}).get("acct", "main")

    def queue(self, op):
        if "acct" not in op:
            op["acct"] = (op.get("event") or {}).get("acct") or self.cal_acct(op["cal"])
        op["id"] = str(uuid.uuid4())
        self.pending.append(op)
        self.save_pending()
        return op

    def save_event(self, ev, scope="single", original=None, send=False):
        """Termin anlegen oder ändern. scope: 'single' | 'instance' | 'series'.
        original: die angezeigte Instanz (für scope='instance' bei Serien)."""
        if self.is_readonly(ev):
            raise ValueError("Dieser Kalender ist nur lesbar (Abo).")
        ev = copy.deepcopy(ev)
        rec = self._rec
        before_local = copy.deepcopy(self.local) if rec else None
        existing = copy.deepcopy(self.find(ev.get("uid"))) if rec and ev.get("uid") else None
        ev.setdefault("cat", guess_cat(ev.get("title")))
        if ev["cal"] != "local" and self.color_for:
            try:
                ev["gcolor"] = self.color_for(ev)
            except Exception:  # noqa: BLE001 – Farbe ist ein Extra
                pass
        if ev["cal"] == "local":
            self._save_local(ev, scope, original)
        else:
            self._save_google(ev, scope, original, send)
        self.remember_location(ev.get("location"))
        if rec:
            title = ev.get("title") or "Termin"
            if ev["cal"] == "local":
                self._push_undo(("geändert: " if existing else "angelegt: ") + title,
                                lambda: self._restore_local(before_local))
            elif existing is None:
                uid, key = ev.get("uid"), (ev["cal"], ev.get("title"), ev.get("start"), ev.get("end"))
                self._push_undo(f"angelegt: {title}", lambda: self._undo_create_google(uid, key))
            elif scope == "series":
                self._push_undo(f"geändert: {title}", None)         # Serie bei Google: Original nicht bekannt
            else:
                self._push_undo(f"geändert: {title}", lambda: self._undo_update_google(existing))
        self.changed()

    def _save_local(self, ev, scope, original):
        if scope == "instance" and original and original.get("rrule"):
            master = self.local[original["uid"]]
            master.setdefault("exdates", []).append(iso(original["occ"], master.get("allday")))
            ev = {**ev, "uid": "local-" + str(uuid.uuid4()), "rrule": None, "exdates": []}
        elif not ev.get("uid") or ev["uid"] not in self.local:
            ev["uid"] = "local-" + str(uuid.uuid4())
        self.local[ev["uid"]] = ev
        self.save_local()

    def _save_google(self, ev, scope, original, send=False):
        is_new = not ev.get("gid")
        if is_new:
            ev["uid"] = ev.get("uid") if str(ev.get("uid", "")).startswith("pending-") else "pending-" + str(uuid.uuid4())
            ev["pending"] = True
            # schon wartendes Anlegen ersetzen statt doppelt hochzuladen
            for op in self.pending:
                if op["op"] == "create" and op["uid"] == ev["uid"]:
                    op["event"] = ev
                    op["send"] = bool(send) or op.get("send", False)
                    self.save_pending()
                    return
            self.queue({"op": "create", "cal": ev["cal"], "uid": ev["uid"], "event": ev, "send": bool(send)})
            return
        target = ev["series"] if scope == "series" and ev.get("series") else ev["gid"]
        self.queue({"op": "update", "cal": ev["cal"], "uid": ev["uid"], "gid": target, "scope": scope, "event": ev,
                    "send": bool(send)})
        if scope != "series" and ev["uid"] in self.google:
            self.google[ev["uid"]] = {**ev, "pending": True}

    def delete_event(self, ev, scope="single", original=None):
        if self.is_readonly(ev):
            raise ValueError("Dieser Kalender ist nur lesbar (Abo).")
        rec = self._rec
        before_local = copy.deepcopy(self.local) if rec else None
        ev_copy = copy.deepcopy(ev) if rec else None
        pend_before = copy.deepcopy(self.pending) if rec else None
        op = self._delete_event(ev, scope, original)
        if rec:
            title = ev_copy.get("title") or "Termin"
            if ev_copy["cal"] == "local":
                self._push_undo(f"gelöscht: {title}", lambda: self._restore_local(before_local))
            elif scope == "series" or ev_copy.get("series"):
                self._push_undo(f"gelöscht: {title}", None)        # Serie/Instanz bei Google: nicht umkehrbar
            elif not ev_copy.get("gid"):
                self._push_undo(f"gelöscht: {title}", lambda: self._restore_pending(pend_before))
            else:
                self._push_undo(f"gelöscht: {title}", lambda: self._undo_delete_google(ev_copy, op))
        self.changed()

    def _delete_event(self, ev, scope, original):
        op = None
        if ev["cal"] == "local":
            if scope == "instance" and original and original.get("rrule"):
                master = self.local[original["uid"]]
                master.setdefault("exdates", []).append(iso(original["occ"], master.get("allday")))
            else:
                self.local.pop(ev["uid"], None)
            self.save_local()
        elif not ev.get("gid"):
            # noch nicht hochgeladen: einfach aus der Warteschlange nehmen
            self.pending = [op for op in self.pending if op.get("uid") != ev["uid"]]
            self.save_pending()
        else:
            target = ev["series"] if scope == "series" and ev.get("series") else ev["gid"]
            op = self.queue({"op": "delete", "cal": ev["cal"], "uid": ev["uid"], "gid": target, "scope": scope,
                             "acct": ev.get("acct") or self.cal_acct(ev["cal"])})
            self.google.pop(ev["uid"], None)
        return op

    # ----- Rückgängig -----
    UNDO_MAX = 30

    def _push_undo(self, label, fn):
        if self._rec:
            self.undo_stack.append((label, fn))
            del self.undo_stack[:-self.UNDO_MAX]

    def can_undo(self):
        return bool(self.undo_stack)

    def undo_label(self):
        return self.undo_stack[-1][0] if self.undo_stack else ""

    def undo(self):
        """Letzte Änderung zurücknehmen. → (ok, Text für die Statuszeile)."""
        if not self.undo_stack:
            return False, "nichts zum Rückgängigmachen"
        label, fn = self.undo_stack.pop()
        if fn is None:
            return False, f"„{label}“ lässt sich nicht zurücknehmen (Serie bei Google)"
        self._rec = False
        try:
            res = fn()
        finally:
            self._rec = True
        self.changed()
        return (res is not False), (f"rückgängig: {label}" if res is not False else f"„{label}“: Termin nicht mehr gefunden")

    class _Group:
        """with store.undo_group("import: 5 Termine") as g: … → ein Rückgängig-Schritt für alles darin."""
        def __init__(self, store, label):
            self.store, self.label = store, label

        def __enter__(self):
            self.start = len(self.store.undo_stack)
            return self

        def __exit__(self, *exc):
            st_ = self.store
            entries = st_.undo_stack[self.start:]
            del st_.undo_stack[self.start:]
            fns = [f for _l, f in entries if f is not None]
            if fns and st_._rec:
                def undo_all():
                    ok_ = True
                    for f in reversed(fns):
                        ok_ = (f() is not False) and ok_
                    return ok_
                st_._push_undo(self.label, undo_all)

    def undo_group(self, label):
        return Store._Group(self, label)

    # ----- Import / Export (.ics) -----
    IMPORT_MAX_GOOGLE = 300

    def import_events(self, events, cal):
        """Gelesene ics-Termine in Kalender `cal` anlegen (ein Rückgängig-Schritt). → Anzahl."""
        todo = [e for e in events if e.get("status") != "cancelled"]
        if self.is_readonly(cal):
            raise ValueError("Der Kalender ist nur lesbar.")
        if cal != "local" and len(todo) > self.IMPORT_MAX_GOOGLE:
            raise ValueError(f"{len(todo)} Termine sind zu viel für Google (höchstens {self.IMPORT_MAX_GOOGLE}) – "
                             "erst in den lokalen Kalender importieren.")
        keys = ("title", "start", "end", "allday", "location", "link", "notes", "cat", "rrule", "exdates")
        with self.undo_group(f"import: {len(todo)} Termine") as g:
            for e in todo:
                new = {k: copy.deepcopy(e.get(k)) for k in keys}
                new.update({"cal": cal, "tone": "", "remind": None, "exdates": e.get("exdates") or []})
                self.save_event(new)
        return len(todo)

    def export_events(self, cal):
        """Termine eines Kalenders für den Export (Store-Format). Google: einzelne Instanzen, lokal: Serien als Regel."""
        if cal == "local":
            return sorted(self.local.values(), key=lambda e: e.get("start", ""))
        if cal.startswith("ics:"):
            return sorted((e for e in self.ics_events() if e["cal"] == cal), key=lambda e: e.get("start", ""))
        return sorted((e for e in self.google.values() if e["cal"] == cal and e.get("status") != "cancelled"),
                      key=lambda e: e.get("start", ""))

    def _restore_local(self, snapshot):
        self.local = copy.deepcopy(snapshot)
        self.save_local()

    def _restore_pending(self, pend):
        self.pending = copy.deepcopy(pend)
        self.save_pending()

    def _undo_create_google(self, uid, key):
        ev = self.find(uid) or next((e for e in self.google.values() if (e["cal"], e.get("title"), e.get("start"),
                                                                         e.get("end")) == key), None)
        if ev is None:
            return False
        self._delete_event(ev, "single", None)

    def _undo_update_google(self, before):
        if not self.find(before.get("uid")):
            return False
        self.save_event(before, scope="single")

    def _undo_delete_google(self, ev, op):
        if op is not None and any(o["id"] == op["id"] for o in self.pending):      # noch nicht bei Google: Auftrag streichen
            self.pending = [o for o in self.pending if o["id"] != op["id"]]
            self.save_pending()
            self.google[ev["uid"]] = {k: v for k, v in ev.items() if k != "pending"}
            self.save_cache()
            return
        new = {k: v for k, v in ev.items() if k not in ("uid", "gid", "series", "html", "updated", "status",
                                                          "color_id", "pending")}
        self.save_event(new)

    # ----- Erinnerungen aus notist -----
    def notist_events(self):
        """nid → Termin, erkannt am Link "notist:<id>" (bleibt auch bei Google erhalten)."""
        out = {}
        for ev in list(self.google.values()) + list(self.local.values()) + self.pending_events():
            link = ev.get("link") or ""
            if link.startswith(NOTIST_LINK) and ev.get("status") != "cancelled":
                out.setdefault(link[len(NOTIST_LINK):], ev)
        return out

    def sync_notist(self):
        """notist legt seine Erinnerungen in data/notist.json ab; hier werden daraus Termine (anlegen, ändern,
        löschen). notist bestimmt, datist folgt. True, wenn sich etwas geändert hat."""
        data = _load(NOTIST_FILE, None)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return False                        # Datei fehlt/kaputt: nichts anfassen
        cal = data.get("cal") or "local"
        if cal not in [c["id"] for c in self.writable()]:
            cal = "local"
        have = self.notist_events()
        changed = False
        self._rec = False                    # kommt von notist, nicht vom Nutzer → nicht rückgängig machen
        try:
            return self._sync_notist_items(data, cal, have)
        finally:
            self._rec = True

    def _sync_notist_items(self, data, cal, have):
        changed = False
        for nid, it in data["items"].items():
            try:
                start = parse_when(it["start"], False)
            except (KeyError, ValueError, TypeError):
                continue
            title = "󰂚 " + (it.get("title") or "Erinnerung")
            end = start + dt.timedelta(minutes=NOTIST_MINUTES)
            ev = have.pop(nid, None)
            if ev:
                try:
                    same = (ev["cal"] == cal and ev.get("title") == title and not ev.get("allday") and
                            parse_when(ev["start"], False) == start and parse_when(ev["end"], False) == end)
                except (KeyError, ValueError):
                    same = False
                if same:
                    continue
                if ev["cal"] != cal:            # anderer Kalender gewählt: dort neu anlegen
                    self.delete_event(ev)
                    ev = None
            new = {"location": "", "notes": "Erinnerung aus notist", "cat": "", "tone": "", "rrule": None,
                   **(ev or {}), "cal": cal, "title": title, "allday": False, "start": iso(start), "end": iso(end),
                   "link": NOTIST_LINK + nid}
            if not ev:
                new.pop("uid", None)
                new.pop("gid", None)
            self.save_event(new)
            changed = True
        for ev in have.values():                 # Erinnerung entfernt oder Notiz gelöscht
            self.delete_event(ev)
            changed = True
        return changed

    def color_fixes(self, all_events=False, skip=()):
        """Google-Termine aus datist, deren Farbe in Google nicht passt → Farb-Aufträge (Serie: einmal am Original).
        all_events=False: nur Termine ganz ohne Google-Farbe (ältere, die dort blau erscheinen)."""
        if not self.color_for:
            return []
        own = {c["id"] for c in self.calendars if c.get("role") in ("owner", "writer")}
        queued = {op["gid"] for op in self.pending if op["op"] in ("color", "update", "delete")} | set(skip)
        done = []
        for ev in list(self.google.values()):
            if not ev.get("dmeta") or ev["cal"] not in own or ev.get("pending"):
                continue
            if not all_events and ev.get("color_id"):
                continue
            want = self.color_for(ev)
            gid = ev.get("series") or ev.get("gid")
            if not want or not gid or want == ev.get("color_id") or gid in queued:
                continue
            queued.add(gid)
            self.queue({"op": "color", "cal": ev["cal"], "uid": ev["uid"], "gid": gid, "colorId": want})
            done.append(gid)
        return done

    def pending_events(self):
        return [op["event"] for op in self.pending if op["op"] == "create"]

    # ----- Ergebnis eines Abgleichs übernehmen -----
    def apply_sync(self, res):
        done = set(res.get("done", []))
        self.pending = [op for op in self.pending if op["id"] not in done]
        self.save_pending()
        if res.get("calendars") is not None:
            skipped = set(res.get("skipped", []))          # Konten, die diesmal nicht drankamen: ihre Kalender bleiben
            self.calendars = res["calendars"] + [c for c in self.calendars if c.get("acct", "main") in skipped]
        if res.get("events") is not None:
            fetched = {(a, c) for a, c in res.get("fetched", [])} | {("main", c) for c in res.get("fetched_cals", [])}
            cal_keys = {(c.get("acct", "main"), c["id"]) for c in self.calendars}
            keep = {u: e for u, e in self.google.items()
                    if (e.get("acct", "main"), e["cal"]) not in fetched and (e.get("acct", "main"), e["cal"]) in cal_keys}
            keep.update(res["events"])
            self.google = keep
            self.window = res.get("window", self.window)
            self.synced = dt.datetime.now(TZ).isoformat(timespec="seconds")
        if res.get("tasks") is not None:
            self.tasks = res["tasks"]
            _save("tasks.json", self.tasks)
        self.save_cache()
        self.changed()
