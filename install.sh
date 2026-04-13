#!/usr/bin/env bash
# install.sh — pi-spotlight installer
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOGGLE="$SCRIPT_DIR/toggle.sh"

echo "══════════════════════════════════════════════════════════"
echo "  pi-spotlight  —  installer"
echo "══════════════════════════════════════════════════════════"
echo

# ── 0. Dependency check ───────────────────────────────────────────────────────
bash "$SCRIPT_DIR/install/deps_check.sh"

read -rp "  Continue installation? [Y/n] " confirm
confirm="${confirm:-Y}"
if [[ "${confirm,,}" != "y" ]]; then
    echo "Installation cancelled."
    exit 0
fi
echo

# ── 1. Make scripts executable ───────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/toggle.sh"
chmod +x "$SCRIPT_DIR/pi-spotlight.py"
for f in "$SCRIPT_DIR/install/"*.sh; do chmod +x "$f"; done
echo "✓ Scripts marked executable"
echo

# ── 2. Print shortcut setup instructions ─────────────────────────────────────
DE=$(bash "$SCRIPT_DIR/install/detect.sh")
echo "  Detected environment: $DE"
echo

echo "══════════════════════════════════════════════════════════"
echo "  Manual shortcut setup (one-time)"
echo "══════════════════════════════════════════════════════════"
echo
echo "  Command to bind:  $TOGGLE"
echo "  Recommended key:  Alt+Space  (or any key you prefer)"
echo

case "$DE" in
    kde)
        echo "  KDE Plasma:"
        echo "  1. Open System Settings → Shortcuts → Custom Shortcuts"
        echo "  2. Edit → New → Global Shortcut → Command/URL"
        echo "  3. Name: pi-spotlight"
        echo "  4. Trigger tab → click the button → press Alt+Space"
        echo "  5. Action tab → Command: $TOGGLE"
        echo "  6. Apply"
        ;;
    gnome)
        echo "  GNOME:"
        echo "  1. Open Settings → Keyboard → View and Customise Shortcuts"
        echo "  2. Custom Shortcuts → +"
        echo "  3. Name: pi-spotlight"
        echo "  4. Command: $TOGGLE"
        echo "  5. Shortcut: Alt+Space"
        ;;
    hyprland)
        echo "  Hyprland — add to ~/.config/hypr/hyprland.conf:"
        echo "    bind = ALT, Space, exec, $TOGGLE"
        ;;
    sway|i3)
        echo "  $DE — add to your config:"
        echo "    bindsym Alt+Space exec $TOGGLE"
        ;;
    xfce)
        echo "  XFCE:"
        echo "  1. Open Settings → Keyboard → Application Shortcuts"
        echo "  2. Add → Command: $TOGGLE → press Alt+Space"
        ;;
    *)
        echo "  Bind this command to a key in your WM/DE settings:"
        echo "    $TOGGLE"
        ;;
esac

echo
echo "══════════════════════════════════════════════════════════"
echo "  Done! Set up the shortcut above, then press it to open"
echo "  pi-spotlight. No daemon or autostart needed."
echo "══════════════════════════════════════════════════════════"
