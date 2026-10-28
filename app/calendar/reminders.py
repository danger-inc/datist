# datist – Erinnerungen: Desktop-Meldung vor einem Termin (notify-send, sonst Gio.Notification).
# Vorlauf je Termin im Feld ev["remind"]: None = Standard, -1 = keine, sonst Minuten vor dem Beginn.
# Der Takt läuft in der App (Hintergrundprozess beim Login), alle Zeiten sind naive Ortszeit wie im Store.
import datetime as dt, hashlib, re, shutil, subprocess

from raster import TZ

DEFAULT_LEAD = 10                       # Minuten
NOTIST_LINK = "notist:"                 # notist-Erinnerungen: Meldung zum Zeitpunkt selbst
KEEP_FIRED = dt.timedelta(days=3)


def now():
    """Jetzt als naive Ortszeit (Tests ersetzen diese Funktion)."""
    return dt.datetime.now(TZ).replace(tzinfo=None)


# ---------- Eingabe / Anzeige ----------
_UNITS = {"": 1, "m": 1, "min": 1, "minute": 1, "minuten": 1,
          "h": 60, "std": 60, "stunde": 60, "stunden": 60,
          "d": 1440, "t": 1440, "tag": 1440, "tage": 1440, "tagen": 1440,
          "w": 10080, "wo": 10080, "woche": 10080, "wochen": 10080}


def parse_lead(text):
    """'' → None (Standard) · 'keine'/'aus'/'-' → -1 · '10', '10 min', '2 h', '1 tag', '1d 2h' → Minuten.
    Wirft ValueError bei Unsinn."""
    t = (text or "").strip().lower()
    if not t or t in ("standard", "std"):
        return None
    if t in ("keine", "kein", "aus", "-", "nein", "no", "off"):
        return -1
    if t in ("zum beginn", "beginn", "pünktlich", "jetzt", "sofort"):
        return 0
    total, rest = 0, t
    for m in re.finditer(r"(\d+)\s*([a-zäöü]*)", t):
        n, unit = int(m.group(1)), m.group(2)
        if unit not in _UNITS:
            raise ValueError(f"„{m.group(0).strip()}“ verstehe ich nicht (z. B. 10, 30 min, 2 h, 1 tag, keine)")
        total += n * _UNITS[unit]
        rest = rest.replace(m.group(0), "", 1)
    if not re.fullmatch(r"[\s,+und]*", rest) or total > 4 * 10080:
        raise ValueError("Vorlauf nicht erkannt (z. B. 10, 30 min, 2 h, 1 tag, keine) – höchstens 4 Wochen")
    return total


def fmt_lead(m):
    """Minuten → '10 min' / '2 h' / '1 tag' / 'keine' / 'zum beginn' ('' bei None = Standard)."""
    if m is None:
        return ""
    if m < 0:
        return "keine"
    if m == 0:
        return "zum beginn"
    if m % 10080 == 0:
        n = m // 10080
        return f"{n} woche" + ("n" if n > 1 else "")
    if m % 1440 == 0:
        n = m // 1440
        return f"{n} tag" + ("e" if n > 1 else "")
    if m % 60 == 0:
        return f"{m // 60} h"
    return f"{m} min"


def fmt_in(minutes):
    if minutes <= 0:
        return "jetzt"
    if minutes < 90:
        return f"in {minutes} min"
    if minutes < 36 * 60:
        h = round(minutes / 60)
        return f"in {h} h"
    return f"in {round(minutes / 1440)} tagen"


# ---------- Meldung senden ----------
def send(app, title, body="", key="", urgency="normal"):
    """Desktop-Meldung. key = Ersetzungsschlüssel (gleiche Meldung nicht doppelt stapeln)."""
    if shutil.which("notify-send"):
        cmd = ["notify-send", "-a", "datist", "-i", "datist", "-u", urgency, "-c", "calendar"]
        if key:
            cmd += ["-h", "string:x-canonical-private-synchronous:datist-" + hashlib.md5(key.encode()).hexdigest()[:12]]
        try:
            subprocess.Popen(cmd + [title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except OSError:
            pass
    try:                                    # ohne notify-send (z. B. Windows): GIO-Meldung der Anwendung
        from gi.repository import Gio
        n = Gio.Notification.new(title)
        n.set_body(body)
        app.send_notification("datist-" + (key or title), n)
        return True
    except Exception:  # noqa: BLE001 – eine Meldung darf nie die App stören
        return False


def send_action(app, title, body, key, action_id, action_label, callback):
    """Meldung mit einem Knopf („Jetzt erneuern“). Geht nur mit notify-send ≥ 0.8; sonst normale Meldung.
    callback() läuft im GTK-Hauptthread, wenn der Knopf gedrückt wurde."""
    if not shutil.which("notify-send"):
        return send(app, title, body, key)
    cmd = ["notify-send", "-a", "datist", "-i", "datist", "-u", "normal", "-c", "calendar",
           "-A", f"{action_id}={action_label}", "-h",
           "string:x-canonical-private-synchronous:datist-" + hashlib.md5(key.encode()).hexdigest()[:12],
           title, body]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                start_new_session=True)
    except OSError:
        return False

    def wait():
        try:
            out = proc.communicate(timeout=3600)[0] or ""
        except Exception:  # noqa: BLE001
            proc.kill()
            return
        if out.strip() == action_id:
            from gi.repository import GLib
            GLib.idle_add(lambda: (callback(), False)[1])
    import threading
    threading.Thread(target=wait, daemon=True).start()
    return True


# ---------- Planer ----------
class Reminders:
    """Prüft regelmäßig, welche Termine jetzt eine Erinnerung brauchen, und meldet sie genau einmal."""
    HORIZON = dt.timedelta(days=5)          # so weit voraus wird gesucht (größter Vorlauf: 4 Wochen → Sonderfall unten)
    GRACE = dt.timedelta(minutes=5)         # „zum Beginn“: noch so lange nach dem Beginn melden

    def __init__(self, store, notify):
        self.store = store
        self.notify = notify                # (titel, text, schlüssel) → None
        self.fired = dict(store.settings.get("fired", {}))
        self._dirty = False

    # ----- Einstellungen -----
    def enabled(self):
        return bool(self.store.settings.get("remind_on", True))

    def default_lead(self):
        v = self.store.settings.get("remind_default", DEFAULT_LEAD)
        return v if isinstance(v, int) and v >= 0 else DEFAULT_LEAD

    def lead_for(self, ev):
        """Vorlauf in Minuten für diesen Termin, None = keine Erinnerung."""
        r = ev.get("remind")
        if r is None:
            if (ev.get("link") or "").startswith(NOTIST_LINK):
                return 0
            if ev.get("allday"):
                return None                 # ganztägig: nur auf ausdrücklichen Wunsch
            return self.default_lead()
        return None if r < 0 else r

    # ----- Takt -----
    def due(self, at=None):
        """[(Termin-Instanz, Vorlauf, Beginn)] die jetzt gemeldet werden sollen (noch nicht gemeldet)."""
        at = at or now()
        out = []
        lo = at - self.GRACE
        hi = at + self.HORIZON + dt.timedelta(days=28)
        for o in self.store.occurrences(lo, hi):
            lead = self.lead_for(o)
            if lead is None:
                continue
            s = o["s"]
            fire = s - dt.timedelta(minutes=lead)
            if not (fire <= at < s + (self.GRACE if lead == 0 else dt.timedelta(0))):
                continue
            key = f'{o.get("uid")}|{s.isoformat()}|{lead}'
            if key in self.fired:
                continue
            out.append((o, lead, s, key))
        return out

    def tick(self, at=None):
        at = at or now()
        if not self.enabled():
            return 0
        n = 0
        for o, lead, s, key in self.due(at):
            self.fired[key] = at.isoformat()
            self._dirty = True
            mins = int((s - at).total_seconds() // 60) + (1 if (s - at).total_seconds() % 60 else 0)
            title = f"{fmt_in(mins)}: {o.get('title') or 'Termin'}"
            e = o["e"]
            when = f"{s:%H:%M}–{e:%H:%M}" if not o.get("allday") else "ganztägig"
            if s.date() != at.date():
                when = f"{s:%a %d.%m. %H:%M}" if not o.get("allday") else f"{s:%a %d.%m.} ganztägig"
            body = when + (f" · {o['location']}" if o.get("location") else "")
            try:
                self.notify(title, body, key)
            except Exception:  # noqa: BLE001
                pass
            n += 1
        # alte Einträge vergessen
        cut = at - KEEP_FIRED
        for k, v in list(self.fired.items()):
            try:
                if dt.datetime.fromisoformat(v) < cut:
                    del self.fired[k]
                    self._dirty = True
            except ValueError:
                del self.fired[k]
                self._dirty = True
        if self._dirty:
            self.store.settings["fired"] = self.fired
            self.store.save_settings()
            self._dirty = False
        return n
