#!/usr/bin/env bash
# kalender (~/.local/share/rice-apps/calendar): blendet ein/aus. Läuft danach im Hintergrund weiter (Abgleich).
exec python3 "$HOME/.local/share/rice-apps/calendar/ui.py" "$@"
