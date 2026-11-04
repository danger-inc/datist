# datist – Termin aus einem Satz anlegen, ohne Oberfläche („grillen nächste woche mittwoch“, „V Mathe mi 2ds @MA/041“).
# Gleiche Erkennung wie die Schnelleingabe (a) in datist; ohne Uhrzeit/DS/Dauer wird der Termin ganztägig.
# Benutzt von `datist --add "text"` (und damit von inquirist, Präfix „a “).
import datetime as dt

import quickparse
import raster
import store as st
import rrule

_NONE = (dt.time(0, 0), dt.time(0, 1))             # Platzhalter: „keine Zeit angegeben“


def build(text, cal="local", today=None):
    """Text → (Termin-dict, Regel-Preset | None, bis-Datum | None). ValueError mit lesbarem Text."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Was für ein Termin?")
    today = today or dt.date.today()
    ev, rule, until = quickparse.parse(text, today, _NONE, cal, today=today)
    if not ev.get("allday") and ev["start"][11:16] == "00:00" and ev["end"][11:16] == "00:01":
        day = st.parse_when(ev["start"], False).date()
        ev.update(allday=True, start=day.isoformat(), end=(day + dt.timedelta(days=1)).isoformat())
    return ev, rule, until


def finish(ev, rule, until):
    """Wiederholungsregel einbauen (wie datist.quick_add)."""
    if rule:
        allday = bool(ev.get("allday"))
        s = st.parse_when(ev["start"], allday)
        r, s2 = rrule.preset_rule(rule, s, until=until)
        if s2 != s:
            dur = st.parse_when(ev["end"], allday) - s
            e2 = s2 + dur
            ev["start"], ev["end"] = (s2.date().isoformat(), e2.date().isoformat()) if allday else (st.iso(s2), st.iso(e2))
        ev["rrule"] = r
    return ev


def describe(ev):
    s = st.parse_when(ev["start"], bool(ev.get("allday")))
    day = f"{raster.WEEKDAYS[s.weekday()]} {s:%d.%m.}"
    if ev.get("allday"):
        return f"{day} · ganztägig"
    e = st.parse_when(ev["end"], False)
    return f"{day} · {s:%H:%M}–{e:%H:%M}"


def create(text, store=None):
    """Legt den Termin im Standardkalender an. → Termin-dict."""
    store = store or st.Store()
    ev, rule, until = build(text, store.default_cal())
    finish(ev, rule, until)
    store.save_event(ev)
    return ev
