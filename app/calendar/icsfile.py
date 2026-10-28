# datist – iCalendar (.ics): Lesen (Import, Abo) und Schreiben (Export). Reine Logik, ohne GTK.
# Termine kommen im Store-Format heraus: start/end als ISO mit Zeitzone (ganztägig: Datum, Ende exklusiv),
# rrule/exdates als Text, Überschreibungen einzelner Wiederholungen (RECURRENCE-ID) als eigene Termine.
import datetime as dt, re, uuid
from zoneinfo import ZoneInfo

from raster import TZ, TZ_NAME, guess_cat

# Windows-/Outlook-Zeitzonennamen → IANA
WIN_TZ = {"W. Europe Standard Time": "Europe/Berlin", "Central Europe Standard Time": "Europe/Budapest",
          "Romance Standard Time": "Europe/Paris", "GMT Standard Time": "Europe/London", "UTC": "UTC",
          "Eastern Standard Time": "America/New_York", "Pacific Standard Time": "America/Los_Angeles",
          "Central Standard Time": "America/Chicago", "E. Europe Standard Time": "Europe/Chisinau",
          "FLE Standard Time": "Europe/Kyiv", "Russian Standard Time": "Europe/Moscow"}
MAX_EVENTS = 20000


# ---------- Lesen ----------
def _unfold(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(v):
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _split_prop(line):
    """'DTSTART;TZID=Europe/Berlin:2026…' → ('DTSTART', {'TZID': 'Europe/Berlin'}, '2026…')"""
    i, q = 0, False
    for i, ch in enumerate(line):                       # erstes ':' außerhalb von Anführungszeichen
        if ch == '"':
            q = not q
        elif ch == ":" and not q:
            break
    else:
        return None
    head, value = line[:i], line[i + 1:]
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _zone(name):
    if not name:
        return TZ
    name = WIN_TZ.get(name, name)
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 – unbekannte Zone: wie lokale Zeit behandeln
        return TZ


def _when(value, params):
    """→ (ISO-Text, ganztägig). Zeiten werden in die lokale Zone umgerechnet."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        d = dt.datetime.strptime(value[:8], "%Y%m%d").date()
        return d.isoformat(), True
    fmt = "%Y%m%dT%H%M%S" if len(value.rstrip("Z")) >= 15 else "%Y%m%dT%H%M"
    naive = dt.datetime.strptime(value.rstrip("Z"), fmt)
    if value.endswith("Z"):
        aware = naive.replace(tzinfo=dt.timezone.utc)
    else:
        aware = naive.replace(tzinfo=_zone(params.get("TZID")))
    return aware.astimezone(TZ).isoformat(timespec="seconds"), False


def _duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _events(text):
    """Rohe VEVENT-Blöcke als {NAME: [(params, value)]}."""
    cal_name, cur, out, depth = None, None, [], 0
    for line in _unfold(text):
        if not line.strip():
            continue
        u = line.upper()
        if u == "BEGIN:VEVENT":
            cur = {}
        elif u == "END:VEVENT":
            if cur is not None:
                out.append(cur)
            cur = None
        elif cur is not None:
            p = _split_prop(line)
            if p:
                cur.setdefault(p[0], []).append((p[1], p[2]))
        elif u.startswith("X-WR-CALNAME"):
            p = _split_prop(line)
            if p:
                cal_name = _unescape(p[2]).strip()
        if len(out) > MAX_EVENTS:
            break
    return cal_name, out


def _first(ev, name, default=""):
    return ev[name][0][1] if ev.get(name) else default


def parse(text, uid_prefix=""):
    """ics-Text → (Kalendername | None, [Termin-dict]). Wirft ValueError, wenn gar kein Kalender erkennbar ist."""
    if "BEGIN:VCALENDAR" not in text.upper():
        raise ValueError("keine gültige Kalenderdatei (BEGIN:VCALENDAR fehlt)")
    name, raw = _events(text)
    masters, overrides, out = {}, [], []
    for ev in raw:
        try:
            ds = ev["DTSTART"][0]
            start, allday = _when(ds[1], ds[0])
        except (KeyError, ValueError):
            continue                                    # Termin ohne lesbaren Beginn überspringen
        end = None
        try:
            if ev.get("DTEND"):
                end, _ = _when(ev["DTEND"][0][1], ev["DTEND"][0][0])
            elif ev.get("DURATION"):
                dur = _duration(ev["DURATION"][0][1])
                if dur is not None:
                    s0 = dt.datetime.fromisoformat(start) if not allday else dt.datetime.fromisoformat(start + "T00:00:00")
                    e0 = s0 + dur
                    end = e0.date().isoformat() if allday else e0.isoformat(timespec="seconds")
        except ValueError:
            end = None
        if end is None:
            if allday:
                end = (dt.date.fromisoformat(start) + dt.timedelta(days=1)).isoformat()
            else:
                end = (dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)).isoformat(timespec="seconds")
        title = _unescape(_first(ev, "SUMMARY")).strip() or "(ohne Titel)"
        uid = _first(ev, "UID") or str(uuid.uuid4())
        exdates = []
        for params, val in ev.get("EXDATE", []):
            for part in val.split(","):
                try:
                    w, ad = _when(part, params)
                    exdates.append(w)
                except ValueError:
                    pass
        rule = _first(ev, "RRULE").strip() or None
        item = {"uid": uid_prefix + uid, "ics_uid": uid, "gid": None, "series": None, "title": title, "start": start,
                "end": end, "allday": allday, "location": _unescape(_first(ev, "LOCATION")).strip(),
                "link": _unescape(_first(ev, "URL")).strip(), "notes": _unescape(_first(ev, "DESCRIPTION")).strip(),
                "cat": guess_cat(title), "tone": "", "rrule": rule, "exdates": exdates,
                "status": "cancelled" if _first(ev, "STATUS").upper() == "CANCELLED" else "confirmed"}
        if ev.get("RECURRENCE-ID"):
            try:
                item["recurrence_id"] = _when(ev["RECURRENCE-ID"][0][1], ev["RECURRENCE-ID"][0][0])[0]
            except ValueError:
                continue
            overrides.append(item)
        else:
            masters[uid] = item
            out.append(item)
    for ov in overrides:                                # geänderte einzelne Wiederholung: Master überspringt sie
        m = masters.get(ov["ics_uid"])
        if m is not None:
            m["exdates"].append(ov["recurrence_id"])
        ov["uid"] = f'{ov["uid"]}#{ov["recurrence_id"]}'
        ov["rrule"], ov["exdates"] = None, []
        out.append(ov)
    return name, out


# ---------- Schreiben ----------
BERLIN_TZ = ("BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nBEGIN:STANDARD\r\nDTSTART:19701025T030000\r\n"
             "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\r\nTZOFFSETFROM:+0200\r\nTZOFFSETTO:+0100\r\nTZNAME:CET\r\n"
             "END:STANDARD\r\nBEGIN:DAYLIGHT\r\nDTSTART:19700329T020000\r\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\r\n"
             "TZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\nTZNAME:CEST\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n")


def _esc(v):
    return (v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line):
    """Zeilen auf höchstens 75 Byte umbrechen (Folgezeilen beginnen mit Leerzeichen)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if size + b > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += b
    out.append(cur)
    return "\r\n ".join(out)


def _local(iso_text):
    d = dt.datetime.fromisoformat(iso_text)
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def to_ics(events, name="datist"):
    """Termine (Store-Format) → ics-Text. Serien als RRULE/EXDATE; Zeiten mit TZID (Europe/Berlin) samt VTIMEZONE."""
    use_tz = TZ_NAME == "Europe/Berlin"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//datist//DE", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:" + _esc(name)]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = []
    for ev in events:
        if ev.get("status") == "cancelled":
            continue
        uid = ev.get("ics_uid") or ev.get("gid") or ev.get("uid") or str(uuid.uuid4())
        body.append("BEGIN:VEVENT")
        body.append(f"UID:{uid}")
        body.append(f"DTSTAMP:{stamp}")
        if ev.get("allday"):
            body.append("DTSTART;VALUE=DATE:" + ev["start"][:10].replace("-", ""))
            body.append("DTEND;VALUE=DATE:" + ev["end"][:10].replace("-", ""))
        else:
            s, e = _local(ev["start"]), _local(ev["end"])
            if use_tz:
                body.append("DTSTART;TZID=Europe/Berlin:" + s.strftime("%Y%m%dT%H%M%S"))
                body.append("DTEND;TZID=Europe/Berlin:" + e.strftime("%Y%m%dT%H%M%S"))
            else:
                body.append("DTSTART:" + s.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
                body.append("DTEND:" + e.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        body.append("SUMMARY:" + _esc(ev.get("title")))
        if ev.get("location"):
            body.append("LOCATION:" + _esc(ev["location"]))
        notes = ev.get("notes") or ""
        if notes.strip():
            body.append("DESCRIPTION:" + _esc(notes))
        link = ev.get("link") or ""
        if link.startswith(("http://", "https://")):
            body.append("URL:" + link)
        if ev.get("rrule"):
            body.append("RRULE:" + ev["rrule"].replace("RRULE:", ""))
            ex = ev.get("exdates") or []
            timed = [x for x in ex if len(x) > 10]
            days = [x for x in ex if len(x) == 10]
            if timed and not ev.get("allday"):
                vals = ",".join(_local(x).strftime("%Y%m%dT%H%M%S") for x in timed)
                body.append(("EXDATE;TZID=Europe/Berlin:" if use_tz else "EXDATE:") + vals)
            if days and ev.get("allday"):
                body.append("EXDATE;VALUE=DATE:" + ",".join(x.replace("-", "") for x in days))
        body.append("END:VEVENT")
    text = "\r\n".join(_fold(l) for l in lines) + "\r\n"
    if use_tz and any(l.startswith("DTSTART;TZID") for l in body):
        text += BERLIN_TZ
    text += "\r\n".join(_fold(l) for l in body) + ("\r\n" if body else "") + "END:VCALENDAR\r\n"
    return text
