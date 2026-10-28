#!/usr/bin/env bash
# datist (~/.local/share/rice-apps/calendar): blendet ein/aus. Läuft danach im Hintergrund weiter (Abgleich).
# Kommandozeile ohne Oberfläche: datist --next | --waybar | --bar-hide | --agenda [N] | --json [N]
case "${1:-}" in
    --next|--waybar|--bar-hide|--bar-info|--bar-off|--bar-on|--bar-show-all|--agenda|--json) exec python3 "$HOME/.local/share/rice-apps/calendar/datist_cli.py" "$@" ;;
esac
# gtk4-layer-shell vorladen (nur für die Desktop-Karte), falls vorhanden – nur unter Wayland
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    for p in /usr/lib/libgtk4-layer-shell.so.0 /usr/lib64/libgtk4-layer-shell.so.0 /usr/lib/*-linux-gnu/libgtk4-layer-shell.so.0 \
             /usr/local/lib/libgtk4-layer-shell.so.0 /usr/local/lib/*-linux-gnu/libgtk4-layer-shell.so.0 /usr/local/lib64/libgtk4-layer-shell.so.0; do
        [ -e "$p" ] && { export LD_PRELOAD="$p${LD_PRELOAD:+:$LD_PRELOAD}"; break; }
    done
fi
exec python3 "$HOME/.local/share/rice-apps/calendar/ui.py" "$@"
