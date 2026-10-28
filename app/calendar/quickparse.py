# datist – Schnelleingabe: „V Analysis nächsten Montag um 14 Uhr für 2h @MA/041 #v !w“.
# Reine Logik ohne GTK. Erkennt Tag (heute, morgen, nächsten Montag, in 2 Wochen, 20.10., English), Uhrzeit
# (14:30, um 14 Uhr, 14-16, von 14 bis 16 Uhr, 2pm, 2ds), Dauer (für 2h, 90min), ganztägig, Ort @…, Typ #…, Regel !…,
# „bis Datum“ und Links; der Rest ist der Titel.
import datetime as dt, re

import raster

CATS = {"v": "vorlesung", "vl": "vorlesung", "ü": "uebung", "ue": "uebung", "s": "seminar", "p": "praktikum",
        "prak": "praktikum", "!": "pruefung", "prüf": "pruefung", "pr": "pruefung", "k": "pruefung",
        "privat": "privat", "priv": "privat", "x": "sonst"}
RULES = {"!w": "weekly", "!g": "even", "!u": "odd", "!kg": "kweven", "!ku": "kwodd", "!m": "monthly",
         "!t": "daily", "!j": "yearly"}
DEFAULT_MIN = 90
ALLDAY = ("ganztägig", "ganztaegig", "ganztags", "allday", "all-day")
FILLER_DAY = ("am", "on", "den")
FILLER_TIME = ("um", "at", "ab")


def _time_tok(t):
    """'14', '14:30', '9' → time; sonst ValueError."""
    return raster.parse_time(t)


def _ampm(tok):
    """'2pm', '2:30pm', '11am' → time | None."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", tok.lower())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (1 <= h <= 12 and mi < 60):
        return None
    h = h % 12 + (12 if m.group(3) == "pm" else 0)
    return dt.time(h, mi)


def time_phrase(toks, i):
    """Uhrzeit ab toks[i]. → (von, bis|None, verbrauchte Wörter) oder None.
    Bloße Zahlen zählen nur mit „um/at“ davor oder „Uhr“ dahinter (sonst „Blatt 4“ = Titel)."""
    n = len(toks)
    j = i
    prefixed = False
    if toks[j].lower() in FILLER_TIME + ("von", "from") and j + 1 < n:
        prefixed = True
        j += 1
    a = toks[j].lower()
    uhr = lambda k: k < n and toks[k].lower().rstrip(".") in ("uhr", "h", "o'clock")
    # von 14 bis 16 (Uhr) / from 2pm to 4pm
    if j + 2 < n and toks[j + 1].lower() in ("bis", "to", "-", "–"):
        t1 = _ampm(a)
        t2 = _ampm(toks[j + 2])
        try:
            if t1 is None and re.fullmatch(r"\d{1,2}(:\d{2})?", a):
                t1 = _time_tok(a)
            if t2 is None and re.fullmatch(r"\d{1,2}(:\d{2})?", toks[j + 2].lower()):
                t2 = _time_tok(toks[j + 2])
        except ValueError:
            t1 = t2 = None
        if t1 and t2 and (prefixed or uhr(j + 3) or ":" in a or _ampm(a)):
            return t1, t2, (j + 3 + (1 if uhr(j + 3) else 0)) - i
    # 14-16 / 14:00-15:30 / 9am-11am (+ „uhr“)
    m = re.fullmatch(r"(\d{1,2}(?::\d{2})?(?:am|pm)?)[-–](\d{1,2}(?::\d{2})?(?:am|pm)?)", a)
    if m:
        try:
            t1 = _ampm(m.group(1)) or _time_tok(m.group(1))
            t2 = _ampm(m.group(2)) or _time_tok(m.group(2))
            return t1, t2, (j + 1 + (1 if uhr(j + 1) else 0)) - i
        except ValueError:
            pass
    # 2pm / 2:30pm / 2 pm
    t = _ampm(a)
    if t is None and j + 1 < n and re.fullmatch(r"\d{1,2}(?::\d{2})?", a) and toks[j + 1].lower() in ("am", "pm"):
        t = _ampm(a + toks[j + 1].lower())
        if t:
            return t, None, (j + 2) - i
    if t:
        return t, None, (j + 1) - i
    # 14:30 (eindeutig) · 14 Uhr / 14uhr / um 14
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(?:uhr|h)?", a)
    if m:
        has_uhr = bool(re.search(r"(uhr|h)$", a)) or uhr(j + 1)
        if m.group(2) is not None or has_uhr or prefixed:
            try:
                t = _time_tok(f"{m.group(1)}:{m.group(2) or '00'}")
            except ValueError:
                return None
            used = 1 if re.search(r"(uhr|h)$", a) else (2 if uhr(j + 1) else 1)
            return t, None, (j + used) - i
    return None


_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(h|std|stunden?|hours?|hrs?|min|minuten?|minutes?)", re.I)


def duration_phrase(toks, i):
    """Dauer: 'für 2h', '90min', '1,5 h', 'for 2 hours' → (timedelta, verbrauchte Wörter) oder None."""
    n = len(toks)
    j = i
    pref = False
    if toks[j].lower() in ("für", "fuer", "for", "dauer") and j + 1 < n:
        pref = True
        j += 1
    a = toks[j]
    m = _DUR.fullmatch(a)
    used = 1
    if not m and j + 1 < n:
        m = _DUR.fullmatch(a + " " + toks[j + 1])
        used = 2
    if not m:
        return None
    if re.fullmatch(r"\d+", a) and not pref:
        return None                                   # „4 min“ ohne „für“ lieber nicht (könnte Titel sein)
    v = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    mins = v * (60 if unit.startswith(("h", "std")) else 1)
    if not (1 <= mins <= 24 * 60):
        return None
    return dt.timedelta(minutes=round(mins)), (j + used) - i


def parse(text, cursor, slot_times, cal, today=None):
    """Text → (Termin-dict, Regel-Preset | None, bis-Datum | None). Wirft ValueError mit verständlichem Text."""
    today = today or dt.date.today()
    day, t_from, t_to, dur = cursor, None, None, None
    loc, link, cat, rule, until, allday = "", "", "", None, None, False
    words = []
    toks = text.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        tl = t.lower()
        # ---- Doppelstunden
        m_ds = re.fullmatch(r"(\d)\.?(?:-(\d)\.?)?\s*ds", tl) or re.fullmatch(r"ds(\d)(?:-(\d))?", tl)
        if m_ds:
            a, b = int(m_ds.group(1)), int(m_ds.group(2) or m_ds.group(1))
            if not (1 <= a <= 7 and 1 <= b <= 7):
                raise ValueError("DS 1–7")
            t_from, t_to = raster.ds_times(a)[0], raster.ds_times(b)[1]
            i += 1
            continue
        if t.startswith("@") and len(t) > 1:
            loc = t[1:]
            i += 1
            continue
        if t.startswith("#") and tl[1:] in CATS:
            cat = CATS[tl[1:]]
            i += 1
            continue
        if tl in RULES:
            rule = RULES[tl]
            i += 1
            continue
        if tl == "bis" and i + 1 < len(toks):
            until = raster.parse_date(toks[i + 1], today)
            i += 2
            continue
        if re.match(r"https?://|www\.", tl):
            link = t
            i += 1
            continue
        if tl in ALLDAY:
            allday = True
            i += 1
            continue
        # ---- Tag (mit Füllwort „am“): „am Montag“, „nächsten Freitag“, „in 2 Wochen“
        j = i + 1 if tl in FILLER_DAY and i + 1 < len(toks) else i
        hit = raster.day_phrase(toks, j, today)
        if hit is not None and (j == i or hit is not None):
            day, used = hit
            i = j + used
            continue
        # ---- Dauer („für 2h“, „90min“)
        dp = duration_phrase(toks, i)
        if dp is not None:
            dur, used = dp
            i += used
            continue
        # ---- Uhrzeit
        tp = time_phrase(toks, i)
        if tp is not None:
            t_from, t_to, used = tp
            i += used
            continue
        words.append(t)
        i += 1
    title = " ".join(words) or "(ohne Titel)"
    if allday:
        ev = {"cal": cal, "title": title, "allday": True, "start": day.isoformat(),
              "end": (day + dt.timedelta(days=1)).isoformat(), "location": loc, "link": link, "notes": "",
              "cat": cat or raster.guess_cat(title), "tone": "", "rrule": None}
        return ev, rule, until
    if t_from is None:
        t_from, default_to = slot_times
        if t_to is None and dur is None:
            t_to = default_to
    s = dt.datetime.combine(day, t_from)
    if t_to is None:
        e = s + (dur or dt.timedelta(minutes=DEFAULT_MIN))
    else:
        e = dt.datetime.combine(day, t_to)
        if e <= s:
            e = s + (dur or dt.timedelta(minutes=DEFAULT_MIN))
    import store as st
    ev = {"cal": cal, "title": title, "allday": False, "start": st.iso(s), "end": st.iso(e),
          "location": loc, "link": link, "notes": "", "cat": cat or raster.guess_cat(title), "tone": "", "rrule": None}
    return ev, rule, until


def parse_task(text, today=None):
    """„Blatt 4 abgeben bis freitag“ / „Abgabe in 3 Tagen“ → (Titel, Fälligkeit 'YYYY-MM-DD' | None).
    Das Datum erkennt dieselbe Logik wie die Schnelleingabe; „bis/am/until“ davor wird mitgenommen."""
    today = today or dt.date.today()
    toks = text.split()
    words, due, i = [], None, 0
    while i < len(toks):
        j = i + 1 if toks[i].lower() in ("bis", "until", "am", "on", "due") and i + 1 < len(toks) else i
        hit = raster.day_phrase(toks, j, today)
        if hit is not None:
            due, used = hit[0].isoformat(), hit[1]
            i = j + used
            continue
        words.append(toks[i])
        i += 1
    return " ".join(words).strip() or "(ohne Titel)", due
