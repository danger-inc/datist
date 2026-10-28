# datist – Teile des Konto-Fensters und Hintergrundaufgaben (Teil von Kalender, siehe ui.py):
# ICS-Abos (Liste, Abruf im Takt), ICS-Import/-Export und die Warnung vor dem Ablauf der Google-Anmeldung.
import datetime as dt, os, time

import gi
from gi.repository import Gio, GLib, Gtk

import tui
from tui import label, hbox, vbox

import barstate
import gcal
import icsfile
import reminders
import subs as subs_mod


def _wrap(*children, spacing=8):
    b = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=spacing, row_spacing=4,
                    max_children_per_line=12, homogeneous=False, halign=Gtk.Align.START, hexpand=True)
    for c in children:
        if c is not None:
            b.append(c)
    return b


class AcctMixin:
    # ================= Abos: Takt =================
    def start_background(self):
        """Nach dem Aufbau starten: Abos im Takt holen, Google-Ablauf beobachten."""
        self._sub_busy = set()
        GLib.timeout_add_seconds(300, lambda: (self.refresh_subs(), True)[1])
        GLib.timeout_add_seconds(6, lambda: (self.refresh_subs(), False)[1])
        GLib.timeout_add_seconds(600, lambda: (self.expiry_tick(), True)[1])
        GLib.timeout_add_seconds(8, lambda: (self.expiry_tick(), False)[1])

    def refresh_subs(self, force=False):
        st = self.store
        for sub in list(st.subs()):
            if sub["id"] in self._sub_busy or not (force or st.sub_due(sub)):
                continue
            self._sub_busy.add(sub["id"])
            etag = (st.ics.get(sub["id"]) or {}).get("etag")

            def done(res, sid=sub["id"]):
                self._sub_busy.discard(sid)
                if isinstance(res, Exception):
                    st.apply_ics(sid, None, error=str(res)[:90] or "Fehler")
                else:
                    st.apply_ics(sid, res)
                self.refresh_subs_panel()
            tui.background(lambda s=dict(sub), e=etag: subs_mod.refresh(s, e), done=done)
        self.refresh_subs_panel()

    # ================= Abos: Fenster =================
    def build_subs_panel(self):
        self.sub_panel = tui.Panel("kalender-abos (ics)")
        self.sub_list = vbox(spacing=2)
        self.sub_panel.body.append(self.sub_list)
        self.sub_name = tui.Entry("Name (optional)", width=16)
        self.sub_url = tui.Entry("https://… oder webcal://… (z. B. Stundenplan, Feiertage)", activate=self.add_sub_clicked)
        self.sub_msg = label("", "warn", wrap=True)
        self.sub_panel.body.append(_wrap(self.sub_name, self.sub_url, tui.Button("hinzufügen", self.add_sub_clicked)))
        self.sub_panel.body.append(label("nur lesen, wird alle 30 min aktualisiert (strg+r sofort). Die Adresse kann ein "
                                         "Geheimnis enthalten und wird deshalb nie angezeigt – nur der Server.",
                                         "dim", wrap=True))
        self.sub_panel.body.append(self.sub_msg)
        self.refresh_subs_panel()
        return self.sub_panel

    def refresh_subs_panel(self):
        box = getattr(self, "sub_list", None)
        if box is None:
            return
        tui.clear(box)
        subs = self.store.subs()
        if not subs:
            box.append(label("noch keine Abos", "dim"))
        for sub in subs:
            busy = sub["id"] in getattr(self, "_sub_busy", ())
            if busy:
                status = "⟳ lädt …"
            elif sub.get("error"):
                status = f"✗ {sub['error']}"
            elif sub.get("last"):
                status = f"✓ {dt.datetime.fromisoformat(sub['last']):%H:%M} · {sub.get('count', 0)} Termine"
            else:
                status = "○ noch nicht geladen"
            row = _wrap(label(sub.get("name") or "Abo", "accent"), label(subs_mod.host_of(sub["url"]), "dim"),
                        label(status, "warn" if sub.get("error") else "dim"),
                        tui.Button("jetzt", lambda sid=sub["id"]: self.sub_now(sid)),
                        tui.Button("entfernen", lambda sid=sub["id"]: self.sub_remove(sid), danger=True))
            box.append(row)

    def add_sub_clicked(self):
        try:
            sub = self.store.add_sub(self.sub_name.get_text(), self.sub_url.get_text())
        except ValueError as e:
            self.sub_msg.set_label(f"✗ {e}")
            return
        self.sub_msg.set_label("")
        self.sub_name.set_text("")
        self.sub_url.set_text("")
        self.refresh_subs(force=True)
        self.win.say(f"Abo „{sub['name']}“ hinzugefügt – lade …")
        self.refresh_account()

    def sub_now(self, sid):
        for s in self.store.subs():
            if s["id"] == sid:
                s["last"] = None
        self.refresh_subs(force=True)

    def sub_remove(self, sid):
        self.store.remove_sub(sid)
        self.refresh_subs_panel()
        self.refresh_account()
        self.redraw()

    # ================= ICS-Datei: Import / Export =================
    def build_ics_panel(self):
        self.ics_panel = tui.Panel("ics-datei · import / export")
        self.ics_in_cal = tui.Select(lambda v: None, max_chars=24, tooltip="Ziel-Kalender des Imports")
        self.ics_out_cal = tui.Select(lambda v: None, max_chars=24, tooltip="Kalender, der exportiert wird")
        self.ics_msg = label("", "dim", wrap=True)
        self.ics_panel.body.append(_wrap(label("importieren in", "dim"), self.ics_in_cal,
                                         tui.Button("ics-datei wählen …", self.ics_import_dialog)))
        self.ics_panel.body.append(_wrap(label("exportieren", "dim"), self.ics_out_cal,
                                         tui.Button("als ics speichern …", self.ics_export_dialog)))
        self.ics_panel.body.append(label("Import mit Serien und Ausnahmen; ein Schritt rückgängig (u). Nach Google höchstens "
                                         "300 Termine – größere Dateien erst in „lokal“. Export enthält Serien als Regel.",
                                         "dim", wrap=True))
        self.ics_panel.body.append(self.ics_msg)
        self.refresh_ics_panel()
        return self.ics_panel

    def refresh_ics_panel(self):
        if not hasattr(self, "ics_in_cal"):
            return
        cals = self.store.writable()
        cur = self.ics_in_cal.current or self.store.default_cal()
        self.ics_in_cal.set_options([(c["id"], c["name"]) for c in cals], cur if any(c["id"] == cur for c in cals) else "local")
        allc = [c for c in self.store.all_calendars()]
        cur2 = self.ics_out_cal.current or "local"
        self.ics_out_cal.set_options([(c["id"], c["name"]) for c in allc], cur2 if any(c["id"] == cur2 for c in allc) else "local")

    def _file_dialog(self, save, name, done):
        dlg = Gtk.FileDialog(title="Kalenderdatei speichern" if save else "Kalenderdatei (.ics) wählen")
        flt = Gtk.FileFilter()
        flt.set_name("Kalender (*.ics)")
        flt.add_pattern("*.ics")
        flt.add_pattern("*.ICS")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(flt)
        dlg.set_filters(filters)
        dlg.set_default_filter(flt)
        if save:
            dlg.set_initial_name(name)
        start = os.path.expanduser("~/Downloads") if os.path.isdir(os.path.expanduser("~/Downloads")) else os.path.expanduser("~")
        dlg.set_initial_folder(Gio.File.new_for_path(start))

        def cb(d, res):
            try:
                f = (d.save_finish if save else d.open_finish)(res)
            except GLib.Error:
                return
            done(f.get_path())
        (dlg.save if save else dlg.open)(self.win, None, cb)

    def ics_import_dialog(self):
        self._file_dialog(False, "", self.ics_import_file)

    def ics_import_file(self, path):
        cal = self.ics_in_cal.current or "local"
        try:
            with open(path, "rb") as f:
                raw = f.read(subs_mod.MAX_BYTES + 1)
            if len(raw) > subs_mod.MAX_BYTES:
                raise ValueError("Datei zu groß (über 15 MB)")
            text = raw.decode("utf-8-sig", errors="replace")
            _name, evs = icsfile.parse(text)
            if not evs:
                raise ValueError("keine Termine in der Datei")
            n = self.store.import_events(evs, cal)
        except (OSError, ValueError) as e:
            self.ics_msg.set_label(f"✗ {e}")
            self.win.say(f"Import: {e}", error=True)
            return
        cname = next((c["name"] for c in self.store.all_calendars() if c["id"] == cal), cal)
        self.ics_msg.set_label(f"✓ {n} Termine importiert in „{cname}“   (u = rückgängig)")
        self.after_edit(f"{n} Termine importiert")

    def ics_export_dialog(self):
        cal = self.ics_out_cal.current or "local"
        cname = next((c["name"] for c in self.store.all_calendars() if c["id"] == cal), "kalender")
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in cname).strip() or "kalender"
        self._file_dialog(True, f"{safe}.ics", lambda path: self.ics_export_file(path, cal, cname))

    def ics_export_file(self, path, cal, cname):
        evs = self.store.export_events(cal)
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(icsfile.to_ics(evs, cname))
        except OSError as e:
            self.ics_msg.set_label(f"✗ {e}")
            return
        self.ics_msg.set_label(f"✓ {len(evs)} Termine nach {path.replace(os.path.expanduser('~'), '~')} exportiert")
        self.win.say(f"{len(evs)} Termine exportiert")

    # ================= Weitere Google-Konten =================
    def build_accounts_panel(self):
        self.ac_panel = tui.Panel("weitere google-konten")
        self.ac_list = vbox(spacing=4)
        self.ac_panel.body.append(self.ac_list)
        self.ac_name = tui.Entry("Name, z. B. Uni oder Privat", width=24, activate=self.add_account_clicked)
        self.ac_msg = label("", "warn", wrap=True)
        self.ac_panel.body.append(_wrap(self.ac_name, tui.Button("konto hinzufügen …", self.add_account_clicked,
                                                                 tooltip="Öffnet die Google-Anmeldung im Browser")))
        self.ac_panel.body.append(label("Jedes Konto bekommt einen eigenen Namen – die E-Mail-Adresse wird nie angezeigt. "
                                        "Es gilt derselbe OAuth-Client; im Testmodus muss jedes Konto unter „Testnutzer“ "
                                        "eingetragen sein. Kalender und Änderungen bleiben je Konto getrennt.",
                                        "dim", wrap=True))
        self.ac_panel.body.append(self.ac_msg)
        self.refresh_accounts_panel()
        return self.ac_panel

    def refresh_accounts_panel(self):
        box = getattr(self, "ac_list", None)
        if box is None:
            return
        tui.clear(box)
        names = self.store.settings.setdefault("accounts", {})
        have = [a for a in gcal.accounts() if a != gcal.MAIN]
        for a in [a for a in list(names) if a != gcal.MAIN and a not in have and a != getattr(self, "login_acct", None)]:
            names.pop(a, None)                                  # Anmeldung abgebrochen: Name wieder vergessen
        if not have:
            box.append(label("noch kein weiteres Konto", "dim"))
        for a in have:
            left = gcal.seconds_left(a)
            if gcal.expired(a):
                status, cls = "⚠ abgelaufen", "warn"
            else:
                status, cls = (f"✓ angemeldet · noch {left / 86400:.1f} Tage" if left is not None and left > 0 else "✓ angemeldet"), "dim"
            ent = tui.Entry("Name", width=18, text=self.acct_name(a), activate=lambda aa=a: None)
            ent.connect("changed", lambda e, aa=a: self.rename_account(aa, e.get_text()))
            box.append(_wrap(ent, label(status, cls),
                             tui.Button("erneuern", lambda aa=a: self.start_login(aa)),
                             tui.Button("entfernen", lambda aa=a: self.remove_account(aa), danger=True)))

    def rename_account(self, acct, name):
        name = name.strip()
        if name and self.store.settings.setdefault("accounts", {}).get(acct) != name:
            self.store.settings["accounts"][acct] = name
            self.store.save_settings()

    def add_account_clicked(self):
        name = self.ac_name.get_text().strip()
        if not name:
            self.ac_msg.set_label("✗ Gib dem Konto zuerst einen Namen")
            return
        if not gcal.client():
            self.ac_msg.set_label("✗ Erst den OAuth-Client laden (Hauptkonto, Schritt 1–4)")
            return
        import uuid
        acct = uuid.uuid4().hex[:6]
        self.store.settings.setdefault("accounts", {})[acct] = name
        self.store.save_settings()
        self.ac_name.set_text("")
        self.ac_msg.set_label("")
        self.start_login(acct)

    def remove_account(self, acct):
        self.logout(acct)
        self.refresh_accounts_panel()

    # ================= Waybar =================
    def build_bar_panel(self):
        self.bar_panel = tui.Panel("waybar · nächster termin")
        self.bar_on = tui.Check("nächsten termin in der waybar zeigen", barstate.load()["on"], self.set_bar_on,
                                tooltip="Aus: in der Leiste bleibt nur das Kalender-Symbol.")
        self.bar_list = vbox(spacing=2)
        self.bar_panel.body.append(self.bar_on)
        self.bar_panel.body.append(label("Rechtsklick auf den Termin in der Leiste öffnet ein Menü: diesen Termin, "
                                         "die ganze Serie oder alle Termine verstecken. Hier (oder im Menü) lässt sich "
                                         "alles wieder einblenden.", "dim", wrap=True))
        self.bar_panel.body.append(self.bar_list)
        self.refresh_bar_panel()
        return self.bar_panel

    def refresh_bar_panel(self):
        box = getattr(self, "bar_list", None)
        if box is None:
            return
        tui.clear(box)
        d = barstate.load()                                   # frisch lesen: die Leiste schreibt dort selbst
        self.bar_on.set_active(d["on"])
        if not d["hidden"]:
            box.append(label("keine versteckten Termine", "dim"))
            return
        box.append(label(f"{len(d['hidden'])} in der Leiste versteckt", "accent", xalign=0))
        for h in d["hidden"]:
            box.append(_wrap(label(h["title"], hexpand=False), label(("ganze Serie" if h.get("series") else h.get("when", "")), "dim"),
                             tui.Button("wieder zeigen", lambda k=h["key"]: self.bar_show(k))))
        if len(d["hidden"]) > 1:
            box.append(_wrap(tui.Button("alle wieder zeigen", self.bar_show_all)))

    def set_bar_on(self, on):
        barstate.set_on(on)
        barstate.signal_waybar()

    def bar_show(self, key):
        barstate.show(key)
        barstate.signal_waybar()
        self.refresh_bar_panel()

    def bar_show_all(self):
        barstate.show_all()
        barstate.signal_waybar()
        self.refresh_bar_panel()

    # ================= Google Aufgaben =================
    TASKS_API_URL = "https://console.cloud.google.com/apis/library/tasks.googleapis.com"

    def build_tasks_panel(self):
        self.tk_panel = tui.Panel("google aufgaben")
        self.tk_status = label("", "dim", wrap=True)
        self.tk_btns = hbox(spacing=8)
        self.tk_panel.body.append(self.tk_status)
        self.tk_panel.body.append(_wrap(self.tk_btns))
        self.tk_panel.body.append(label("Aufgaben mit Datum erscheinen in Agenda, Woche und Monat (anklicken = abhaken), "
                                        "in der Agenda lassen sie sich anlegen und löschen. Nur für das Hauptkonto. "
                                        "Braucht eine zusätzliche Google-Berechtigung (einmal neu anmelden) und die "
                                        "„Tasks API“ in deinem Google-Cloud-Projekt.", "dim", wrap=True))
        self.refresh_tasks_panel()
        return self.tk_panel

    def refresh_tasks_panel(self):
        box = getattr(self, "tk_btns", None)
        if box is None:
            return
        tui.clear(box)
        st_ = self.store
        scope = gcal.has_tasks_scope(gcal.MAIN)
        main_in = gcal.logged_in(gcal.MAIN)
        if st_.tasks_on() and scope:
            n = len(st_.open_tasks(10 ** 6))
            self.tk_status.set_label(f"● aktiv · {n} offen · {len(st_.tasks.get('lists', []))} Liste(n)")
            box.append(tui.Button("jetzt abgleichen", lambda: self.sync(force=True)))
            box.append(tui.Button("ausschalten", self.tasks_off))
        elif not main_in:
            self.tk_status.set_label("○ erst das Hauptkonto anmelden")
        else:
            self.tk_status.set_label("○ aus – „aktivieren“ meldet dich einmal neu an (neue Berechtigung)")
            box.append(tui.Button("aufgaben aktivieren", lambda: self.start_login(gcal.MAIN, True)))
        if main_in:
            box.append(tui.Button("tasks api öffnen", lambda: Gio.AppInfo.launch_default_for_uri(self.TASKS_API_URL, None),
                                  tooltip="Im Google-Cloud-Projekt „Google Tasks API“ aktivieren"))

    def tasks_off(self):
        self.store.settings["tasks_on"] = False
        self.store.save_settings()
        self.refresh_tasks_panel()
        self.redraw()

    # ================= Google-Anmeldung: Ablauf beobachten =================
    EXPIRY_WARN = 24 * 3600         # ab so vielen Sekunden vor dem Ablauf warnen

    def expiry_soon(self):
        """Sekunden bis zum Ablauf des nächsten ablaufenden Kontos, wenn das bald (und noch nicht) ist, sonst None."""
        best = None
        for a in gcal.accounts():
            if gcal.expired(a):
                continue
            left = gcal.seconds_left(a)
            if left is not None and left < self.EXPIRY_WARN and (best is None or left < best[0]):
                best = (left, a)
        self._expiry_acct = best[1] if best else None
        return best[0] if best else None

    def expiry_tick(self):
        left = self.expiry_soon()
        self.update_header()
        if left is None:
            return
        last = self.store.settings.get("expiry_notified", 0)
        if time.time() - last < 6 * 3600:
            return
        self.store.settings["expiry_notified"] = time.time()
        self.store.save_settings()
        hours = max(0, int(left // 3600))
        when = "in unter einer Stunde" if hours < 1 else f"in etwa {hours} Stunden" if hours < 36 else "bald"
        if left <= 0:
            when = "jetzt"
        acct = getattr(self, "_expiry_acct", None) or gcal.MAIN
        multi = len(gcal.accounts()) > 1
        who = f" ({self.acct_name(acct)})" if multi else ""
        reminders.send_action(self, "Google-Anmeldung läuft ab" + who,
                              f"Der Abgleich pausiert {when}. Jetzt kurz erneuern?",
                              "expiry", "renew", "Jetzt erneuern", lambda: self.start_login(acct))
