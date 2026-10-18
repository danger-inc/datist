#!/usr/bin/env bash
# datist entfernen. Termine/Anmeldung (~/.local/share/kalender, ~/.config/kalender) bleiben.
set -euo pipefail
RICE="$HOME/.local/share/rice-apps"
pkill -f "^python3 $RICE/calendar/ui.py" || true
rm -rf "$RICE/calendar"
rm -f "$HOME/.local/bin/datist" "$HOME/.local/share/applications/datist.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/datist.svg"
# gemeinsame Bausteine nur entfernen, wenn keine andere Suite-App (musicalist) sie noch braucht
if [ ! -d "$RICE/music" ]; then
    rm -rf "$RICE/fonts" "$RICE/tui.py" "$RICE/glass.py" "$RICE/__pycache__"
    rmdir "$RICE" 2>/dev/null || true
fi
echo "datist entfernt. Deine Termine liegen weiter in ~/.local/share/kalender."
