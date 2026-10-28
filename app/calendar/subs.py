# datist – ICS-Abos: Kalender-Links (z. B. Uni-Stundenplan, Feiertage) holen. Nur lesen, kein Konto.
# Die Adresse kann ein Geheimnis enthalten (private Links): sie wird nie angezeigt oder protokolliert, nur der Host.
import urllib.error, urllib.parse, urllib.request

import icsfile

MAX_BYTES = 15_000_000
EVERY_MINUTES = 30
UA = "datist (Kalender-Abo)"


def normalize(url):
    """webcal:// → https:// · nur http(s) erlaubt. Wirft ValueError."""
    u = (url or "").strip()
    if u.lower().startswith("webcals://"):
        u = "https://" + u[10:]
    elif u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Adresse muss mit https:// (oder webcal://) beginnen")
    return u


def host_of(url):
    try:
        return urllib.parse.urlparse(url).netloc or "?"
    except ValueError:
        return "?"


def fetch(url, etag=None, timeout=25):
    """(Text | None bei „unverändert“, neues ETag). Wirft RuntimeError mit verständlichem Text."""
    req = urllib.request.Request(normalize(url), headers={"User-Agent": UA, "Accept": "text/calendar, */*"})
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_BYTES + 1)
            new_etag = r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag
        raise RuntimeError(f"Server antwortet mit {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        raise RuntimeError("keine Verbindung" if isinstance(reason, OSError) else str(reason)[:80]) from None
    if len(data) > MAX_BYTES:
        raise RuntimeError("Datei zu groß (über 15 MB)")
    try:
        return data.decode("utf-8-sig"), new_etag
    except UnicodeDecodeError:
        return data.decode("latin-1"), new_etag


def refresh(sub, etag=None):
    """Abo holen und lesen → {"name", "events": {uid: Termin}, "etag", "unchanged"}."""
    text, new_etag = fetch(sub["url"], etag)
    if text is None:
        return {"unchanged": True, "etag": new_etag}
    cal = "ics:" + sub["id"]
    name, evs = icsfile.parse(text, uid_prefix=cal + ":")
    out = {}
    for ev in evs:
        ev["cal"] = cal
        out[ev["uid"]] = ev
    return {"unchanged": False, "name": name, "events": out, "etag": new_etag}
