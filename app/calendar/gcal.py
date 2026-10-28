# Google-Kalender: Anmeldung (OAuth 2.0 für Desktop-Apps, PKCE, Rückleitung an 127.0.0.1) und Abgleich
# über die Calendar-REST-API – ohne Fremdbibliotheken (urllib).
#
# Einrichtung (einmalig, siehe Konto-Tab): eigener OAuth-Client "Desktop-App" in der Google Cloud Console,
# JSON herunterladen → in der App laden (liegt dann in ~/.config/kalender/client_secret.json).
# Das Token liegt in ~/.local/share/kalender/auth/token.json (nur für dich lesbar, nicht im rice-Backup).
import base64, datetime as dt, hashlib, http.server, json, os, secrets, socket, threading, time
import urllib.error, urllib.parse, urllib.request

from raster import TZ, TZ_NAME, guess_cat
import store as st

CONFIG = os.path.expanduser("~/.config/kalender")
CLIENT = os.path.join(CONFIG, "client_secret.json")
AUTH_DIR = os.path.expanduser("~/.local/share/kalender/auth")
TOKEN = os.path.join(AUTH_DIR, "token.json")
MAIN = "main"            # das Hauptkonto (Token wie bisher in token.json); weitere Konten: token-<id>.json
SCOPE = "https://www.googleapis.com/auth/calendar"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
TASKS_API = os.environ.get("TASKS_API_BASE", "https://tasks.googleapis.com/tasks/v1")


def has_tasks_scope(acct=MAIN):
    t = token(acct)
    return bool(t and TASKS_SCOPE in (t.get("scope") or ""))
LOGIN_HINT_FILE = os.path.join(CONFIG, "login_hint")   # optional, lokal: Google-Konto vorauswählen


def login_hint():
    """Mail-Adresse, die Google bei der Anmeldung vorschlägt – steht nur lokal, nie im Code."""
    try:
        with open(LOGIN_HINT_FILE, encoding="utf-8") as f:
            return f.readline().strip() or None
    except OSError:
        return None
API = os.environ.get("CAL_API_BASE", "https://www.googleapis.com/calendar/v3")
AUTH_URL = os.environ.get("CAL_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
TOKEN_URL = os.environ.get("CAL_TOKEN_URL", "https://oauth2.googleapis.com/token")
LINK_PREFIX = "Link: "


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(f"{status}: {msg}")
        self.status = status


class AuthError(Exception):
    pass


class ExpiredError(AuthError):
    """Google nimmt das Refresh-Token nicht mehr an (Testmodus: nach 7 Tagen, oder Zugriff widerrufen)."""


# ---------------------------------------------------------------- Client & Token
def client():
    try:
        with open(CLIENT) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    c = d.get("installed") or d.get("web") or d
    return c if c.get("client_id") else None


def install_client(path):
    """Heruntergeladene client_secret_….json übernehmen (prüft das Format)."""
    with open(path) as f:
        d = json.load(f)
    c = d.get("installed") or d.get("web")
    if not c or not c.get("client_id"):
        raise ValueError("Keine OAuth-Client-Datei (\"installed\".client_id fehlt)")
    if "web" in d and "installed" not in d:
        raise ValueError("Das ist ein Web-Client – bitte als Typ „Desktop-App“ anlegen")
    os.makedirs(CONFIG, exist_ok=True)
    with open(CLIENT, "w") as f:
        json.dump(d, f)
    os.chmod(CLIENT, 0o600)


def install_client_manual(client_id, secret):
    """Client-ID und Schlüssel aus der Konsole kopiert (falls kein JSON-Download)."""
    client_id, secret = client_id.strip(), secret.strip()
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise ValueError("Client-ID sieht nicht richtig aus (endet auf .apps.googleusercontent.com)")
    if len(secret) < 10:
        raise ValueError("Clientschlüssel fehlt")
    d = {"installed": {"client_id": client_id, "client_secret": secret,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}
    os.makedirs(CONFIG, exist_ok=True)
    fd = os.open(CLIENT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)


def token_path(acct=MAIN):
    return TOKEN if acct == MAIN else os.path.join(AUTH_DIR, f"token-{acct}.json")


def token(acct=MAIN):
    try:
        with open(token_path(acct)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_token(t, acct=MAIN):
    os.makedirs(AUTH_DIR, exist_ok=True)
    os.chmod(AUTH_DIR, 0o700)
    path = token_path(acct)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(t, f)
    os.replace(tmp, path)


def accounts():
    """IDs aller angemeldeten Konten (mit Token-Datei), Hauptkonto zuerst."""
    out = []
    if token(MAIN) and token(MAIN).get("refresh_token"):
        out.append(MAIN)
    try:
        names = sorted(os.listdir(AUTH_DIR))
    except OSError:
        names = []
    for n in names:
        if n.startswith("token-") and n.endswith(".json"):
            a = n[6:-5]
            t = token(a)
            if a and t and t.get("refresh_token"):
                out.append(a)
    return out


def expired(acct=None):
    """acct=None: ist irgendein angemeldetes Konto abgelaufen?"""
    if acct is None:
        return any(expired(a) for a in accounts())
    t = token(acct)
    return bool(t and t.get("expired"))


def expired_accounts():
    return [a for a in accounts() if expired(a)]


def active_accounts():
    """Angemeldet und nicht abgelaufen – nur mit diesen wird abgeglichen."""
    return [a for a in accounts() if not expired(a)]


def signed_in_at(acct=MAIN):
    t = token(acct)
    return t.get("created") if t else None


TEST_DAYS = 7           # Google-Testmodus: das Anmelde-Token läuft nach 7 Tagen ab


def seconds_left(acct=MAIN):
    """Sekunden bis das Token im Testmodus abläuft (negativ: schon abgelaufen), None wenn nicht angemeldet."""
    c = signed_in_at(acct)
    return None if not c else TEST_DAYS * 86400 - (time.time() - c)


def logged_in(acct=None):
    """acct=None: ist irgendein Konto angemeldet?"""
    if acct is None:
        return bool(accounts())
    t = token(acct)
    return bool(t and t.get("refresh_token"))


def logout(acct=MAIN):
    t = token(acct)
    if t and t.get("refresh_token"):
        try:  # Zugriff bei Google widerrufen (best effort)
            urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/revoke", data=urllib.parse.urlencode(
                    {"token": t["refresh_token"]}).encode()), timeout=8)
        except (urllib.error.URLError, OSError):
            pass
    try:
        os.remove(token_path(acct))
    except OSError:
        pass


def _post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        if body.get("error") == "invalid_grant":
            raise ExpiredError("Anmeldung abgelaufen") from None
        raise AuthError(body.get("error_description") or body.get("error") or f"HTTP {e.code}") from None


def access_token(acct=MAIN):
    t = token(acct)
    if not t or not t.get("refresh_token"):
        raise AuthError("nicht angemeldet")
    if t.get("access_token") and t.get("expires_at", 0) > time.time() + 60:
        return t["access_token"]
    c = client()
    if not c:
        raise AuthError("OAuth-Client fehlt (client_secret.json)")
    try:
        res = _post_form(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                     "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    except ExpiredError:
        t["expired"] = True                  # merken, damit die App es auch nach einem Neustart weiß
        t.pop("access_token", None)
        save_token(t, acct)
        raise
    t["access_token"] = res["access_token"]
    t["expires_at"] = time.time() + int(res.get("expires_in", 3600))
    save_token(t, acct)
    return t["access_token"]


# ---------------------------------------------------------------- Anmeldung im Browser
class Login:
    """Startet einen kleinen Server auf 127.0.0.1, öffnet die Google-Anmeldung im Standardbrowser (Zen)
    und tauscht den zurückkommenden Code gegen ein Token. run() blockiert → im Thread aufrufen."""

    def __init__(self, open_url, acct=MAIN, tasks=False):
        self.open_url = open_url
        self.acct = acct
        self.tasks = tasks              # zusätzlich die Aufgaben-Berechtigung (Google Tasks) verlangen
        self.cancelled = False

    def run(self, timeout=300):
        c = client()
        if not c:
            raise AuthError("Erst die OAuth-Client-Datei laden (Konto-Tab, Schritt 1)")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        result = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if "state" not in q and "error" not in q:
                    self.send_response(404)
                    self.end_headers()
                    return
                result.update({k: v[0] for k, v in q.items()})
                ok = q.get("state", [""])[0] == state and "code" in q
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "Angemeldet – du kannst den Tab schließen." if ok else "Anmeldung abgebrochen."
                self.wfile.write(
                    f"<html><body style='background:#111;color:#ddd;font:16px monospace;padding:3em'>"
                    f"<pre>┌──────────────────────────────────────────┐\n│ datist · {msg:<30}│\n"
                    f"└──────────────────────────────────────────┘</pre></body></html>".encode())

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        srv.timeout = 1
        port = srv.server_address[1]
        redirect = f"http://127.0.0.1:{port}"
        params = {"client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
                  "scope": SCOPE + (" " + TASKS_SCOPE if self.tasks or has_tasks_scope(self.acct) else ""),
                  "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
                  "access_type": "offline", "prompt": "consent"}
        hint = login_hint()
        if hint:
            params["login_hint"] = hint
        self.open_url(AUTH_URL + "?" + urllib.parse.urlencode(params))
        end = time.time() + timeout
        try:
            while not result and time.time() < end and not self.cancelled:
                srv.handle_request()
        finally:
            srv.server_close()
        if self.cancelled:
            raise AuthError("abgebrochen")
        if not result:
            raise AuthError("Zeitüberschreitung – keine Antwort vom Browser")
        if result.get("error") == "access_denied":
            raise AuthError("Google hat den Zugriff verweigert – entweder abgebrochen, oder dein Konto ist nicht als "
                            "Testnutzer eingetragen (Google Auth Platform → Zielgruppe → Testnutzer)")
        if result.get("error"):
            raise AuthError(f"Google meldet: {result['error']}")
        if result.get("state") != state:
            raise AuthError("Antwort passt nicht zur Anfrage (state)")
        res = _post_form(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                     "code": result["code"], "code_verifier": verifier,
                                     "redirect_uri": redirect, "grant_type": "authorization_code"})
        if not res.get("refresh_token"):
            raise AuthError("Google hat kein Refresh-Token geschickt – Zugriff unter "
                            "myaccount.google.com/permissions entfernen und erneut anmelden")
        save_token({"refresh_token": res["refresh_token"], "access_token": res["access_token"], "created": time.time(),
                    "expires_at": time.time() + int(res.get("expires_in", 3600)), "scope": res.get("scope")}, self.acct)
        return True


# ---------------------------------------------------------------- REST
def call(method, path, params=None, body=None, acct=MAIN, base=None):
    url = (base or API) + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {access_token(acct)}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                msg = ""
            if e.code == 401 and attempt == 0:
                t = token(acct) or {}
                t.pop("access_token", None)
                save_token(t, acct)
                continue
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ApiError(e.code, msg or e.reason) from None
    raise ApiError(0, "keine Antwort")


def _write_params(op):
    """Schreib-Parameter: Einladungen nur, wenn der Nutzer es für diesen Speichervorgang wollte (sonst keine Mail);
    Meet-Konferenz nur beim Anlegen."""
    p = {"sendUpdates": "all" if op.get("send") else "none"}
    if (op.get("event") or {}).get("meet_create"):
        p["conferenceDataVersion"] = 1
    return p


def online(host="www.googleapis.com"):
    if API.startswith("http://127.0.0.1") or API.startswith("http://localhost"):
        return True
    try:
        socket.create_connection((host, 443), timeout=3).close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- Umwandeln
def to_google(ev):
    notes = ev.get("notes") or ""
    if ev.get("link"):
        notes = (notes.rstrip() + "\n\n" if notes.strip() else "") + LINK_PREFIX + ev["link"]
    body = {"summary": ev.get("title") or "(ohne Titel)", "location": ev.get("location") or "",
            "description": notes,
            "extendedProperties": {"private": {"cat": ev.get("cat") or "", "tone": ev.get("tone") or "",
                                               "link": ev.get("link") or "",
                                               "remind": "" if ev.get("remind") is None else str(int(ev["remind"])),
                                               "sem": json.dumps(ev["sem"]) if ev.get("sem") else ""}}}
    if ev.get("gcolor"):                    # Farbe im Google-Kalender (nächste der 11 Google-Farben)
        body["colorId"] = ev["gcolor"]
    if ev.get("allday"):
        body["start"], body["end"] = {"date": ev["start"][:10]}, {"date": ev["end"][:10]}
    else:
        zone = ev.get("tz") or TZ_NAME                  # eigene Zeitzone des Termins, sonst die lokale
        body["start"] = {"dateTime": ev["start"], "timeZone": zone}
        body["end"] = {"dateTime": ev["end"], "timeZone": zone}
    if ev.get("attendees_edit"):                        # Gäste nur senden, wenn sie im Editor geändert wurden
        body["attendees"] = [{k: v for k, v in (("email", a.get("email")), ("displayName", a.get("name")),
                                                  ("responseStatus", a.get("status")), ("optional", a.get("optional")))
                              if v} for a in ev.get("attendees") or [] if a.get("email")]
    if ev.get("meet_create"):
        body["conferenceData"] = {"createRequest": {"requestId": secrets.token_hex(8),
                                                    "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
    if ev.get("rrule") is not None:
        body["recurrence"] = ["RRULE:" + ev["rrule"]] if ev.get("rrule") else []
        if ev.get("rrule") and ev.get("exdates"):
            timed = [x for x in ev["exdates"] if len(x) > 10]
            days = [x for x in ev["exdates"] if len(x) == 10]
            if timed and not ev.get("allday"):
                body["recurrence"] += ["EXDATE;TZID=" + TZ_NAME + ":" +
                                       ",".join(st.parse_when(x, False).strftime("%Y%m%dT%H%M%S") for x in timed)]
            if days and ev.get("allday"):
                body["recurrence"] += ["EXDATE;VALUE=DATE:" + ",".join(x.replace("-", "") for x in days)]
    return body


def from_google(g, cal, acct=MAIN):
    priv = (g.get("extendedProperties") or {}).get("private") or {}
    desc = g.get("description") or ""
    link = priv.get("link") or ""
    lines = desc.rstrip().split("\n")
    if lines and lines[-1].startswith(LINK_PREFIX):
        link = link or lines[-1][len(LINK_PREFIX):].strip()
        desc = "\n".join(lines[:-1]).rstrip()
    allday = "date" in g.get("start", {})
    s = g["start"].get("date") or g["start"].get("dateTime")
    e = g["end"].get("date") or g["end"].get("dateTime")
    title = g.get("summary") or "(ohne Titel)"
    try:
        remind = int(priv["remind"]) if priv.get("remind") not in (None, "") else None
    except (ValueError, TypeError):
        remind = None
    att = [{"email": a.get("email") or "", "name": a.get("displayName") or "", "status": a.get("responseStatus") or "",
            "self": bool(a.get("self")), "organizer": bool(a.get("organizer")), "optional": bool(a.get("optional"))}
           for a in (g.get("attendees") or [])[:100] if a.get("email")]
    meet = g.get("hangoutLink") or ""
    if not meet:
        for ep in (g.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video" and ep.get("uri"):
                meet = ep["uri"]
                break
    tz = None if allday else (g["start"].get("timeZone") or None)
    if tz == TZ_NAME:
        tz = None
    org = g.get("organizer") or {}
    organizer_self = bool(org.get("self")) or not att        # ohne Gäste: eigener Termin
    return {"uid": g["id"] if acct == MAIN else f"{acct}:{g['id']}", "gid": g["id"], "cal": cal, "acct": acct,
            "series": g.get("recurringEventId"), "attendees": att, "meet": meet, "tz": tz, "organizer_self": organizer_self,
            "title": title, "start": s, "end": e, "allday": allday, "location": g.get("location") or "",
            "link": link, "notes": desc, "cat": priv.get("cat") or guess_cat(title), "tone": priv.get("tone") or "",
            "rrule": None, "status": g.get("status"), "html": g.get("htmlLink"), "updated": g.get("updated"),
            "sem": _sem(priv.get("sem")), "color_id": g.get("colorId"), "dmeta": bool(priv.get("cat")),
            "remind": remind}


def _sem(v):
    try:
        return json.loads(v) if v else None
    except ValueError:
        return None


def _exdates(line):
    """EXDATE;TZID=Europe/Berlin:20261031T091000,… / EXDATE;VALUE=DATE:20261031 / …Z → ISO wie im Store."""
    head, _, vals = line.partition(":")
    out = []
    for v in vals.split(","):
        v = v.strip()
        try:
            if "T" not in v:
                out.append(dt.datetime.strptime(v, "%Y%m%d").date().isoformat())
                continue
            d = dt.datetime.strptime(v.rstrip("Z"), "%Y%m%dT%H%M%S")
            if v.endswith("Z"):
                d = d.replace(tzinfo=dt.timezone.utc)
            out.append(st.iso(d))
        except ValueError:
            pass
    return out


def master(cal, gid, acct=MAIN):
    """Serie (Original-Termin) holen – für 'ganze Serie bearbeiten'."""
    g = call("GET", f"/calendars/{urllib.parse.quote(cal)}/events/{urllib.parse.quote(gid)}", acct=acct)
    ev = from_google(g, cal, acct)
    ev["exdates"] = []
    for line in g.get("recurrence", []):
        if line.startswith("RRULE:"):
            ev["rrule"] = line[6:]
        elif line.startswith("EXDATE"):                 # ausgelassene Termine nicht verlieren
            ev["exdates"] += _exdates(line)
    return ev


# ---------------------------------------------------------------- Abgleich
# ---------------------------------------------------------------- Aufgaben (Google Tasks, nur Hauptkonto)
def _task_in(t, lid):
    due = (t.get("due") or "")[:10] or None
    return {"id": t["id"], "list": lid, "title": t.get("title") or "(ohne Titel)", "notes": t.get("notes") or "",
            "due": due, "done": t.get("status") == "completed", "updated": t.get("updated"), "parent": t.get("parent")}


def tasks_fetch(acct=MAIN):
    """Alle Listen und Aufgaben (auch erledigte) → {"lists": [{id, title}], "items": {id: Aufgabe}}."""
    lists, items = [], {}
    page = None
    while True:
        r = call("GET", "/users/@me/lists", {"pageToken": page} if page else None, acct=acct, base=TASKS_API)
        lists += [{"id": x["id"], "title": x.get("title") or "Aufgaben"} for x in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            break
    for lst in lists:
        page = None
        while True:
            params = {"showCompleted": "true", "showHidden": "true", "maxResults": 100}
            if page:
                params["pageToken"] = page
            r = call("GET", f"/lists/{urllib.parse.quote(lst['id'])}/tasks", params, acct=acct, base=TASKS_API)
            for t in r.get("items", []):
                items[t["id"]] = _task_in(t, lst["id"])
            page = r.get("nextPageToken")
            if not page:
                break
    return {"lists": lists, "items": items}


def _task_body(task):
    b = {}
    if "title" in task:
        b["title"] = task["title"]
    if "notes" in task:
        b["notes"] = task["notes"] or ""
    if "due" in task:
        b["due"] = (task["due"] + "T00:00:00.000Z") if task["due"] else None
    if "done" in task:
        b["status"] = "completed" if task["done"] else "needsAction"
        if not task["done"]:
            b["completed"] = None
    return b


def tasks_apply(ops, acct=MAIN):
    """Offene Aufgaben-Änderungen hochladen → (erledigte Auftrags-IDs, Fehlertexte). Bricht bei Netzfehlern ab."""
    done, errors = [], []
    for op in ops:
        lid = urllib.parse.quote(op["list"])
        try:
            if op["op"] == "task_create":
                call("POST", f"/lists/{lid}/tasks", body=_task_body(op["task"]), acct=acct, base=TASKS_API)
            elif op["op"] == "task_update":
                call("PATCH", f"/lists/{lid}/tasks/{urllib.parse.quote(op['tid'])}", body=_task_body(op["task"]),
                     acct=acct, base=TASKS_API)
            elif op["op"] == "task_delete":
                try:
                    call("DELETE", f"/lists/{lid}/tasks/{urllib.parse.quote(op['tid'])}", acct=acct, base=TASKS_API)
                except ApiError as e:
                    if e.status not in (404, 410):
                        raise
            done.append(op["id"])
        except AuthError:
            raise
        except ApiError as e:
            if e.status == 404:                                   # Liste/Aufgabe gibt es nicht mehr
                done.append(op["id"])
            elif e.status == 403:
                errors.append("Aufgaben: Google lehnt ab – Tasks API im Cloud-Projekt aktiviert? Berechtigung erteilt?")
                break
            else:
                errors.append(f"Aufgaben: {e} – später erneut")
                break
    return done, errors


def sync(pending, window, names=None, tasks=False):
    """Läuft im Hintergrund. pending: Kopie der Warteschlange. names: {Konto-ID: Anzeigename}. Gleicht jedes
    angemeldete, nicht abgelaufene Konto einzeln ab. Rückgabe für Store.apply_sync().
    Ist das einzige Konto abgelaufen, wird ExpiredError geworfen (wie bisher); sind es nur einige, kommen die
    übrigen durch und res["expired"] nennt die abgelaufenen (ihre Aufträge bleiben in der Warteschlange)."""
    res = {"done": [], "errors": [], "calendars": [], "events": {}, "fetched": [], "expired": [], "skipped": []}
    if not online():
        res["offline"] = True
        return res
    if tasks and has_tasks_scope(MAIN) and MAIN in accounts() and not expired(MAIN):   # Aufgaben (nur Hauptkonto)
        try:
            tdone, terrs = tasks_apply([op for op in pending if op["op"].startswith("task_")])
            res["done"] += tdone
            res["errors"] += terrs
            if not terrs:
                res["tasks"] = tasks_fetch()
        except AuthError:
            pass                                            # das meldet gleich der Kalender-Abgleich
        except ApiError as e:
            res["errors"].append("Aufgaben: Google lehnt ab – Tasks API im Cloud-Projekt aktiviert?" if e.status == 403
                                 else f"Aufgaben: {e}")
        except (urllib.error.URLError, OSError):
            pass
    names = names or {}
    accts = accounts()
    first_exc = None
    ok_accts = []
    seen_cals = set()
    for acct in accts:
        if expired(acct):
            res["expired"].append(acct)
            res["skipped"].append(acct)
            continue
        ops = [op for op in pending if op.get("acct", MAIN) == acct and not op["op"].startswith("task_")]
        try:
            part = _sync_acct(acct, ops, window, names.get(acct), seen_cals)
        except ExpiredError as e:
            res["expired"].append(acct)
            res["skipped"].append(acct)
            first_exc = first_exc or e
            continue
        except AuthError as e:
            res["errors"].append(f"Konto {names.get(acct) or acct}: {e}")
            res["skipped"].append(acct)
            first_exc = first_exc or e
            continue
        ok_accts.append(acct)
        res["done"] += part["done"]
        res["errors"] += part["errors"]
        res["calendars"] += part.get("calendars", [])
        res["events"].update(part.get("events", {}))
        res["fetched"] += part.get("fetched", [])
        if part.get("offline"):
            res["offline"] = True
            return _finish(res)
        if part.get("window"):
            res["window"] = part["window"]
    # Aufträge für Konten, die es nicht mehr gibt: nicht ewig mitschleppen
    for op in pending:
        a = op.get("acct", MAIN)
        if op["op"].startswith("task_"):
            continue
        if a not in accts:
            res["done"].append(op["id"])
            res["errors"].append("Änderung für ein entferntes Konto verworfen")
    if not ok_accts and first_exc is not None:
        raise first_exc
    if ok_accts:
        res["events_ok"] = True
    return _finish(res)


def _finish(res):
    """Ohne einen einzigen erfolgreichen Abgleich dürfen Kalender/Termine nicht „leer“ übernommen werden."""
    if not res.pop("events_ok", False):
        for k in ("calendars", "events", "fetched"):
            res.pop(k, None)
    return res


def _cal_name(c, acct, label):
    name = c.get("summaryOverride") or c.get("summary") or c["id"]
    if acct == MAIN:
        if c.get("primary"):
            return "Hauptkalender"
        return "Google-Kalender" if "@" in name else name        # Konto-/Gruppenadressen nicht anzeigen
    label = label or "Konto"
    if c.get("primary") or "@" in name:
        return label if c.get("primary") else f"{label} · Kalender"
    return f"{label} · {name}"


def _sync_acct(acct, pending, window, label, seen_cals):
    """Ein Konto: eigene Änderungen hochladen, dann Kalender und Termine holen."""
    res = {"done": [], "errors": [], "calendars": [], "events": {}, "fetched": []}
    # 1) eigene Änderungen hochladen
    for op in pending:
        cal = urllib.parse.quote(op["cal"])
        try:
            if op["op"] == "create":
                call("POST", f"/calendars/{cal}/events", body=to_google(op["event"]), params=_write_params(op), acct=acct)
            elif op["op"] == "update":
                body = to_google(op["event"])
                if op.get("scope") == "instance":
                    body.pop("recurrence", None)
                call("PATCH", f"/calendars/{cal}/events/{urllib.parse.quote(op['gid'])}", body=body,
                     params=_write_params(op), acct=acct)
            elif op["op"] == "color":                     # nur die Farbe im Google-Kalender anpassen
                call("PATCH", f"/calendars/{cal}/events/{urllib.parse.quote(op['gid'])}",
                     body={"colorId": op["colorId"]}, acct=acct)
            elif op["op"] == "delete":
                try:
                    call("DELETE", f"/calendars/{cal}/events/{urllib.parse.quote(op['gid'])}", acct=acct)
                except ApiError as e:
                    if e.status not in (404, 410):       # schon weg – passt
                        raise
            res["done"].append(op["id"])
        except AuthError:
            raise
        except ApiError as e:
            title = (op.get("event") or {}).get("title", "")
            if e.status in (400, 403, 404):              # dauerhaft abgelehnt: nicht ewig wiederholen
                res["done"].append(op["id"])
                res["errors"].append(f"„{title}“ von Google abgelehnt ({e})")
            else:
                res["errors"].append(f"„{title}“: {e} – später erneut")
                break
        except (urllib.error.URLError, OSError) as e:
            res["errors"].append(f"Netzwerk: {e}")
            res["offline"] = True
            return res
    # 2) Kalender und Termine holen
    try:
        cals = []
        page = None
        while True:
            r = call("GET", "/users/me/calendarList", {"pageToken": page} if page else None, acct=acct)
            for c in r.get("items", []):
                if c["id"] in seen_cals:                  # derselbe Kalender über zwei Konten: nur einmal
                    continue
                seen_cals.add(c["id"])
                cals.append({"id": c["id"], "name": _cal_name(c, acct, label), "acct": acct,
                             "color": c.get("backgroundColor"), "role": c.get("accessRole"),
                             "primary": bool(c.get("primary")), "selected": bool(c.get("selected", True))})
            page = r.get("nextPageToken")
            if not page:
                break
        res["calendars"] = cals
        a, b = window
        for c in cals:
            try:
                fetch_cal(c, a, b, res["events"], acct)
            except ApiError as e:
                res["errors"].append(f"Kalender {c['name']}: {e}")
                continue
            res["fetched"].append([acct, c["id"]])
        res["window"] = list(window)
    except (urllib.error.URLError, OSError) as e:
        res["errors"].append(f"Netzwerk: {e}")
        res["offline"] = True
    return res


def fetch_cal(c, a, b, events, acct=MAIN):
    page = None
    while True:
        params = {"singleEvents": "true", "timeMin": a, "timeMax": b, "maxResults": 2500, "orderBy": "startTime"}
        if page:
            params["pageToken"] = page
        r = call("GET", f"/calendars/{urllib.parse.quote(c['id'])}/events", params, acct=acct)
        for g in r.get("items", []):
            if g.get("status") == "cancelled" or "start" not in g:
                continue
            ev = from_google(g, c["id"], acct)
            events[ev["uid"]] = ev
        page = r.get("nextPageToken")
        if not page:
            return


def window_around(center, before=90, after=400):
    a = dt.datetime.combine(center - dt.timedelta(days=before), dt.time()).replace(tzinfo=TZ)
    b = dt.datetime.combine(center + dt.timedelta(days=after), dt.time()).replace(tzinfo=TZ)
    return a.isoformat(), b.isoformat()
