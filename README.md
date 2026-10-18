# kalender

Kalender im Terminal-Look der Suite (GTK4): Wochen- und Monatsansicht mit dem Stundenraster der TU Dresden
(Doppelstunden, Kalenderwochen gerade/ungerade), Kategorien, Wiederholungen, Offline-Speicher und Abgleich mit
Google Kalender.

## Installieren

```bash
gh auth login                                   # einmalig (Repo ist privat)
gh repo clone invincible-nix/kalender ~/kalender-src
cd ~/kalender-src && ./install.sh
```

Starten mit `kalender` (oder aus dem Menü). Hyprland: `bind = SUPER, K, exec, kalender` – die Taste blendet ein und aus.

## Google-Abgleich

Unter „konto“ in der App. Google verlangt einen eigenen OAuth-Client (Typ „Desktop-App“); die App führt Schritt
für Schritt durch. Anmeldung und Termine bleiben auf deinem Rechner (`~/.local/share/kalender`,
`~/.config/kalender`). Optional: deine Google-Adresse in `~/.config/kalender/login_hint` – dann schlägt Google
beim Anmelden gleich das richtige Konto vor.

## Aktualisieren / entfernen

`./update.sh` · `./uninstall.sh` (deine Termine bleiben)
