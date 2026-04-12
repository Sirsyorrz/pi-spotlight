#!/usr/bin/env bash
# xfce.sh — register a keyboard shortcut on XFCE via xfconf-query
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

if ! command -v xfconf-query &>/dev/null; then
    echo "⚠  xfconf-query not found. Cannot auto-register XFCE shortcut."
    return 1 2>/dev/null || exit 1
fi

CHANNEL="xfce4-keyboard-shortcuts"
PROPERTY="/commands/custom/<Alt>space"

xfconf-query -c "$CHANNEL" -p "$PROPERTY" -n -t string -s "bash $TOGGLE" 2>/dev/null \
    || xfconf-query -c "$CHANNEL" -p "$PROPERTY" -s "bash $TOGGLE"

echo "✓ XFCE shortcut registered: Alt+Space → pi-spotlight"
echo "  To change: Applications → Settings → Keyboard → Application Shortcuts"
