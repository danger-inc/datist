# Zeitraster der TU Dresden (Doppelstunden), Kalenderwochen, Veranstaltungstypen.
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


def parse_time(text):
    t = (text or "").strip().replace(".", ":")
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", t)
    if not m:
        raise ValueError(f"Uhrzeit nicht erkannt: {text}")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h <= 24 and 0 <= mi < 60):
        raise ValueError(f"Uhrzeit nicht erkannt: {text}")
    return dt.time(23, 59) if h == 24 else dt.time(h, mi)
