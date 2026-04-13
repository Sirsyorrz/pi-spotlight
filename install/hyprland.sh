#!/usr/bin/env bash
# hyprland.sh — add a keybind to Hyprland config
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

HYPR_CONF="${HOME}/.config/hypr/hyprland.conf"

if [[ ! -f "$HYPR_CONF" ]]; then
    echo "⚠  Hyprland config not found at $HYPR_CONF"
    echo ""
    echo "   ── Manual Hyprland Shortcut Setup ──────────────────────────────────"
    echo "   1. Open your Hyprland config (usually ~/.config/hypr/hyprland.conf)"
    echo "   2. Add this line:"
    echo "      bind = Alt, Space, exec, bash $TOGGLE"
    echo "   3. Reload config:  hyprctl reload"
    echo "   ────────────────────────────────────────────────────────────────────────"
    return 1 2>/dev/null || exit 1
fi

# Don't add duplicate
if grep -qF "pi-spotlight" "$HYPR_CONF"; then
    echo "✓ Hyprland keybind already present in $HYPR_CONF"
    return 0 2>/dev/null || exit 0
fi

cat >> "$HYPR_CONF" << EOF

# pi-spotlight
bind = Alt, Space, exec, bash $TOGGLE
EOF

echo "✓ Hyprland keybind added to $HYPR_CONF (Alt+Space)"
echo "  Reload Hyprland config (hyprctl reload) or re-login to activate."
