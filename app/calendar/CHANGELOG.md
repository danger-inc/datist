# datist – Änderungen

## 1.12.0 (2026-10-28)
- **Waybar: Rechtsklick öffnet ein Menü** (im Stil der anderen Leisten-Menüs): „diesen Termin verstecken“, bei Serien „diese Wiederholung“ oder „ganze Serie verstecken“, „alle Termine verstecken“ (die Leiste zeigt dann nur das Kalender-Symbol), „wieder zeigen“ und „einstellungen“. Neu auf der Kommandozeile: `datist --bar-hide [once|series]`, `--bar-off`, `--bar-on`, `--bar-show-all`, `--bar-info`.
- **Neuer Reiter ⁵ „aufgaben“**: Google-Aufgaben anlegen, abhaken und löschen. Sind sie noch nicht aktiviert, steht dort die Erklärung (einmal neu anmelden, Tasks API im Cloud-Projekt) mit Knopf. Die Agenda zeigt nur noch fällige Aufgaben.
- **Einstellungen überarbeitet**: Das Konto-Fenster hat jetzt Seiten – allgemein, google, kalender, erinnerungen, leiste & desktop. `datist --tab bar` öffnet direkt die Leisten-Seite.
- **Desktop-Karte**: im -ist-Stil (Rahmen mit Titel wie in filist), Tastenkürzel Super+Shift+K, in datist die Taste `b`, auf der Kommandozeile `datist --desk`.
- Bei schmalen Fenstern (unter 640 px) zeigen die Reiter nur noch Symbole.

## 1.11.2 (2026-10-28)
- **Termin in der Waybar verstecken**: Rechtsklick auf den Termin in der Leiste versteckt ihn dort (Serien als Ganzes); die Meldung bietet „Rückgängig“ an, die Leiste aktualisiert sich sofort. In den Einstellungen gibt es den Bereich „waybar · nächster termin“ mit einem Schalter für das ganze Modul und der Liste der versteckten Termine („wieder zeigen“). Im Termin selbst steht dazu der Haken „in der Waybar zeigen“.
- **Waybar-Layout**: Der Termin-Block ist so hoch wie der Uhr-Chip, näher an der Uhr, und Sound und Helligkeit sitzen direkt daneben (die linke Seite ist jetzt eine Gruppe ohne den globalen Abstand).
- Die versteckten Termine liegen in einer eigenen Datei (`bar.json`), damit die Kommandozeile und die laufende App sich nicht gegenseitig Einstellungen überschreiben.

## 1.11.1 (2026-10-28)
- **Konto-/Einstellungsfenster war viel zu breit** (über 2000 px, dadurch abgeschnitten und verschoben): Ein langer Erklärtext im Semester-Bereich hatte keinen Zeilenumbruch und erzwang seine volle Breite. Jetzt umbricht er, die Mindestbreite liegt bei ca. 520 px. Das Fenster gehört außerdem zur App (Fensterklasse `de.invincible.Datist` statt `python3`), damit eigene Fensterregeln greifen.
- **Zahnrad (Einstellungen) fehlte im Halbfenster**: Die Kopfzeile ließ rechts Elemente abgeschnitten, wenn sie zu breit wurde (Zahnrad, Version, Schließen). Jetzt blendet sie bei Platzmangel zuerst Nebensächliches aus (KW-Anzeige, Abgleich-Anzeige, Prüfungs-Badge, ‹ heute ›), Zahnrad, Version, Tabs und ✕ bleiben immer sichtbar.
- **Waybar-Modul**: Der nächste Termin war nahezu unsichtbar (fehlende Textfarbe). Er hat jetzt Systemfarben (`@foreground`, `@primary`), einen Rahmen wie die Leiste, Hover und Zustandsfarben (bald, läuft, Prüfung). Ein Klick öffnet datist.

## 1.11.0 (2026-10-28)
- **Mehrere Google-Konten**: Im Konto-Fenster unter „weitere google-konten“ lassen sich beliebig viele Konten hinzufügen. Jedes bekommt einen eigenen Namen (z. B. „Uni“); die E-Mail-Adresse wird nie angezeigt. Eigenes Token je Konto, Kalender und Änderungen bleiben getrennt und gehen immer ans richtige Konto. Läuft ein Konto ab, laufen die anderen weiter, oben steht „⚠ neu anmelden“ und der Klick erneuert genau dieses Konto. Das bisherige Konto bleibt unverändert das Hauptkonto.
- **Google Aufgaben** (optional, Hauptkonto): „aufgaben aktivieren“ im Konto-Fenster meldet dich einmal mit der zusätzlichen Berechtigung neu an (die „Tasks API“ muss in deinem Cloud-Projekt aktiv sein, der Knopf „tasks api öffnen“ führt hin). Aufgaben mit Datum erscheinen in Woche und Monat (anklicken = abhaken) und in der Agenda; dort lassen sie sich anlegen („Blatt 4 abgeben bis freitag“), abhaken und löschen, auch offline.
- **Gäste, Meet und Zeitzonen** im Termin: „gäste“ (E-Mail-Adressen, nur wer den Termin organisiert), „Google Meet-Link erstellen“ (Link steht danach mit öffnen/kopieren am Termin) und „zeitzone“ (z. B. America/New_York; die Uhrzeiten gelten dann dort, „bei dir: …“ zeigt deine Zeit). Es geht **keine Mail** an Gäste raus, außer du hakst beim Speichern „Einladungen senden“ an.
- **Desktop-Karte**: Die nächsten Termine, Prüfungs-Countdown und offene Aufgaben dauerhaft auf dem Hintergrundbild, unter allen Fenstern (Einstellungen → „termine auf dem hintergrundbild“, Standard aus, Position wählbar, Standard oben links). Braucht Wayland mit layer-shell (Hyprland, Sway …) und gtk4-layer-shell.
- **Schnelleingabe** versteht mehr: „nächsten Montag“, „übernächsten Freitag“, „nächste Woche Dienstag“, „in 3 Tagen / 2 Wochen / 1 Monat“, „am Freitag“, „um 14 Uhr“, „von 14 bis 16 Uhr“, „14:30“, „für 2h / 90min“, „ganztägig“ und englisch (next monday, friday 3pm, in 2 weeks). Ein Wort wie „Raum 14“ oder „Blatt 4“ bleibt Titel. Das gilt auch für „gehe zu“ (g).
- Änderungen, die man während eines laufenden Abgleichs macht, gehen jetzt gleich danach raus (vorher erst beim nächsten Abgleich).

## 1.10.0 (2026-10-28)
- **Termine mit der Maus verschieben** (Woche, Tag, Monat): ziehen und auf ein anderes Feld loslassen. Das Ziel leuchtet mit Tag und Doppelstunde; die Dauer bleibt, in der Woche landet der Termin am Beginn der Doppelstunde, im Monat bleibt die Uhrzeit. Den **unteren Rand** eines Termins ziehen ändert die Dauer (Ende der Doppelstunde). Ein Klick ohne Ziehen öffnet den Termin wie bisher. Serientermine verschieben nur diese Wiederholung, Abo- und Feiertags-Termine sind geschützt. Mit `u` rückgängig.
- **Überschneidungen**: Termine, die sich zeitlich überlappen, bekommen ein ⚡ in der Rahmenecke, in Tag und Woche steht dazu „überschneidet: …“. In der Agenda steht „mit …“.
- **Feiertage und vorlesungsfreie Zeit**: Gesetzliche Feiertage (bundesweit, dazu das Bundesland im Konto-Fenster unter „semester“) erscheinen im eigenen Kalender „Feiertage & Semester“ (ausblendbar). Das Datum steht in der Woche und im Monat in der Warnfarbe. Aus deinen Semesterzeiten kommen Vorlesungsbeginn/-ende, freie Zeiträume und die Wochen-Kopfzeile „· vorlesungsfrei“; optional steht je Semester `"exams": [["2027-02-08", "2027-03-12"]]` für eine Prüfungsphase („· prüfungsphase“). Geschätzte Semester erzeugen keine Marken.
- **Agenda** (neuer Tab ⁴, Taste 4): die nächsten 7, 14 oder 30 Tage, nach Tag gruppiert, mit Prüfungen oben. j/k wählt, ⏎ öffnet.
- **Prüfungs-Countdown**: Oben in der Kopfleiste steht „! Name · 12 d“ für die nächste Prüfung (Klick springt hin, Tooltip nennt die nächsten fünf).
- **Leistenanzeige / Kommandozeile** ohne Fenster: `datist --next`, `datist --agenda [N]`, `datist --json [N]` und `datist --waybar` (JSON für ein Waybar-Modul, Klassen `none`, `later`, `today`, `soon`, `now`, `exam`). Konfigurationsbeispiel in der README.

## 1.9.0 (2026-10-28)
- **Erinnerungen**: Eine Desktop-Meldung vor jedem Termin (Standard 10 min vorher, ganztägige nur auf Wunsch). Im Termin steht ein neues Feld „erinnerung“: frei eingeben, z. B. `30 min`, `2 h`, `1 tag`, `zum beginn` oder `keine`, leer = Standard. Der Standard-Vorlauf steht im Konto-Fenster („erinnerungen“) samt Test-Meldung. Der Vorlauf wird bei Google als Zusatzfeld am Termin gespeichert, nichts an Googles eigenen Erinnerungen ändert sich. Erinnerungen aus notist melden zum Zeitpunkt selbst. Läuft, solange datist im Hintergrund ist (startet beim Login).
- **Suche** (Taste `/`): Titel, Ort, Notiz und Typ, mehrere Wörter müssen alle vorkommen; leer zeigt die nächsten Termine. ⏎ springt zum Termin, strg+⏎ öffnet ihn zum Bearbeiten.
- **Rückgängig** (Taste `u` oder strg+z, bis zu 30 Schritte): Anlegen, Ändern und Löschen, auch Import. Bei Terminen in Google-Serien geht es nicht (der Serientermin liegt nur bei Google); dann sagt datist das klar. Änderungen von notist zählen nicht.
- **Google-Anmeldung ohne Überraschung**: Ab 24 Stunden vor dem Ablauf (Testmodus: 7 Tage) erscheint oben „⏳ erneuern (noch N h)“ und eine Benachrichtigung mit dem Knopf „Jetzt erneuern“; ein Klick erneuert, der Abgleich läuft ohne Unterbrechung weiter. Das Konto-Fenster zeigt die Restzeit und hat „anmeldung erneuern“.
- **Kalender-Abos (ICS)**: Beliebig viele Links (Uni-Stundenplan, Feiertage …) als eigene, nur lesbare Kalender, alle 30 Minuten aktualisiert (strg+r sofort), ohne Konto. Die Adresse kann ein Geheimnis enthalten und wird nie angezeigt, nur der Server.
- **ICS-Import und -Export** im Konto-Fenster: Datei in einen schreibbaren Kalender importieren (mit Serien und Ausnahmen; nach Google höchstens 300 Termine) und jeden Kalender als `.ics` speichern.
- Gespeicherte Daten (Termine, Abo-Adressen) sind jetzt nur für dich lesbar (Rechte 0600).

## 1.8.1 (2026-10-27)
- **Alt+Zahl wechselt den Tab**: Alt+1 Tag, Alt+2 Woche, Alt+3 Monat – auch beim Tippen in einem Feld (im Termin-Editor wählen 1–7 die DS, solange man nicht in einem Feld tippt; Alt+1–7 geht immer).

## 1.8.0 (2026-10-27)
- **Wechsel-Animation**: Der Wechsel zwischen Hell und Dunkel (und zwischen Designs) läuft als Scanbalken über den ganzen Bildschirm. Alle Fenster, die Leiste und das Terminal wechseln darunter im selben Moment, hinter dem Balken steht das neue Design. An/aus und Dauer (Standard 1,5 s) stehen in der Designauswahl der Einstellungen.

## 1.7.0 (2026-10-26)
- **Design wählbar**: In den Einstellungen gibt es die Designauswahl wie in notist (Automatisch + 9 Designs). Die Wahl gilt für alle -ist-Apps zugleich und wirkt sofort. Bei „Automatisch“ (Desktop-Farben) kannst du zwischen **Dunkel** und **Hell** umschalten.

## 1.6.2 (2026-10-25)
- **Windows**: Speichern brach bei Zeichen wie „☑“ mit einem Zeichensatz-Fehler ab; Textdateien werden dort jetzt
  immer als UTF-8 gelesen und geschrieben.
- **Windows**: Der Glas-Schalter funktioniert wieder.

## 1.6.1 (2026-10-25)
- **Update-Knopf**: Neben der Versionsnummer steht „󰑐“ – Klick sucht sofort nach einem Update. Gibt es eine neuere
  Version, wird daraus „󰚰 update“; ein Klick lädt und installiert sie (Linux und Windows), danach heißt er „󰑓 neu starten“.
- **Rückmeldung bei Umschalt-Knöpfen**: „An“ (z. B. „Ton behalten“) ist jetzt auch unter dem Mauszeiger zu sehen,
  Drücken färbt sofort – man muss die Maus nicht mehr wegbewegen, um zu sehen, ob der Klick angekommen ist.
- **2 Finger auch vorwärts**: Nach einem Zurück-Wischen bringt das Wischen in die andere Richtung zur verlassenen
  Seite zurück.
- **Windows: echte Titelleiste** – das Fenster lässt sich verschieben, in der Größe ändern, minimieren und
  maximieren.

## 1.6.0 (2026-10-22)
- **Wo stehe ich gerade? – Woche**: minutengenaue Jetzt-Linie mit Punkt in der heutigen Spalte (über den
  Terminen, verdeckt nichts), dünn durch die anderen Tage, links die Uhrzeit als Marke; die heutige Spalte ist
  leicht hinterlegt.
- **Tag**: Linie „● jetzt 13:40“ genau zwischen den Terminen; der laufende Termin bekommt einen kräftigen Rahmen
  mit „● läuft · bis …“, vergangene Termine werden blasser.
- **Monat**: der heutige Tag hat einen farbigen Rahmen und die Uhrzeit neben der Tageszahl, schon vergangene
  Termine des Tages sind blasser.
- **Farbvorschau beim Termin anlegen**: Farben als Kacheln statt Liste – drüberfahren zeigt die Farbe sofort
  in einer Vorschau (so sieht der Termin in Woche und Monat aus) samt der Farbe, die er in Google Kalender bekommt.

## 1.5.0 (2026-10-22)
- **Termin wegklicken**: Ein Klick neben den Termin-Editor schließt ihn. Hast du etwas geändert, wird es dabei
  gespeichert (bei einer ungültigen Eingabe bleibt er offen und zeigt den Fehler); unverändert geht er einfach zu.
  Esc bzw. „abbrechen“ verwirft wie bisher.
- **2-Finger-Zurück** (und Maustaste „zurück“) funktioniert jetzt auch über dem Editor und der Hilfe und schließt sie.

## 1.4.0 (2026-10-21)
- **Mehrtägige Termine**: im Termin neben dem Datum „bis“ eintragen (z. B. `fr`, `+2`, `23.10.`). Sie laufen als
  Balken über die Tage der Woche (mehrere übereinander), im Monat mit „↦“ an den Folgetagen, in der Tagesansicht
  mit „tag 2/3“. Termine über Mitternacht stehen jetzt auch am nächsten Morgen.
- **Ganzes Semester**: Häkchen im Termin legt ihn 1× pro Woche über die ganze Vorlesungszeit an – ohne Feiertage
  und Pausen, wahlweise nur **A-Woche** (1. Woche, ungerade KW) oder **B-Woche** (2. Woche, gerade KW), auch über
  den Jahreswechsel mit KW 53 richtig. Die Semesterzeiten stehen unter konto → semester.
- **Farben in Google Kalender**: Termine aus datist bekommen dort die passende Farbe statt Standard-Blau
  (nächste der 11 Google-Farben). Ältere Termine werden beim nächsten Abgleich nachgezogen; „farben an google
  übertragen“ im Konto gleicht alle neu ab.
- **2 Finger zurück** (Wischen, Maustaste 8) – wie in den anderen Apps, endet immer in der Wochenansicht.
- **2-Finger-Zoom**: zusammenziehen = Tag → Woche → Monat, auseinander = zurück.
- **Konto & Einstellungen** sind jetzt ein eigenes Fenster: Knopf „konto“ oben rechts neben der Version
  (`datist --tab acct` öffnet es weiterhin).
- „ganze serie“ setzt den Editor nicht mehr zurück: Titel, Farbe, Ort, Notiz usw. bleiben, das Datum bleibt
  beim angeklickten Termin. Nach dem Speichern springt die Ansicht nicht mehr zum Serienbeginn (eine Woche zurück).
- Beim Bearbeiten einer Google-Serie gehen ausgelassene Einzeltermine nicht mehr verloren.

## 1.3.1 (2026-10-20)
- `datist --tab acct` (bzw. day, week, month) öffnet direkt diesen Tab – scourge nutzt das für
  „einstellungen“.

## 1.3.0 (2026-10-20)
- **Erinnerungen aus notist** erscheinen als 15-Minuten-Termine „󰂚 Titel“ – im Kalender, den du in notist wählst
  (lokal oder Google). Ändert oder löscht du die Erinnerung in notist, zieht datist sofort nach; „öffnen“ im Termin
  springt zum Eintrag in notist.

## 1.2.0 (2026-10-19)
- **Changelog**: oben rechts steht jetzt die Version – Klick darauf zeigt, was sich geändert hat. Nach einem
  Update ist sie hervorgehoben und die Statuszeile sagt einmal Bescheid.
- Ein Klick auf einen Termin öffnet ihn direkt zum Bearbeiten (in allen Ansichten).
- Woche: Klick auf einen Wochentag springt in die Tagesansicht. Monat: Klick auf die Tageszahl oder „+N weitere“
  öffnet den Tag.
- Tastenhinweise bleiben auch im kleinen Fenster sichtbar, der Name „datist“ steht oben links.
- Das „✓ HH:MM“ oben zeigt den letzten Google-Abgleich – ein Klick gleicht sofort ab.
- Startgröße passt auf kleine Bildschirme (z. B. 1366×768).
- Weniger Speicherverbrauch auf Dauer: entfernte Zeilen und Listen werden jetzt wirklich freigegeben.

## 1.1.0 (2026-10-18)
- **Neuer Name: datist** (vorher „kalender“). Deine Termine und die Google-Anmeldung bleiben, wo sie sind.
- Installer überarbeitet: fehlende Pakete werden übersprungen statt abzubrechen, Symbole erscheinen auch ohne
  Nerd Font, Windows-Installer.

## 1.0.0 (2026-10-18)
- Erste Veröffentlichung: Tag/Woche/Monat im TUI-Look mit Uni-Stundenraster (DS-Blöcke, Kalenderwoche,
  gerade/ungerade Woche), Kategorien in den Desktop-Farben.
- Abgleich mit Google Kalender (eigener OAuth-Client), funktioniert auch offline und holt Änderungen nach.
- Wiederholungen (täglich, wöchentlich, nur gerade/ungerade Wochen …), Schnell-Eingabe mit `a`.
