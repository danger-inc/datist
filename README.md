# datist

Kalender im Terminal-Look der Suite (GTK4): Wochen- und Monatsansicht mit dem Stundenraster der TU Berlin
(Doppelstunden, Kalenderwochen gerade/ungerade), Kategorien, Wiederholungen, Offline-Speicher und Abgleich mit
Google Kalender.

## Installieren – Linux

```bash
gh auth login                                   # einmalig (Repo ist privat, Einladung nötig)
gh repo clone invincible-nix/datist ~/datist-src
cd ~/datist-src && ./install.sh
```

Der Installer fragt nach den Systempaketen (GTK4, PyGObject – einmal Passwort), kopiert datist nach
`~/.local/share/rice-apps/calendar` und legt den Befehl `datist` und einen Menüeintrag an. Die Symbole bringt
datist selbst mit, eine Nerd Font ist nicht nötig.

Starten mit `datist` (oder aus dem Menü). Nochmal aufrufen blendet das Fenster ein/aus.
Hyprland: `hl.bind("SUPER + K", hl.dsp.exec_cmd("datist"))` bzw. `bind = SUPER, K, exec, datist`.

## Installieren – Windows 10/11

1. Repo herunterladen: auf GitHub **Code → Download ZIP** und entpacken (oder `gh repo clone …`).
2. Im Ordner **`install-windows.bat`** doppelklicken.

Das Skript richtet einmalig **MSYS2** ein (liefert GTK 4 und Python für Windows, ~1 GB, fragt nach
Admin-Rechten), installiert die Pakete und legt datist ins Startmenü. Entfernen: `uninstall-windows.bat`.
Unter Windows beendet ✕ datist ganz (unter Linux läuft es im Hintergrund weiter).

## Läuft auf

| System | Status |
|---|---|
| Ubuntu 24.04+, Linux Mint 22+, Debian 13 | getestet (Ubuntu 24.04) |
| Fedora 39+ | getestet (Fedora 44) |
| Arch, EndeavourOS, CachyOS, Manjaro | getestet (Arch) |
| openSUSE Tumbleweed | sollte gehen (ungetestet) |
| Windows 10/11 | über MSYS2 – App-Start getestet, Installer auf echtem Windows noch ungetestet |

Nötig ist **GTK 4.12 oder neuer** (Ubuntu 22.04 / Mint 21 / Debian 12 sind zu alt).
Auf GNOME, KDE und Windows hat das Fenster einen normalen Rahmen (verschieben über die Kopfzeile, Größe am Rand
ziehen); auf Hyprland/Sway & Co. ist es rahmenlos.

## Google-Abgleich

Unter „konto“ in der App. Google verlangt einen eigenen OAuth-Client (Typ „Desktop-App“); die App führt Schritt
für Schritt durch. Anmeldung und Termine bleiben auf deinem Rechner (`~/.local/share/kalender`,
`~/.config/kalender`). Optional: deine Google-Adresse in `~/.config/kalender/login_hint` – dann schlägt Google
beim Anmelden gleich das richtige Konto vor.

## Aktualisieren / entfernen

- Linux: `./update.sh` · `./uninstall.sh` (deine Termine bleiben)
- Windows: neue Version holen und `install-windows.bat` erneut starten · `uninstall-windows.bat`

## Probleme?

- **Kästchen statt Symbolen:** neu installieren bzw. `./update.sh` – die Symbolschrift kommt mit.
- **`datist: Befehl nicht gefunden`:** `~/.local/bin` fehlt im PATH (der Installer zeigt, was in die `~/.bashrc`
  gehört). Aus dem Anwendungsmenü startet es auch so.
- **„GTK … ZU ALT“ beim Installieren:** die Distribution ist zu alt, siehe „Läuft auf“.
