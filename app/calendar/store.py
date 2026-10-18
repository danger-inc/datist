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

import rrule
from tudd import TZ, guess_cat

DATA = os.path.expanduser("~/.local/share/kalender/data")   # bewusst nicht in rice-apps (Backup)
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
    with open(tmp, "w") as f:
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
        self.pending = _load("pending.json", [])        # [op]
        self.settings = _load("settings.json", {})
        self.listeners = []

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
    def all_calendars(self):
        return [LOCAL_CAL] + self.calendars

    def visible(self, cal):
        vis = self.settings.get("visible", {})
        if cal in vis:
            return vis[cal]
        if cal == "local":
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
        sources = list(self.google.values()) + list(self.local.values()) + self.pending_events()
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

    def find(self, uid):
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
    def queue(self, op):
        op["id"] = str(uuid.uuid4())
        self.pending.append(op)
        self.save_pending()

    def save_event(self, ev, scope="single", original=None):
        """Termin anlegen oder ändern. scope: 'single' | 'instance' | 'series'.
        original: die angezeigte Instanz (für scope='instance' bei Serien)."""
        ev = copy.deepcopy(ev)
        ev.setdefault("cat", guess_cat(ev.get("title")))
        if ev["cal"] == "local":
            self._save_local(ev, scope, original)
        else:
            self._save_google(ev, scope, original)
        self.remember_location(ev.get("location"))
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

    def _save_google(self, ev, scope, original):
        is_new = not ev.get("gid")
        if is_new:
            ev["uid"] = ev.get("uid") if str(ev.get("uid", "")).startswith("pending-") else "pending-" + str(uuid.uuid4())
            ev["pending"] = True
            # schon wartendes Anlegen ersetzen statt doppelt hochzuladen
            for op in self.pending:
                if op["op"] == "create" and op["uid"] == ev["uid"]:
                    op["event"] = ev
                    self.save_pending()
                    return
            self.queue({"op": "create", "cal": ev["cal"], "uid": ev["uid"], "event": ev})
            return
        target = ev["series"] if scope == "series" and ev.get("series") else ev["gid"]
        self.queue({"op": "update", "cal": ev["cal"], "uid": ev["uid"], "gid": target, "scope": scope, "event": ev})
        if scope != "series" and ev["uid"] in self.google:
            self.google[ev["uid"]] = {**ev, "pending": True}

    def delete_event(self, ev, scope="single", original=None):
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
            self.queue({"op": "delete", "cal": ev["cal"], "uid": ev["uid"], "gid": target, "scope": scope})
            self.google.pop(ev["uid"], None)
        self.changed()

    def pending_events(self):
        return [op["event"] for op in self.pending if op["op"] == "create"]

    # ----- Ergebnis eines Abgleichs übernehmen -----
    def apply_sync(self, res):
        done = set(res.get("done", []))
        self.pending = [op for op in self.pending if op["id"] not in done]
        self.save_pending()
        if res.get("calendars") is not None:
            self.calendars = res["calendars"]
        if res.get("events") is not None:
            fetched_cals = set(res.get("fetched_cals", []))
            keep = {u: e for u, e in self.google.items() if e["cal"] not in fetched_cals and
                    any(c["id"] == e["cal"] for c in self.calendars)}
            keep.update(res["events"])
            self.google = keep
            self.window = res.get("window", self.window)
            self.synced = dt.datetime.now(TZ).isoformat(timespec="seconds")
        self.save_cache()
        self.changed()
