#!/usr/bin/env python3
# datist – Kommandozeile ohne Oberfläche (schnell, ohne GTK): nächster Termin, Agenda, Waybar-Modul, JSON.
#   datist --next            eine Zeile: nächster Termin („09:20 Analysis · MA/041 · in 14 min“)
#   datist --waybar          JSON für ein Waybar-Modul (custom, "return-type": "json", "interval": 60, "signal": 8)
#   datist --bar-hide [once|series]   den in der Leiste gezeigten Termin dort verstecken (mit „Rückgängig“-Meldung)
#   datist --bar-off | --bar-on | --bar-show-all | --bar-info   alle verstecken / zeigen, Zustand fürs Menü
#   datist --agenda [N]      die nächsten N Tage (Standard 7) als Text
#   datist --json [N]        dieselben Termine als JSON (für eigene Skripte)
# Liest nur den lokalen Zwischenspeicher (kein Netz, keine Anmeldung nötig).
import datetime as dt, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import barstate
import store as st
from raster import TZ, WEEKDAYS


def now():
    return dt.datetime.now(TZ).replace(tzinfo=None)


def rel(mins):
    if mins <= 0:
        return "jetzt"
    if mins < 90:
        return f"in {mins} min"
    if mins < 36 * 60:
        return f"in {round(mins / 60)} h"
    return f"in {round(mins / 1440)} Tagen"


def load(days):
    s = st.Store()
    t0 = now()
    occ = s.occurrences(t0 - dt.timedelta(hours=12), t0 + dt.timedelta(days=days))
    occ = s.mark_conflicts(occ)
    return s, t0, [o for o in occ if o["e"] > t0 and o.get("cal") != "holidays"]


def line(o, t0, with_day=True):
    allday = o.get("allday") or (o["e"] - o["s"]) >= dt.timedelta(hours=20)
    if allday:
        when = f"{WEEKDAYS[o['s'].weekday()]} {o['s']:%d.%m.} ganztägig"
    else:
        day = "" if o["s"].date() == t0.date() else f"{WEEKDAYS[o['s'].weekday()]} {o['s']:%d.%m.} "
        when = f"{day}{o['s']:%H:%M}"
    txt = f"{when} {o.get('title') or 'Termin'}"
    if o.get("location"):
        txt += f" · {o['location']}"
    return txt


def next_event(occ, t0):
    """Laufender oder nächster Termin mit Uhrzeit (ganztägige zählen nicht)."""
    timed = [o for o in occ if not o.get("allday") and (o["e"] - o["s"]) < dt.timedelta(hours=20)]
    timed.sort(key=lambda o: o["s"])
    return timed[0] if timed else None


def cmd_next():
    s, t0, occ = load(7)
    o = next_event(occ, t0)
    if not o:
        print("kein Termin in den nächsten 7 Tagen")
        return
    mins = int((o["s"] - t0).total_seconds() // 60)
    state = "läuft: " if o["s"] <= t0 else ""
    print(f"{state}{line(o, t0)} · {'bis ' + format(o['e'], '%H:%M') if o['s'] <= t0 else rel(mins + (1 if (o['s'] - t0).total_seconds() % 60 else 0))}")


def bar_events(occ):
    """Für die Leiste: versteckte Termine weglassen."""
    hidden = barstate.load()["hidden"]
    return [o for o in occ if not barstate.is_hidden(o, hidden)]


def cmd_waybar():
    if not barstate.load()["on"]:                        # alle versteckt: nur das Symbol, damit das Menü erreichbar bleibt
        print(json.dumps({"text": "󰃭", "tooltip": "Termine in der Leiste versteckt – Rechtsklick: wieder zeigen",
                          "class": ["off"], "alt": "off"}, ensure_ascii=False))
        return
    s, t0, occ = load(7)
    occ = bar_events(occ)
    o = next_event(occ, t0)
    exams = s.upcoming("pruefung", 90, today=t0.date(), now=t0)
    tip = []
    for x in occ[:8]:
        tip.append(("⚡ " if x.get("conflict") else "") + line(x, t0))
    if exams:
        tip.append("")
        tip += [f"! {x['s']:%d.%m.} {x['title']}" for x in exams[:3]]
    if occ:
        tip += ["", "rechtsklick: Termin in der Leiste verstecken"]
    cls = "none"
    if not o:
        text, alt = "󰃭 –", "none"
    else:
        mins = int((o["s"] - t0).total_seconds() // 60)
        running = o["s"] <= t0
        title = (o.get("title") or "Termin")
        title = title if len(title) <= 22 else title[:21] + "…"
        text = f"󰃭 {o['s']:%H:%M} {title}" if o["s"].date() == t0.date() else f"󰃭 {WEEKDAYS[o['s'].weekday()]} {o['s']:%H:%M} {title}"
        if running:
            cls, text = "now", f"󰃭 läuft: {title}"
        elif mins <= 10:
            cls = "soon"
            text = f"󰃭 {title} {rel(mins)}"
        elif mins <= 120 and o["s"].date() == t0.date():
            cls = "today"
        else:
            cls = "later"
        alt = cls
    if exams and (exams[0]["s"].date() - t0.date()).days <= 3:
        cls += " exam"
    print(json.dumps({"text": text, "tooltip": "\n".join(tip) or "keine Termine", "class": cls.split(), "alt": alt},
                     ensure_ascii=False))


def _shown():
    s, t0, occ = load(7)
    return next_event(bar_events(occ), t0)


def cmd_bar_info():
    """Für das Waybar-Menü: was gerade gezeigt wird und was sich ändern lässt (JSON)."""
    o = _shown()
    d = barstate.load()
    print(json.dumps({"on": d["on"], "hidden": len(d["hidden"]), "title": (o or {}).get("title") or "",
                      "recurring": bool(o and barstate.is_recurring(o))}, ensure_ascii=False))


def cmd_bar_hide(mode=None):
    """Den in der Leiste gezeigten Termin dort verstecken. mode: "once" (nur diese Wiederholung), "series" (ganze
    Serie), sonst Serien als Ganzes. Die Meldung bietet „Rückgängig“ an."""
    o = _shown()
    if o is None:
        print("kein Termin zu verstecken")
        return
    series = None if mode not in ("once", "series") else (mode == "series")
    entry = barstate.hide(o, series)
    barstate.signal_waybar()
    what = f"{o.get('title') or 'Termin'}" + (" (ganze Serie)" if entry.get("series") else "")
    print(f"in der Leiste versteckt: {what}")
    import shutil, subprocess
    if shutil.which("notify-send"):
        try:
            r = subprocess.run(["notify-send", "-a", "datist", "-i", "datist", "-t", "9000", "-A", "undo=Rückgängig",
                                "In der Leiste versteckt", f"{what}\nWieder einblenden: Rechtsklick auf das Symbol oder datist → Einstellungen"],
                               capture_output=True, text=True, timeout=15)
            if r.stdout.strip() == "undo":
                barstate.show(entry["key"])
                barstate.signal_waybar()
                print("rückgängig gemacht")
        except (OSError, subprocess.SubprocessError):
            pass


def cmd_bar_set(on):
    barstate.set_on(on)
    barstate.signal_waybar()
    print("Termine in der Leiste " + ("gezeigt" if on else "versteckt"))


def cmd_bar_show_all():
    barstate.show_all()
    barstate.set_on(True)
    barstate.signal_waybar()
    print("alle Termine in der Leiste wieder gezeigt")


def cmd_agenda(days, as_json):
    s, t0, occ = load(days)
    if as_json:
        out = [{"title": o.get("title"), "start": o["s"].isoformat(timespec="minutes"), "end": o["e"].isoformat(timespec="minutes"),
                "allday": bool(o.get("allday")), "location": o.get("location") or "", "calendar": o.get("cal"),
                "type": o.get("cat"), "conflict": bool(o.get("conflict"))} for o in occ]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if not occ:
        print(f"keine Termine in den nächsten {days} Tagen")
        return
    cur = None
    for o in occ:
        d = max(o["s"].date(), t0.date())
        if d != cur:
            cur = d
            tag = "heute" if d == t0.date() else "morgen" if d == t0.date() + dt.timedelta(days=1) else ""
            print(f"\n{WEEKDAYS[d.weekday()]} {d:%d.%m.}" + (f"  ({tag})" if tag else ""))
        allday = o.get("allday") or (o["e"] - o["s"]) >= dt.timedelta(hours=20)
        when = "ganztägig" if allday else f"{o['s']:%H:%M}–{o['e']:%H:%M}"
        print(f"  {when:<11} {'⚡ ' if o.get('conflict') else ''}{o.get('title')}" + (f" · {o['location']}" if o.get("location") else ""))


def main(argv):
    if "--waybar" in argv:
        cmd_waybar()
    elif "--bar-hide" in argv:
        rest = argv[argv.index("--bar-hide") + 1:]
        cmd_bar_hide(rest[0] if rest else None)
    elif "--bar-info" in argv:
        cmd_bar_info()
    elif "--bar-off" in argv:
        cmd_bar_set(False)
    elif "--bar-on" in argv:
        cmd_bar_set(True)
    elif "--bar-show-all" in argv:
        cmd_bar_show_all()
    elif "--agenda" in argv or "--json" in argv:
        flag = "--json" if "--json" in argv else "--agenda"
        rest = argv[argv.index(flag) + 1:]
        try:
            days = max(1, min(90, int(rest[0]))) if rest else 7
        except ValueError:
            days = 7
        cmd_agenda(days, flag == "--json")
    else:
        cmd_next()


if __name__ == "__main__":
    main(sys.argv[1:])
