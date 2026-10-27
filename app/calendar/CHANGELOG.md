# datist – Änderungen

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
