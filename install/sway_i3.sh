#!/usr/bin/env bash
# sway_i3.sh — add a keybind to Sway or i3 config (same syntax)
# Args: $1 = path to toggle.sh   $2 = "sway" | "i3"

set -e
TOGGLE="$1"
WM="${2:-sway}"

if [[ "$WM" == "sway" ]]; then
    CONF="${HOME}/.config/sway/config"
else
    CONF="${HOME}/.config/i3/config"
fi

if [[ ! -f "$CONF" ]]; then
    echo "⚠  $WM config not found at $CONF"
    echo ""
    echo "   ── Manual $WM Shortcut Setup ────────────────────────────────────────────"
    echo "   1. Open your $WM config at $CONF"
    echo "   2. Add this line:"
    echo "      bindsym Alt+space exec bash $TOGGLE"
    echo "   3. Reload config:"
    if [[ "$WM" == "sway" ]]; then
        echo "      swaymsg reload"
    else
        echo "      i3-msg reload"
    fi
    echo "   ────────────────────────────────────────────────────────────────────────"
    return 1 2>/dev/null || exit 1
fi

if grep -qF "pi-spotlight" "$CONF"; then
    echo "✓ $WM keybind already present in $CONF"
    return 0 2>/dev/null || exit 0
fi

cat >> "$CONF" << EOF

# pi-spotlight
bindsym Alt+space exec bash $TOGGLE
EOF

echo "✓ $WM keybind added to $CONF (Alt+Space)"
echo "  Reload $WM config to activate."
