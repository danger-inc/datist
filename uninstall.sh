#!/usr/bin/env bash
# datist entfernen. Termine/Anmeldung (~/.local/share/kalender, ~/.config/kalender) bleiben.
set -euo pipefail
pkill -f "^python3 $HOME/.local/share/rice-apps/calendar/ui.py" || true
rm -rf "$HOME/.local/share/rice-apps/calendar"
rm -f "$HOME/.local/bin/datist" "$HOME/.local/share/applications/datist.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/datist.svg"
echo "datist entfernt. Deine Termine liegen weiter in ~/.local/share/kalender."
