# Wiederholungsregeln (RFC 5545 RRULE) – Ausrollen für lokale Termine und deutsche Beschreibung.
# Google rollt Serien selbst aus (singleEvents=true); hier geht es um lokale/offline angelegte Termine
# und um die Vorschau im Editor. Unterstützt: FREQ, INTERVAL, COUNT, UNTIL, BYDAY (auch 2MO/-1FR),
# BYMONTHDAY, BYMONTH, BYWEEKNO (mit FREQ=YEARLY), WKST=MO.
import calendar
import datetime as dt

from tudd import TZ, WEEKDAYS, WEEKDAYS_LONG, MONTHS

DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def parse(rule):
    rule = (rule or "").strip()
    if rule.upper().startswith("RRULE:"):
        rule = rule[6:]
    out = {}
    for part in rule.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().upper()] = v.strip().upper()
    if out.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        raise ValueError("FREQ fehlt oder wird nicht unterstützt (DAILY, WEEKLY, MONTHLY, YEARLY)")
    return out


def build(d):
    order = ["FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYWEEKNO", "COUNT", "UNTIL", "WKST"]
    return ";".join(f"{k}={d[k]}" for k in order if d.get(k))


def _byday(v):
    out = []
    for tok in (v or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        n, day = tok[:-2], tok[-2:]
        out.append((int(n) if n not in ("", "+") else None, DAYS.index(day)))
    return out


def _until(v):
    if not v:
        return None
    v = v.rstrip("Z")
    if "T" in v:
        u = dt.datetime.strptime(v, "%Y%m%dT%H%M%S")
        if (v + "Z").endswith("Z"):
            u = u.replace(tzinfo=dt.timezone.utc).astimezone(TZ).replace(tzinfo=None)
        return u
    return dt.datetime.strptime(v, "%Y%m%d").replace(hour=23, minute=59, second=59)


def _nth_weekdays(year, month, specs):
    """Tage eines Monats zu BYDAY-Angaben (mit/ohne Ordinalzahl)."""
    n_days = calendar.monthrange(year, month)[1]
    days = [dt.date(year, month, i) for i in range(1, n_days + 1)]
    out = set()
    for n, wd in specs:
        hits = [d for d in days if d.weekday() == wd]
        if n is None:
            out.update(hits)
        elif -len(hits) <= n <= len(hits) and n != 0:
            out.add(hits[n - 1] if n > 0 else hits[n])
    return out


def expand(rule, start, range_start, range_end, exdates=(), limit=2000):
    """Beginnzeiten (naive Ortszeit, gleiche Uhrzeit wie start) einer Serie im Bereich [range_start, range_end).
    start/range_*: naive datetime (Ortszeit). exdates: naive datetimes oder dates."""
    r = parse(rule)
    freq = r["FREQ"]
    interval = max(1, int(r.get("INTERVAL", 1)))
    count = int(r["COUNT"]) if r.get("COUNT") else None
    until = _until(r.get("UNTIL"))
    byday = _byday(r.get("BYDAY"))
    bymd = [int(x) for x in r.get("BYMONTHDAY", "").split(",") if x]
    bymonth = [int(x) for x in r.get("BYMONTH", "").split(",") if x]
    byweekno = [int(x) for x in r.get("BYWEEKNO", "").split(",") if x]
    ex = set()
    for e in exdates:
        ex.add(e.date() if isinstance(e, dt.datetime) else e)
    t = start.time()
    out, n = [], 0

    def emit(d):
        nonlocal n
        when = dt.datetime.combine(d, t)
        if when < start:
            return True
        if until and when > until:
            return False
        if count is not None and n >= count:
            return False
        n += 1
        if d not in ex and range_start <= when < range_end:
            out.append(when)
        return when < range_end

    d0 = start.date()
    guard = 0
    if freq == "DAILY":
        d = d0
        while guard < 100000:
            guard += 1
            if (not bymonth or d.month in bymonth) and (not byday or d.weekday() in [w for _, w in byday]):
                if not emit(d):
                    break
            d += dt.timedelta(days=interval)
            if len(out) >= limit:
                break
    elif freq == "WEEKLY":
        days = sorted({w for _, w in byday}) or [d0.weekday()]
        wk = d0 - dt.timedelta(days=d0.weekday())
        stop = False
        while guard < 20000 and not stop:
            guard += 1
            for wd in days:
                d = wk + dt.timedelta(days=wd)
                if bymonth and d.month not in bymonth:
                    continue
                if not emit(d):
                    stop = True
                    break
            wk += dt.timedelta(weeks=interval)
            if len(out) >= limit:
                break
    elif freq == "MONTHLY":
        y, m = d0.year, d0.month
        stop = False
        while guard < 5000 and not stop:
            guard += 1
            if not bymonth or m in bymonth:
                if byday:
                    cands = sorted(_nth_weekdays(y, m, byday))
                elif bymd:
                    nd = calendar.monthrange(y, m)[1]
                    cands = sorted({dt.date(y, m, x if x > 0 else nd + x + 1) for x in bymd if 1 <= abs(x) <= nd})
                else:
                    cands = [dt.date(y, m, d0.day)] if d0.day <= calendar.monthrange(y, m)[1] else []
                for d in cands:
                    if not emit(d):
                        stop = True
                        break
            m += interval
            while m > 12:
                m -= 12
                y += 1
            if len(out) >= limit:
                break
    else:  # YEARLY
        y = d0.year
        stop = False
        while guard < 500 and not stop:
            guard += 1
            cands = set()
            if byweekno:
                wds = [w for _, w in byday] or [d0.weekday()]
                for wn in byweekno:
                    for wd in wds:
                        try:
                            d = dt.date.fromisocalendar(y, wn, wd + 1)
                        except ValueError:
                            continue
                        cands.add(d)
            elif byday and bymonth:
                for mo in bymonth:
                    cands |= _nth_weekdays(y, mo, byday)
            elif bymd or bymonth:
                for mo in bymonth or [d0.month]:
                    for x in bymd or [d0.day]:
                        try:
                            cands.add(dt.date(y, mo, x))
                        except ValueError:
                            pass
            else:
                try:
                    cands.add(d0.replace(year=y))
                except ValueError:
                    pass
            for d in sorted(cands):
                if not emit(d):
                    stop = True
                    break
            y += interval
            if len(out) >= limit:
                break
    return out


def describe(rule, start=None):
    """Kurzbeschreibung auf Deutsch, z. B. 'alle 2 Wochen am Mi (ungerade KW) bis 31.01.2027'."""
    if not rule:
        return "einmalig"
    try:
        r = parse(rule)
    except ValueError as e:
        return f"ungültig: {e}"
    iv = int(r.get("INTERVAL", 1))
    days = _byday(r.get("BYDAY"))
    dnames = ", ".join((f"{n}. " if n and n > 0 else "letzten " if n == -1 else "") + WEEKDAYS[w] for n, w in days)
    f = r["FREQ"]
    if f == "DAILY":
        s = "täglich" if iv == 1 else f"alle {iv} Tage"
    elif f == "WEEKLY":
        s = "wöchentlich" if iv == 1 else f"alle {iv} Wochen"
        dn = dnames or (WEEKDAYS[start.weekday()] if start else "")
        if dn:
            s += f" am {dn}"
        if iv == 2 and start:
            s += f" ({'gerade' if start.isocalendar()[1] % 2 == 0 else 'ungerade'} KW)"
    elif f == "MONTHLY":
        s = "monatlich" if iv == 1 else f"alle {iv} Monate"
        if days:
            s += f" am {dnames}"
        elif r.get("BYMONTHDAY"):
            s += f" am {r['BYMONTHDAY']}."
        elif start:
            s += f" am {start.day}."
    else:
        s = "jährlich" if iv == 1 else f"alle {iv} Jahre"
        if r.get("BYWEEKNO"):
            wn = r["BYWEEKNO"].split(",")
            nums = [int(x) for x in wn]
            if len(nums) > 20 and all(x % 2 == 0 for x in nums):
                s = "in geraden KW"
            elif len(nums) > 20 and all(x % 2 == 1 for x in nums):
                s = "in ungeraden KW"
            else:
                s += f" in KW {r['BYWEEKNO']}"
            if dnames:
                s += f" am {dnames}"
    if r.get("COUNT"):
        s += f", {r['COUNT']}×"
    if r.get("UNTIL"):
        u = _until(r["UNTIL"])
        s += f" bis {u:%d.%m.%Y}"
    return s


PRESETS = [  # (id, Anzeige) – Regel wird mit dem Starttag gebaut (preset_rule)
    ("none", "keine"), ("daily", "täglich"), ("weekly", "wöchentlich"),
    ("even", "alle 2 Wochen · gerade KW"), ("odd", "alle 2 Wochen · ungerade KW"),
    ("kweven", "jede gerade KW (exakt, über Jahreswechsel)"), ("kwodd", "jede ungerade KW (exakt)"),
    ("monthly", "monatlich (gleicher Tag)"), ("monthly_nth", "monatlich (z. B. 2. Mi)"),
    ("yearly", "jährlich"), ("custom", "benutzerdefiniert …"),
]


def preset_rule(pid, start, until=None, count=None):
    """Regel zu einer Vorauswahl. Bei gerade/ungerade wird ggf. der Starttag in die passende Woche gelegt;
    Rückgabe: (rule, start)."""
    wd = DAYS[start.weekday()]
    r = None
    if pid == "daily":
        r = {"FREQ": "DAILY"}
    elif pid == "weekly":
        r = {"FREQ": "WEEKLY", "BYDAY": wd}
    elif pid in ("even", "odd"):
        want = 0 if pid == "even" else 1
        if start.isocalendar()[1] % 2 != want:
            start += dt.timedelta(weeks=1)
        r = {"FREQ": "WEEKLY", "INTERVAL": "2", "BYDAY": wd}
    elif pid in ("kweven", "kwodd"):
        want = 0 if pid == "kweven" else 1
        if start.isocalendar()[1] % 2 != want:      # Serienbeginn muss selbst ein Treffer sein
            start += dt.timedelta(weeks=1)
        r = {"FREQ": "YEARLY", "BYWEEKNO": ",".join(str(i) for i in range(1, 54) if i % 2 == want), "BYDAY": wd}
    elif pid == "monthly":
        r = {"FREQ": "MONTHLY", "BYMONTHDAY": str(start.day)}
    elif pid == "monthly_nth":
        n = (start.day - 1) // 7 + 1
        r = {"FREQ": "MONTHLY", "BYDAY": f"{n if n < 5 else -1}{wd}"}
    elif pid == "yearly":
        r = {"FREQ": "YEARLY"}
    if r is None:
        return None, start
    if until:
        r["UNTIL"] = until.strftime("%Y%m%d") + "T225959Z"
    elif count:
        r["COUNT"] = str(count)
    return build(r), start


def preset_of(rule, start):
    """Welche Vorauswahl passt zu einer bestehenden Regel (für den Editor)."""
    if not rule:
        return "none"
    try:
        r = parse(rule)
    except ValueError:
        return "custom"
    base = {k: v for k, v in r.items() if k not in ("UNTIL", "COUNT", "WKST")}
    wd = DAYS[start.weekday()]
    iv = base.pop("INTERVAL", "1")
    f = base.get("FREQ")
    if f == "DAILY" and iv == "1" and len(base) == 1:
        return "daily"
    if f == "WEEKLY" and base.get("BYDAY", wd) == wd and set(base) <= {"FREQ", "BYDAY"}:
        if iv == "1":
            return "weekly"
        if iv == "2":
            return "even" if start.isocalendar()[1] % 2 == 0 else "odd"
    if f == "YEARLY" and base.get("BYWEEKNO") and base.get("BYDAY") == wd:
        nums = [int(x) for x in base["BYWEEKNO"].split(",")]
        if nums == [i for i in range(1, 54) if i % 2 == 0]:
            return "kweven"
        if nums == [i for i in range(1, 54) if i % 2 == 1]:
            return "kwodd"
    if f == "MONTHLY" and iv == "1" and base.get("BYMONTHDAY") == str(start.day) and len(base) == 2:
        return "monthly"
    if f == "MONTHLY" and iv == "1" and base.get("BYDAY", "").endswith(wd) and len(base) == 2:
        return "monthly_nth"
    if f == "YEARLY" and iv == "1" and len(base) == 1:
        return "yearly"
    return "custom"


def until_of(rule):
    try:
        return _until(parse(rule).get("UNTIL"))
    except ValueError:
        return None
