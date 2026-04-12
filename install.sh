#!/usr/bin/env bash
# install.sh — universal spotlight-chat installer
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOGGLE="$SCRIPT_DIR/toggle.sh"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_AUTOSTART="$AUTOSTART_DIR/spotlight-chat.desktop"

echo "══════════════════════════════════════════════════════════"
echo "  spotlight-chat  —  universal installer"
echo "══════════════════════════════════════════════════════════"
echo

# ── 0. Dependency check ───────────────────────────────────────────────────────
bash "$SCRIPT_DIR/install/deps_check.sh"

# Allow continuing even with warnings (user may fix later)
read -rp "  Continue installation? [Y/n] " confirm
confirm="${confirm:-Y}"
if [[ "${confirm,,}" != "y" ]]; then
    echo "Installation cancelled."
    exit 0
fi
echo

# ── 1. Make scripts executable ───────────────────────────────────────────────
chmod +x "$TOGGLE"
chmod +x "$SCRIPT_DIR/spotlight.py"
chmod +x "$SCRIPT_DIR/install/detect.sh"
for f in "$SCRIPT_DIR/install/"*.sh; do chmod +x "$f"; done

# ── 2. XDG Autostart (works on KDE, GNOME, XFCE, most DEs) ──────────────────
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_AUTOSTART" << EOF
[Desktop Entry]
Type=Application
Name=Spotlight Chat
Comment=Quick AI query overlay
Exec=python3 $SCRIPT_DIR/spotlight.py --daemon
Icon=utilities-terminal
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
echo "✓ Autostart entry created: $DESKTOP_AUTOSTART"

# ── 3. Detect DE and register hotkey ─────────────────────────────────────────
DE=$(bash "$SCRIPT_DIR/install/detect.sh")
echo "  Detected environment: $DE"
echo

case "$DE" in
    kde)
        echo "── KDE Plasma ───────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/kde.sh" "$TOGGLE" || true
        ;;
    gnome)
        echo "── GNOME ────────────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/gnome.sh" "$TOGGLE" || true
        ;;
    hyprland)
        echo "── Hyprland ─────────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/hyprland.sh" "$TOGGLE" || true
        # Also add exec to hyprland.conf for autostart (more reliable than XDG there)
        HYPR_CONF="${HOME}/.config/hypr/hyprland.conf"
        if [[ -f "$HYPR_CONF" ]] && ! grep -qF "spotlight-chat.*daemon" "$HYPR_CONF"; then
            echo "" >> "$HYPR_CONF"
            echo "# spotlight-chat autostart" >> "$HYPR_CONF"
            echo "exec-once = python3 $SCRIPT_DIR/spotlight.py --daemon" >> "$HYPR_CONF"
            echo "✓ exec-once autostart added to $HYPR_CONF"
        fi
        ;;
    sway)
        echo "── Sway ─────────────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/sway_i3.sh" "$TOGGLE" "sway" || true
        SWAY_CONF="${HOME}/.config/sway/config"
        if [[ -f "$SWAY_CONF" ]] && ! grep -qF "spotlight-chat.*daemon" "$SWAY_CONF"; then
            echo "" >> "$SWAY_CONF"
            echo "# spotlight-chat autostart" >> "$SWAY_CONF"
            echo "exec python3 $SCRIPT_DIR/spotlight.py --daemon" >> "$SWAY_CONF"
            echo "✓ exec autostart added to $SWAY_CONF"
        fi
        ;;
    i3)
        echo "── i3 ───────────────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/sway_i3.sh" "$TOGGLE" "i3" || true
        I3_CONF="${HOME}/.config/i3/config"
        if [[ -f "$I3_CONF" ]] && ! grep -qF "spotlight-chat.*daemon" "$I3_CONF"; then
            echo "" >> "$I3_CONF"
            echo "# spotlight-chat autostart" >> "$I3_CONF"
            echo "exec --no-startup-id python3 $SCRIPT_DIR/spotlight.py --daemon" >> "$I3_CONF"
            echo "✓ exec autostart added to $I3_CONF"
        fi
        ;;
    xfce)
        echo "── XFCE ─────────────────────────────────────────────────────────────────"
        bash "$SCRIPT_DIR/install/xfce.sh" "$TOGGLE" || true
        ;;
    x11)
        echo "── Generic X11 (xbindkeys fallback) ─────────────────────────────────────"
        bash "$SCRIPT_DIR/install/xbindkeys.sh" "$TOGGLE" || true
        ;;
    wayland)
        echo "── Generic Wayland (unknown compositor) ─────────────────────────────────"
        echo "  ⚠ Could not identify your Wayland compositor."
        echo "  Please add the hotkey manually in your compositor's config:"
        echo "    Command: bash $TOGGLE"
        echo "    Key:     Alt+Space"
        ;;
    *)
        echo "── Unknown environment ───────────────────────────────────────────────────"
        echo "  ⚠ Could not detect your desktop environment."
        echo "  Please add the hotkey manually:"
        echo "    Command: bash $TOGGLE"
        echo "    Key:     Alt+Space"
        ;;
esac

echo
echo "══════════════════════════════════════════════════════════"
echo "  Installation complete!"
echo ""
echo "  Start now:     python3 $SCRIPT_DIR/spotlight.py --daemon"
echo "  Toggle:        bash $TOGGLE"
echo "  Hotkey:        Alt+Space  (after login / compositor reload)"
echo "══════════════════════════════════════════════════════════"
