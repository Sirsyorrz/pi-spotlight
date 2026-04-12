#!/usr/bin/env bash
# gnome.sh — register a custom keyboard shortcut on GNOME (Wayland or X11)
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

if ! command -v gsettings &>/dev/null; then
    echo "⚠  gsettings not found. Cannot auto-register GNOME shortcut."
    return 1 2>/dev/null || exit 1
fi

SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA="${SCHEMA}.custom-keybinding"
BASE_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# Read existing list
existing=$(gsettings get $SCHEMA custom-keybindings 2>/dev/null || echo "@as []")

# Find next free slot index
idx=0
while gsettings get "${CUSTOM_SCHEMA}:${BASE_PATH}/custom${idx}/" name &>/dev/null 2>&1; do
    idx=$(( idx + 1 ))
done

BINDING_PATH="${BASE_PATH}/custom${idx}/"

# Write the new binding
gsettings set "${CUSTOM_SCHEMA}:${BINDING_PATH}" name    "pi-spotlight"
gsettings set "${CUSTOM_SCHEMA}:${BINDING_PATH}" command "bash $TOGGLE"
gsettings set "${CUSTOM_SCHEMA}:${BINDING_PATH}" binding "<Alt>space"

# Append to list
if [[ "$existing" == "@as []" || "$existing" == "[]" ]]; then
    new_list="['${BINDING_PATH}']"
else
    # Strip trailing ] and append
    new_list="${existing%]}, '${BINDING_PATH}']"
fi
gsettings set $SCHEMA custom-keybindings "$new_list"

echo "✓ GNOME shortcut registered: Alt+Space → pi-spotlight"
echo "  To change it: Settings → Keyboard → View and Customize Shortcuts → Custom Shortcuts"
