#!/usr/bin/env bash
# datist (~/.local/share/rice-apps/calendar): blendet ein/aus. Läuft danach im Hintergrund weiter (Abgleich).
exec python3 "$HOME/.local/share/rice-apps/calendar/ui.py" "$@"
