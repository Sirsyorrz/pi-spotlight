#!/usr/bin/env bash
# hyprland.sh — add a keybind to Hyprland config
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

HYPR_CONF="${HOME}/.config/hypr/hyprland.conf"

if [[ ! -f "$HYPR_CONF" ]]; then
    echo "⚠  Hyprland config not found at $HYPR_CONF"
    echo "   Please add manually:  bind = Alt, Space, exec, bash $TOGGLE"
    return 1 2>/dev/null || exit 1
fi

# Don't add duplicate
if grep -qF "spotlight-chat" "$HYPR_CONF"; then
    echo "✓ Hyprland keybind already present in $HYPR_CONF"
    return 0 2>/dev/null || exit 0
fi

cat >> "$HYPR_CONF" << EOF

# spotlight-chat
bind = Alt, Space, exec, bash $TOGGLE
EOF

echo "✓ Hyprland keybind added to $HYPR_CONF (Alt+Space)"
echo "  Reload Hyprland config (hyprctl reload) or re-login to activate."
