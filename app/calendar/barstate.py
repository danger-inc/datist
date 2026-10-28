# datist – Waybar-Anzeige: ein/aus und welche Termine in der Leiste versteckt sind.
# Eigene Datei (bar.json im Datenordner), damit die Kommandozeile (Rechtsklick in der Leiste) und die App sich nicht
# gegenseitig Einstellungen überschreiben: beide lesen bei jedem Zugriff frisch und schreiben atomar.
import datetime as dt, subprocess

import store as st

FILE = "bar.json"
SIGNAL = "RTMIN+8"          # muss zu "signal": 8 im Waybar-Modul passen


def load():
    d = st._load(FILE, {})
    return {"on": bool(d.get("on", True)), "hidden": [h for h in d.get("hidden", []) if isinstance(h, dict) and h.get("key")]}


def save(d):
    st._save(FILE, d)


def key_of(o):
    """Schlüssel eines Termins: Serien (Google oder lokal) als Ganzes, sonst der einzelne Termin."""
    return str(o.get("series") or o.get("uid") or "")


def occ_key(o):
    """Schlüssel nur dieses einen Termins (bei Serien: nur diese Wiederholung)."""
    s = o.get("s")
    return f"{o.get('uid')}@{s.isoformat(timespec='minutes')}" if s else str(o.get("uid") or "")


def is_recurring(o):
    return bool(o.get("series") or o.get("rrule"))


def is_hidden(o, hidden=None):
    hidden = load()["hidden"] if hidden is None else hidden
    keys = {key_of(o), occ_key(o)}
    return any(h["key"] in keys for h in hidden)


def hide(o, series=None):
    """Termin in der Leiste verstecken → Eintrag (für „wieder zeigen“). series=True: bei Serien die ganze Serie,
    False: nur diese Wiederholung; None: Serien als Ganzes, Einzeltermine einzeln."""
    d = load()
    if series is None:
        series = is_recurring(o)
    k = occ_key(o) if (is_recurring(o) and not series and o.get("s")) else key_of(o)
    if any(h["key"] == k for h in d["hidden"]):
        return next(h for h in d["hidden"] if h["key"] == k)
    series = bool(series and is_recurring(o))
    entry = {"key": k, "title": o.get("title") or "Termin", "series": series,
             "when": (o["s"].strftime("%d.%m. %H:%M") if o.get("s") else "")}
    d["hidden"].append(entry)
    save(d)
    return entry


def show(key):
    d = load()
    d["hidden"] = [h for h in d["hidden"] if h["key"] != key]
    save(d)


def show_all():
    d = load()
    d["hidden"] = []
    save(d)


def set_on(on):
    d = load()
    d["on"] = bool(on)
    save(d)


def signal_waybar():
    """Waybar sofort neu zeichnen lassen (statt bis zu 60 s zu warten)."""
    try:
        subprocess.run(["pkill", f"-{SIGNAL}", "-x", "waybar"], capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass
