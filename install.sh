#!/usr/bin/env bash
# datist installieren (ins eigene Benutzerverzeichnis, root nur für Systempakete).
#   ./install.sh            normal (fragt nach Systempaketen)
#   ./install.sh --update   ohne Rückfragen (von update.sh)
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SRC/pkg.sh"
RICE="$HOME/.local/share/rice-apps"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
UPDATE=0; [[ "${1:-}" == "--update" ]] && UPDATE=1

say "== datist installieren =="
if ask "Systempakete installieren (GTK4, PyGObject)?"; then
    pkg_install \
        "gtk4 python python-gobject python-cairo adwaita-icon-theme xdg-utils" \
        "python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 adwaita-icon-theme xdg-utils" \
        "python3 python3-gobject python3-cairo gtk4 adwaita-icon-theme xdg-utils" \
        "python3 python3-gobject python3-gobject-cairo python3-gobject-Gdk typelib-1_0-Gtk-4_0 adwaita-icon-theme xdg-utils" \
        || warn "Paketinstallation nicht vollständig – weiter."
fi
echo

say "Kopiere datist nach $RICE/calendar …"
mkdir -p "$RICE/calendar" "$RICE/fonts" "$BIN" "$APPS" "$ICONS"
cp -f "$SRC"/app/calendar/*.py "$SRC"/app/calendar/VERSION "$SRC"/app/calendar/CHANGELOG.md "$RICE/calendar/"
cp -f "$SRC/app/tui.py" "$SRC/app/glass.py" "$SRC/app/istheme.py" "$SRC/app/ist-swipe.py" "$SRC/app/changelog.py" "$SRC/app/swipe.py" "$RICE/"             # gemeinsame Bausteine der Suite
cp -f "$SRC"/app/fonts/* "$RICE/fonts/"                           # Symbolschrift (Icons ohne Nerd Font)
install -m 755 "$SRC/datist.sh" "$BIN/datist"
sed "s|@EXEC@|$BIN/datist|g" "$SRC/datist.desktop.in" > "$APPS/datist.desktop"
cp -f "$SRC/datist.svg" "$ICONS/datist.svg"
# alter Name „kalender“ (bis 2026-10) – Termine/Anmeldung bleiben in ~/.local/share/kalender
rm -f "$BIN/kalender" "$APPS/kalender.desktop" "$ICONS/kalender.svg"
refresh_desktop

echo
say "Prüfe …"
check_gtk || warn "Ohne passendes GTK startet datist nicht – siehe README."
echo
path_hint
say "Fertig!  Starten mit:  datist   (oder über das Anwendungsmenü)"
echo "Google-Abgleich: in der App unter „konto“ – eigener OAuth-Client nötig (Anleitung dort)."
echo "Aktualisieren: ./update.sh   Entfernen: ./uninstall.sh (Termine bleiben)"
