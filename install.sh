#!/usr/bin/env bash
# kalender installieren (ins eigene Benutzerverzeichnis).   ./install.sh [--update]
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
install -m 755 "$SRC/kalender.sh" "$HOME/.local/bin/kalender"
sed "s|@EXEC@|$HOME/.local/bin/kalender|g" "$SRC/kalender.desktop.in" > "$HOME/.local/share/applications/kalender.desktop"
cp -f "$SRC/kalender.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/kalender.svg"
echo "Fertig. Starten mit: kalender   (Tipp Hyprland: bind = SUPER, K, exec, kalender)"
echo "Google-Abgleich: in der App unter „konto“ – eigener OAuth-Client nötig (Anleitung dort)."
