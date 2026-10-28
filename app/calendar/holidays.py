# datist – Feiertage (bundesweit + je Bundesland), Vorlesungszeit-Marken und „vorlesungsfrei / Prüfungsphase“.
# Alles wird berechnet (Ostern nach Gauß), nichts aus dem Netz. Das Bundesland steht in den Einstellungen
# ("holiday_state", leer = nur bundesweit) – nichts davon wird geraten.
import datetime as dt

STATES = [("", "nur bundesweit"), ("BW", "Baden-Württemberg"), ("BY", "Bayern"), ("BE", "Berlin"),
          ("BB", "Brandenburg"), ("HB", "Bremen"), ("HH", "Hamburg"), ("HE", "Hessen"),
          ("MV", "Mecklenburg-Vorpommern"), ("NI", "Niedersachsen"), ("NW", "Nordrhein-Westfalen"),
          ("RP", "Rheinland-Pfalz"), ("SL", "Saarland"), ("SN", "Sachsen"), ("ST", "Sachsen-Anhalt"),
          ("SH", "Schleswig-Holstein"), ("TH", "Thüringen")]
GLYPH = "󰃳 "            # Titelzeichen für Feiertage
MARK = "󰐕 "            # Titelzeichen für Vorlesungsbeginn/-ende


def easter(year):
    """Ostersonntag (Gaußsche Osterformel)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def holidays(year, state=""):
    """{Datum: Name} der gesetzlichen Feiertage des Jahres (bundesweit + Bundesland)."""
    e = easter(year)
    out = {dt.date(year, 1, 1): "Neujahr", e - dt.timedelta(days=2): "Karfreitag",
           e + dt.timedelta(days=1): "Ostermontag", dt.date(year, 5, 1): "Tag der Arbeit",
           e + dt.timedelta(days=39): "Christi Himmelfahrt", e + dt.timedelta(days=50): "Pfingstmontag",
           dt.date(year, 10, 3): "Tag der Deutschen Einheit", dt.date(year, 12, 25): "1. Weihnachtstag",
           dt.date(year, 12, 26): "2. Weihnachtstag"}
    s = (state or "").upper()
    if s in ("BW", "BY", "ST"):
        out[dt.date(year, 1, 6)] = "Heilige Drei Könige"
    if s == "BE" or (s == "MV" and year >= 2023):
        out[dt.date(year, 3, 8)] = "Internationaler Frauentag"
    if s in ("BW", "BY", "HE", "NW", "RP", "SL"):
        out[e + dt.timedelta(days=60)] = "Fronleichnam"
    if s == "SL":
        out[dt.date(year, 8, 15)] = "Mariä Himmelfahrt"
    if s == "TH":
        out[dt.date(year, 9, 20)] = "Weltkindertag"
    if s in ("BB", "HB", "HH", "MV", "NI", "SN", "ST", "SH", "TH"):
        out[dt.date(year, 10, 31)] = "Reformationstag"
    if s in ("BW", "BY", "NW", "RP", "SL"):
        out[dt.date(year, 11, 1)] = "Allerheiligen"
    if s == "SN":                                   # Mittwoch vor dem 23. November
        d = dt.date(year, 11, 22)
        while d.weekday() != 2:
            d -= dt.timedelta(days=1)
        out[d] = "Buß- und Bettag"
    return out


def holiday_on(d, state=""):
    return holidays(d.year, state).get(d)


# ---------- Semester ----------
def own_semesters(sems):
    """Nur eingetragene Semester (keine geschätzten) – sonst gäbe es falsche Marken."""
    return [s for s in sems if not s.get("guess")]


def lecture_state(d, sems):
    """'vorlesung' | 'frei' | 'pruefung' | None (unbekannt: kein Semester eingetragen oder außerhalb)."""
    own = own_semesters(sems)
    if not own:
        return None
    for s in own:
        for a, b in s.get("exams", []):
            if a <= d <= b:
                return "pruefung"
    for s in own:
        if s["start"] <= d <= s["end"]:
            return "frei" if any(a <= d <= b for a, b in s.get("free", [])) else "vorlesung"
    first, last = own[0]["start"], max(s["end"] for s in own)
    if first <= d <= last:
        return "frei"                               # zwischen zwei Semestern
    return None


def span_state(days, sems):
    """Gleicher Zustand an allen Tagen (z. B. Mo–Fr einer Woche)? → 'frei' | 'pruefung' | 'vorlesung' | None."""
    states = {lecture_state(d, sems) for d in days}
    return states.pop() if len(states) == 1 else None


def events(a, b, state, sems):
    """Als schreibgeschützte ganztägige Termine (Store-Format) im Bereich [a, b) – Feiertage, Vorlesungsbeginn/-ende,
    freie Zeiträume und Prüfungsphasen eingetragener Semester."""
    out = []

    def add(d, name, glyph, last=None, kind="hol"):
        end = (last or d) + dt.timedelta(days=1)
        if end > a and d < b:
            out.append({"uid": f"{kind}:{d.isoformat()}:{name}", "ics_uid": None, "gid": None, "series": None, "cal": "holidays",
                        "title": glyph + name, "start": d.isoformat(), "end": end.isoformat(), "allday": True,
                        "location": "", "link": "", "notes": "", "cat": "sonst", "tone": "", "rrule": None,
                        "exdates": [], "status": "confirmed"})
    for y in range(a.year, (b - dt.timedelta(days=1)).year + 1):
        for d, name in holidays(y, state).items():
            add(d, name, GLYPH)
    for s in own_semesters(sems):
        add(s["start"], f"Vorlesungsbeginn {s['name']}", MARK, kind="sem")
        add(s["end"], f"Vorlesungsende {s['name']}", MARK, kind="sem")
        for x, y in s.get("free", []):
            if y > x:                               # einzelne freie Tage sind meist ohnehin Feiertage
                add(x, "vorlesungsfrei", "󰒲 ", last=y, kind="free")
        for x, y in s.get("exams", []):
            add(x, f"Prüfungsphase {s['name']}", "󰙏 ", last=y, kind="exam")
    return out
