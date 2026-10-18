#!/usr/bin/env bash
# datist installieren (ins eigene Benutzerverzeichnis).   ./install.sh [--update]
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RICE="$HOME/.local/share/rice-apps"
UPDATE=0; [[ "${1:-}" == "--update" ]] && UPDATE=1
if (( ! UPDATE )); then
    read -rp "Systempakete (GTK4, PyGObject) installieren? [J/n] " a
    if [[ ! "${a,,}" =~ ^n ]]; then
        if command -v pacman >/dev/null; then sudo pacman -S --needed --noconfirm gtk4 python-gobject python-cairo || true
        elif command -v apt >/dev/null; then sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 || true
        elif command -v dnf >/dev/null; then sudo dnf install -y python3-gobject gtk4 || true; fi
    fi
fi
mkdir -p "$RICE/calendar" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
cp -f "$SRC"/app/calendar/*.py "$RICE/calendar/"
cp -f "$SRC/app/tui.py" "$SRC/app/glass.py" "$RICE/"          # gemeinsame Bausteine der Suite
install -m 755 "$SRC/datist.sh" "$HOME/.local/bin/datist"
sed "s|@EXEC@|$HOME/.local/bin/datist|g" "$SRC/datist.desktop.in" > "$HOME/.local/share/applications/datist.desktop"
cp -f "$SRC/datist.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/datist.svg"
# alter Name „kalender“ (bis 2026-10) – Termine/Anmeldung bleiben in ~/.local/share/kalender
rm -f "$HOME/.local/bin/kalender" "$HOME/.local/share/applications/kalender.desktop" "$HOME/.local/share/icons/hicolor/scalable/apps/kalender.svg"
echo "Fertig. Starten mit: datist   (Tipp Hyprland: bind = SUPER, K, exec, datist)"
echo "Google-Abgleich: in der App unter „konto“ – eigener OAuth-Client nötig (Anleitung dort)."
