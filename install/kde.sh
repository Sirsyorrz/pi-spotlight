#!/usr/bin/env bash
# kde.sh — register hotkey on KDE Plasma (Wayland or X11)
# Supports both Plasma 5 (kwriteconfig5) and Plasma 6 (kwriteconfig6)
# Args: $1 = path to toggle.sh

TOGGLE="$1"

# ── Detect kwriteconfig version ───────────────────────────────────────────────
if command -v kwriteconfig6 &>/dev/null; then
    KWRITE="kwriteconfig6"
    QDBUS="qdbus6"
elif command -v kwriteconfig5 &>/dev/null; then
    KWRITE="kwriteconfig5"
    QDBUS="qdbus"
else
    echo "⚠  kwriteconfig5/6 not found. Cannot auto-register KDE shortcut."
    echo ""
    echo "   ── Manual KDE Shortcut Setup ──────────────────────────────────────"
    echo "   1. Open System Settings → Shortcuts → Custom Shortcuts"
    echo "   2. Click Edit → New → Global Shortcut → Command/URL"
    echo "   3. Name it: pi-spotlight"
    echo "   4. In the 'Trigger' tab, press: Alt+Space"
    echo "   5. In the 'Action' tab, set Command to:"
    echo "      bash $TOGGLE"
    echo "   6. Click Apply"
    echo "   ────────────────────────────────────────────────────────────────────"
    exit 1
fi

# ── Plasma 6: use kglobalshortcutsrc with a .desktop action ──────────────────
# Plasma 6 dropped khotkeysrc for global shortcuts; the modern way is to
# register a .desktop file in /usr/local/share/applications (or ~/.local/share)
# and bind it in kglobalshortcutsrc.

DESKTOP_NAME="pi-spotlight-toggle"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/${DESKTOP_NAME}.desktop"

mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=pi-spotlight Toggle
Comment=Toggle the pi-spotlight overlay
Exec=bash $TOGGLE
Icon=utilities-terminal
NoDisplay=true
EOF
echo "✓ Desktop entry created: $DESKTOP_FILE"

# ── Clear any existing Alt+Space conflict in kglobalshortcutsrc ──────────────
if [[ -f "$HOME/.config/kglobalshortcutsrc" ]]; then
    # Replace any other entry that claims Alt+Space (not our own group)
    python3 - "$HOME/.config/kglobalshortcutsrc" "${DESKTOP_NAME}.desktop" << 'PYEOF'
import sys, re
path, our_group = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
# Remove Alt+Space from any section that isn't ours
lines = content.split('\n')
current_group = ''
result = []
for line in lines:
    m = re.match(r'^\[(.+?)\]', line)
    if m:
        current_group = m.group(1)
    if current_group != our_group and re.match(r'^_launch=Alt\+Space', line):
        line = re.sub(r'Alt\+Space', 'none', line, count=1)
        print(f'  cleared Alt+Space from [{current_group}]', file=sys.stderr)
    result.append(line)
with open(path, 'w') as f:
    f.write('\n'.join(result))
PYEOF
fi

# Register Alt+Space in kglobalshortcutsrc
KGLOBAL="$HOME/.config/kglobalshortcutsrc"
"$KWRITE" --file kglobalshortcutsrc \
    --group "services" --group "${DESKTOP_NAME}.desktop" \
    --key "_launch" \
    "Alt+Space,none,pi-spotlight Toggle"
echo "✓ Shortcut written to kglobalshortcutsrc: Alt+Space"

# Reload KDE shortcut daemon
if command -v "$QDBUS" &>/dev/null; then
    "$QDBUS" org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.reloadConfig 2>/dev/null \
        || "$QDBUS" org.kde.kglobalaccel /component/kglobalaccel invokeAction reloadConfig 2>/dev/null \
        || true
    echo "✓ kglobalaccel reloaded"
fi

echo ""
echo "  Shortcut: Alt+Space → pi-spotlight"
echo "  If Alt+Space conflicts with another shortcut (e.g. KRunner),"
echo "  open System Settings → Shortcuts and reassign it."
