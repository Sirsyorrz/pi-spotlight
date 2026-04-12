#!/usr/bin/env bash
# kde.sh — register hotkey on KDE Plasma (Wayland or X11)
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

if ! command -v kwriteconfig5 &>/dev/null; then
    echo "⚠  kwriteconfig5 not found. Cannot auto-register KDE shortcut."
    return 1 2>/dev/null || exit 1
fi

KHOTKEYS_RC="$HOME/.config/khotkeysrc"
LAST_ID=$(grep -oP '^\[Data_\K[0-9]+' "$KHOTKEYS_RC" 2>/dev/null | sort -n | tail -1)
NEW_ID=$(( ${LAST_ID:-0} + 1 ))

kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}" --key "Comment" "pi-spotlight toggle"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}" --key "Enabled" "true"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}" --key "Name"    "pi-spotlight"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}" --key "Type"    "SIMPLE_ACTION_DATA"

kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}Triggers0" --key "Key"  "Alt+Space"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}Triggers0" --key "Type" "SHORTCUT"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}Triggers0" --key "Uuid" "{$(cat /proc/sys/kernel/random/uuid)}"

kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}Actions0" --key "CommandURL" "bash $TOGGLE"
kwriteconfig5 --file khotkeysrc --group "Data_${NEW_ID}Actions0" --key "Type"       "COMMAND_URL"

if command -v qdbus &>/dev/null; then
    qdbus org.kde.khotkeys /khotkeys reread_configuration 2>/dev/null || true
fi

echo "✓ KDE shortcut registered: Alt+Space → pi-spotlight"
echo "  If it conflicts, open System Settings → Shortcuts → Custom Shortcuts"
echo "  and reassign the key manually for 'pi-spotlight'."
