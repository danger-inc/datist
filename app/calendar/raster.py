# Zeitraster der TU Berlin (Doppelstunden), Kalenderwochen, Veranstaltungstypen.
import datetime as dt
import re
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
TZ_NAME = "Europe/Berlin"

# (Nr, Beginn, Ende) – Pausen ergeben sich aus den Lücken (je 20 min)
DS = [(1, (7, 30), (9, 0)), (2, (9, 20), (10, 50)), (3, (11, 10), (12, 40)), (4, (13, 0), (14, 30)),
      (5, (14, 50), (16, 20)), (6, (16, 40), (18, 10)), (7, (18, 30), (20, 0))]
DAY_START, DAY_END = (7, 30), (20, 0)
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]

# Veranstaltungstypen: Schlüssel, Name, Kürzel, Farbquelle (siehe ui.Palette)
CATS = [("vorlesung", "Vorlesung", "V", "primary"), ("uebung", "Übung", "Ü", "analog"),
        ("seminar", "Seminar", "S", "analog2"), ("praktikum", "Praktikum", "P", "triad"),
        ("pruefung", "Prüfung", "!", "alert"), ("privat", "Privat", "·", "complement"),
        ("sonst", "Sonstiges", "○", "outline")]
CAT_NAMES = {k: n for k, n, _, _ in CATS}
CAT_SHORT = {k: s for k, _, s, _ in CATS}


def minutes(hm):
    return hm[0] * 60 + hm[1]


def ds_times(n):
    _, a, b = DS[n - 1]
    return dt.time(*a), dt.time(*b)


def ds_of(t):
    """Nummer der Doppelstunde, in der Uhrzeit t liegt (oder None in Pausen/außerhalb)."""
    m = t.hour * 60 + t.minute
    for n, a, b in DS:
        if minutes(a) <= m < minutes(b):
            return n
    return None


def ds_span(start, end):
    """Erste/letzte DS, die von [start, end) berührt werden – für Anzeige wie '2.–3. DS'."""
    a, b = start.hour * 60 + start.minute, end.hour * 60 + end.minute
    hit = [n for n, s, e in DS if a < minutes(e) and b > minutes(s)]
    return (hit[0], hit[-1]) if hit else None


def kw(d):
    return d.isocalendar()[1]


def parity(d):
    return "gerade" if kw(d) % 2 == 0 else "ungerade"


def week_start(d):
    return d - dt.timedelta(days=d.weekday())


def guess_cat(title):
    t = (title or "").strip().lower()
    rules = [(r"^(v|vl|vorl)\b|vorlesung|lecture", "vorlesung"), (r"^(ü|ue|ueb)\b|übung|uebung|tutorium|exercise", "uebung"),
             (r"^s\b|seminar|kolloquium|proseminar", "seminar"), (r"praktikum|labor|lab\b", "praktikum"),
             (r"prüfung|pruefung|klausur|exam|testat|abgabe|deadline", "pruefung")]
    for pat, cat in rules:
        if re.search(pat, t):
            return cat
    return "sonst"


def fmt_date(d, year=True):
    return f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}." + (f"{d.year}" if year else "")


def parse_date(text, today=None):
    """'heute', 'morgen', 'übermorgen', '+3', 'mi', 'nächsten mi', '20.10.', '20.10.2026', '2026-10-20'."""
    today = today or dt.date.today()
    t = (text or "").strip().lower()
    if not t or t == "heute":
        return today
    toks = t.split()
    hit = day_phrase(toks, 0, today) if toks and "day_phrase" in globals() else None
    if hit is not None and hit[1] == len(toks):          # „in 2 wochen“, „nächsten mo“, „friday“, „20.10.“ …
        return hit[0]
    if t == "morgen":
        return today + dt.timedelta(days=1)
    if t in ("übermorgen", "uebermorgen"):
        return today + dt.timedelta(days=2)
    m = re.fullmatch(r"([+-])\s*(\d+)\s*([dtw]?)", t)
    if m:
        n = int(m.group(2)) * (7 if m.group(3) == "w" else 1)
        return today + dt.timedelta(days=n if m.group(1) == "+" else -n)
    m = re.fullmatch(r"(?:(nächste[nr]?|naechste[nr]?)\s+)?([a-zäöü]{2,})", t)
    if m:
        for i, (s, l) in enumerate(zip(WEEKDAYS, WEEKDAYS_LONG)):
            if l.lower().startswith(m.group(2)) or s.lower() == m.group(2):
                delta = (i - today.weekday()) % 7
                if m.group(1) and delta == 0:
                    delta = 7
                return today + dt.timedelta(days=delta)
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?", t.split()[-1] if " " in t else t)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        d = dt.date(y, int(m.group(2)), int(m.group(1)))
        if not m.group(3) and d < today - dt.timedelta(days=60):
            d = d.replace(year=y + 1)       # "05.01." im Oktober meint nächstes Jahr
        return d
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise ValueError(f"Datum nicht erkannt: {text}")


EN_DAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2, "thursday": 3,
           "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
_UNIT_DAYS = {"d": 1, "t": 1, "tag": 1, "tage": 1, "tagen": 1, "day": 1, "days": 1,
              "w": 7, "wo": 7, "woche": 7, "wochen": 7, "week": 7, "weeks": 7}
_UNIT_MONTHS = {"monat": 1, "monate": 1, "monaten": 1, "month": 1, "months": 1}


def weekday_word(word):
    """'mo', 'montag', 'mon', 'monday' → 0–6 | None (deutsch exakt/ausgeschrieben, englisch voll oder 3 Buchstaben)."""
    w = word.lower().rstrip(".,")
    if w in EN_DAYS:
        return EN_DAYS[w]
    for i, (s, l) in enumerate(zip(WEEKDAYS, WEEKDAYS_LONG)):
        if w == s.lower() or w == l.lower():
            return i
    return None


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))


def _date_literal(t, today):
    """'20.10.', '20.10.2026', '2026-10-20' → Datum | None (ohne weitere Erkennung, daher rekursionsfrei)."""
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?", t)
    if m:
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        try:
            d = dt.date(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and d < today - dt.timedelta(days=60):
            d = d.replace(year=y + 1)
        return d
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def day_phrase(toks, i, today=None):
    """Tagesangabe ab toks[i]: heute/morgen/übermorgen, +3/+2w, Wochentag, „nächsten Montag“, „übernächsten Freitag“,
    „nächste Woche (Montag)“, „in 3 Tagen / 2 Wochen / 1 Monat“, „next monday“, Datum (20.10., 2026-10-20).
    → (Datum, verbrauchte Wörter) oder None."""
    today = today or dt.date.today()
    n = len(toks)
    a = toks[i].lower().rstrip(",")
    nxt = toks[i + 1].lower().rstrip(",") if i + 1 < n else ""
    if a in ("heute", "today"):
        return today, 1
    if a in ("morgen", "tomorrow"):
        return today + dt.timedelta(days=1), 1
    if a in ("übermorgen", "uebermorgen"):
        return today + dt.timedelta(days=2), 1
    m = re.fullmatch(r"([+-])(\d+)([dtw]?)", a)
    if m:
        k = int(m.group(2)) * (7 if m.group(3) == "w" else 1)
        return today + dt.timedelta(days=k if m.group(1) == "+" else -k), 1
    # in 3 Tagen / in 2w / in 1 Monat
    if a in ("in",) and i + 1 < n:
        m2 = re.fullmatch(r"(\d+)\s*([a-zäöü]+)?", nxt)
        if m2:
            num, unit = int(m2.group(1)), m2.group(2)
            used = 2
            if not unit and i + 2 < n:
                unit, used = toks[i + 2].lower().rstrip(","), 3
            if unit in _UNIT_DAYS:
                return today + dt.timedelta(days=num * _UNIT_DAYS[unit]), used
            if unit in _UNIT_MONTHS:
                return _add_months(today, num), used
    # nächsten Montag / next monday / übernächsten Freitag / nächste Woche [Montag]
    pre = a in ("nächsten", "nächste", "nächster", "naechsten", "naechste", "next", "kommenden", "kommende")
    pre2 = a in ("übernächsten", "übernächste", "uebernaechsten", "uebernaechste")
    if (pre or pre2) and i + 1 < n:
        wd = weekday_word(nxt)
        if wd is not None:
            delta = (wd - today.weekday()) % 7 or 7
            return today + dt.timedelta(days=delta + (7 if pre2 else 0)), 2
        if nxt in ("woche", "week"):
            base = today + dt.timedelta(days=7 - today.weekday() + (7 if pre2 else 0))     # Montag der Zielwoche
            if i + 2 < n:
                wd2 = weekday_word(toks[i + 2])
                if wd2 is not None:
                    return base + dt.timedelta(days=wd2), 3
            return today + dt.timedelta(days=7 * (2 if pre2 else 1)), 2
        if nxt in ("monat", "month"):
            return _add_months(today, 2 if pre2 else 1), 2
    wd = weekday_word(a)
    if wd is not None:
        return today + dt.timedelta(days=(wd - today.weekday()) % 7), 1
    # Datum: 20.10. / 20.10.2026 / 2026-10-20
    d = _date_literal(a, today)
    return (d, 1) if d is not None else None


def parse_time(text):
    t = (text or "").strip().replace(".", ":")
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", t)
    if not m:
        raise ValueError(f"Uhrzeit nicht erkannt: {text}")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h <= 24 and 0 <= mi < 60):
        raise ValueError(f"Uhrzeit nicht erkannt: {text}")
    return dt.time(23, 59) if h == 24 else dt.time(h, mi)


# ---------------------------------------------------------------- Semester (Vorlesungszeit)
# Eigene Angaben stehen in ~/.config/kalender/semester.json (gehen vor), sonst grobe Schätzung:
# [{"name": "WS 2026/27", "start": "2026-10-12", "end": "2027-02-06", "free": [["2026-12-20", "2027-01-03"], …]}]
# 1. Woche („A“) = ungerade Kalenderwoche, 2. Woche („B“) = gerade – unabhängig vom Semester.
import json as _json
import os as _os

SEMESTER_FILE = _os.path.expanduser("~/.config/kalender/semester.json")
WEEKS = [("all", "jede woche"), ("a", "A · 1. woche (ungerade KW)"), ("b", "B · 2. woche (gerade KW)")]


def _monday_on_after(d):
    return d + dt.timedelta(days=(7 - d.weekday()) % 7)


def _saturday_on_before(d):
    return d - dt.timedelta(days=(d.weekday() - 5) % 7)


def _guess(year):
    """Übliche Lage der Vorlesungszeit, falls nichts eingetragen ist."""
    ss = {"name": f"SS {year}", "start": _monday_on_after(dt.date(year, 4, 7)),
          "end": _saturday_on_before(dt.date(year, 7, 19)), "free": [(dt.date(year, 5, 1), dt.date(year, 5, 1))],
          "guess": True}
    ws = {"name": f"WS {year}/{(year + 1) % 100:02d}", "start": _monday_on_after(dt.date(year, 10, 10)),
          "end": _saturday_on_before(dt.date(year + 1, 2, 10)),
          "free": [(dt.date(year, 12, 21), dt.date(year + 1, 1, 3))], "guess": True}
    return [ss, ws]


def semesters():
    own = []
    try:
        with open(SEMESTER_FILE) as f:
            for s in _json.load(f):
                own.append({"name": s["name"], "start": dt.date.fromisoformat(s["start"]),
                            "end": dt.date.fromisoformat(s["end"]),
                            "free": [(dt.date.fromisoformat(a), dt.date.fromisoformat(b)) for a, b in s.get("free", [])],
                            "exams": [(dt.date.fromisoformat(a), dt.date.fromisoformat(b)) for a, b in s.get("exams", [])]})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    y = dt.date.today().year
    out = list(own)
    for g in [x for yy in range(y - 1, y + 3) for x in _guess(yy)]:
        if not any(o["start"] <= g["end"] and g["start"] <= o["end"] for o in own):
            out.append(g)
    return sorted(out, key=lambda s: s["start"])


def semester_for(d):
    """Semester, dessen Vorlesungszeit d enthält – sonst das nächste."""
    for s in semesters():
        if d <= s["end"]:
            return s
    return None


def semester_days(sem, weekday, week="all"):
    """(alle Wochentage der Vorlesungszeit, davon die mit Veranstaltung) – ohne Pausen/Feiertage, ggf. nur A/B."""
    d = sem["start"] + dt.timedelta(days=(weekday - sem["start"].weekday()) % 7)
    every, hit = [], []
    while d <= sem["end"]:
        every.append(d)
        free = any(a <= d <= b for a, b in sem["free"])
        par = kw(d) % 2
        if not free and (week == "all" or (week == "a" and par == 1) or (week == "b" and par == 0)):
            hit.append(d)
        d += dt.timedelta(weeks=1)
    return every, hit
