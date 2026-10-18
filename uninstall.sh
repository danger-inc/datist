#!/usr/bin/env bash
# kalender entfernen. Termine/Anmeldung (~/.local/share/kalender, ~/.config/kalender) bleiben.
set -euo pipefail
pkill -f "^python3 $HOME/.local/share/rice-apps/calendar/ui.py" || true
rm -rf "$HOME/.local/share/rice-apps/calendar"
rm -f "$HOME/.local/bin/kalender" "$HOME/.local/share/applications/kalender.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/kalender.svg"
echo "kalender entfernt. Deine Termine liegen weiter in ~/.local/share/kalender."
