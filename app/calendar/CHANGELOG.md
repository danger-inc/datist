# datist – Änderungen

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
