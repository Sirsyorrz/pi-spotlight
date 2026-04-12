#!/usr/bin/env bash
# xbindkeys.sh — generic X11 hotkey via xbindkeys
# Args: $1 = path to toggle.sh

set -e
TOGGLE="$1"

if ! command -v xbindkeys &>/dev/null; then
    echo "⚠  xbindkeys not found."
    echo "   Install it (e.g. sudo apt install xbindkeys) then re-run."
    return 1 2>/dev/null || exit 1
fi

XBINDKEYS_RC="${HOME}/.xbindkeysrc"

# Don't add duplicate
if [[ -f "$XBINDKEYS_RC" ]] && grep -qF "spotlight-chat" "$XBINDKEYS_RC"; then
    echo "✓ xbindkeys entry already present in $XBINDKEYS_RC"
else
    cat >> "$XBINDKEYS_RC" << EOF

# spotlight-chat
"bash $TOGGLE"
    Alt + space
EOF
    echo "✓ xbindkeys entry added to $XBINDKEYS_RC"
fi

# Autostart xbindkeys via XDG autostart
AUTOSTART_DIR="${HOME}/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
XBIND_DESKTOP="${AUTOSTART_DIR}/xbindkeys.desktop"
if [[ ! -f "$XBIND_DESKTOP" ]]; then
    cat > "$XBIND_DESKTOP" << EOF
[Desktop Entry]
Type=Application
Name=xbindkeys
Exec=xbindkeys
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
    echo "✓ xbindkeys autostart entry created"
fi

# Restart xbindkeys immediately
pkill -x xbindkeys 2>/dev/null || true
sleep 0.3
xbindkeys &
echo "✓ xbindkeys started (Alt+Space → spotlight-chat)"
