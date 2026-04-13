# pi-spotlight

A macOS Spotlight-style overlay for [`pi`](https://github.com/anthropics/claude-code) (Claude Code) on Linux.  
Bind it to any shortcut you like → ask a question or drop into a full interactive agent session.

```
┌──────────────────────────────────────────────────────────────┐
│  ⌘  Ask anything…              [Sonnet 4.5 ▾] [⚡ Agent] [⚙] │
├──────────────────────────────────────────────────────────────┤
│  Here's a quick answer to your question...                   │
│  The reason this works is because...                         │
└──────────────────────────────────────────────────────────────┘
```

---

## Features

- **Quick mode** — single-prompt, streamed JSON response with thinking support
- **Agent mode** — full VT100 terminal via PTY (`pyte`), rendered with QPainter — supports all ANSI colours and cursor movement
- **No daemon / no autostart** — `toggle.sh` launches the app on demand; bind it to a key and you're done
- **Settings panel** — model picker, tool permissions, working directory, `pi` binary auto-discovery
- **Config persistence** — preferences saved to `~/.config/pi-spotlight/config.json`
- **PyQt5 / PyQt6** — works with either; falls back automatically

---

## Requirements

| Dependency | Notes |
|---|---|
| `python3` | 3.8+ |
| `PyQt5` or `PyQt6` | `pip install PyQt5` |
| `pyte` | `pip install pyte` (VT100 terminal emulator for agent mode) |
| [`pi`](https://github.com/anthropics/claude-code) | `npm install -g @anthropic-ai/claude-code` |

---

## Install

```bash
git clone https://github.com/Sirsyorrz/pi-spotlight
cd pi-spotlight
bash install.sh
```

The installer will:

1. Check all dependencies and report anything missing
2. Detect your desktop environment
3. Print the exact steps to bind **Alt+Space** → `toggle.sh` in your DE

No autostart entry is created — the app starts when you press your shortcut and exits when you close it.

### Bind the hotkey manually

After running `install.sh`, follow the printed instructions for your DE. Bind `toggle.sh` to whatever key combination you prefer. Quick reference:

| Desktop | How to bind |
|---|---|
| KDE Plasma | System Settings → Shortcuts → Custom Shortcuts → New → Global Shortcut → Command: `toggle.sh` |
| GNOME | Settings → Keyboard → Custom Shortcuts → + |
| Hyprland | `bind = ALT, Space, exec, /path/to/toggle.sh` in `hyprland.conf` |
| Sway / i3 | `bindsym <key> exec /path/to/toggle.sh` in config |
| XFCE | Settings → Keyboard → Application Shortcuts |
| Other | Bind `toggle.sh` to any key in your WM |

---

## Usage

### Quick mode

Press your shortcut, type a question, press **Enter**. The response streams in below the input bar with thinking blocks collapsed.

### Agent mode

Click **⚡ Agent** in the header (or press **Ctrl+A**) to open a full `pi` terminal session. The terminal is a proper VT100 emulator — full ANSI colour, cursor movement, and interactive prompts all work. Type at the bottom bar and press **Enter** to send.

```
┌──────────────────────────────────────────────────────────────┐
│  ⚡  Working directory: ~/projects/myapp      [⌘ Quick] [⚙]  │
├──────────────────────────────────────────────────────────────┤
│  > Reading src/main.py...                                    │
│  > Allow edit to src/main.py? [y/n]                         │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ❯ _type here, enter sends to pi_                            │
│  ↵ send  ·  ctrl+c interrupt  ·  esc hide  ·  ctrl+q quick  │
└──────────────────────────────────────────────────────────────┘
```

### Settings

Click **⚙** in the header to open the settings panel:

- **Default model** — choose from Sonnet 4.5, Sonnet 4.0, Haiku 3.5, Opus 4
- **Quick mode tools** — read-only (default) or all tools
- **Working directory** — starting directory for agent sessions
- **pi binary** — path to `pi`, or click **Detect** to auto-discover
- **Terminal font size** — adjusts agent output and input font

---

## Keyboard shortcuts

### Quick mode

| Key | Action |
|---|---|
| `Enter` | Submit query |
| `Esc` | Hide window |
| `Ctrl+L` | Clear query and response |
| `Ctrl+M` | Cycle through models |
| `Ctrl+A` | Switch to Agent mode |
| `Ctrl+C` | Stop running query |

### Agent mode

| Key | Action |
|---|---|
| `Enter` | Send line to pi |
| `Esc` | Hide window |
| `Ctrl+L` | Clear output |
| `Ctrl+C` | Send SIGINT to pi |
| `Ctrl+Q` | Switch to Quick mode |

---

## Configuration

Settings are saved to `~/.config/pi-spotlight/config.json`:

```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "quick_tools": "read",
  "agent_cwd": "~",
  "pi_bin": "",
  "font_family": "JetBrains Mono",
  "font_size": 13,
  "terminal_cols": 118,
  "terminal_rows": 34,
  "position_y_fraction": 0.10
}
```

You can edit this file directly or use the in-app settings panel.

---

## Uninstall

### 1. Remove saved config

```bash
rm -rf ~/.config/pi-spotlight
```

### 2. Remove the hotkey

Remove whatever shortcut you added in your DE settings pointing to `toggle.sh`.

**Hyprland** — remove from `~/.config/hypr/hyprland.conf`:
```
bind = ALT, Space, exec, /path/to/toggle.sh
```

**Sway / i3** — remove from your config:
```
bindsym Alt+Space exec /path/to/toggle.sh
```

### 3. Delete the repo

```bash
rm -rf /path/to/pi-spotlight
```

---

## How it works

- `toggle.sh` launches `pi-spotlight.py` directly — no background daemon or autostart entry needed
- A **Unix socket** (`/tmp/pi-spotlight-<uid>.sock`) is used so that pressing the hotkey a second time toggles the already-running window instead of opening a duplicate
- **Quick mode** spawns `pi --mode json -p "..."` and streams JSON events line by line
- **Agent mode** spawns `pi` inside a **PTY** (`pty.openpty()`), feeds raw bytes into a `pyte` VT100 screen, and renders each cell with QPainter — giving accurate colour, bold, and cursor rendering

### File structure

```
pi-spotlight/
├── pi-spotlight.py          # single-file app (quick + agent mode)
├── install.sh               # prints hotkey setup instructions for your DE
├── toggle.sh                # launch / toggle the window (bind this to Alt+Space)
├── install/
│   ├── detect.sh            # echoes: kde | gnome | hyprland | sway | i3 | xfce | x11 | wayland | unknown
│   ├── deps_check.sh        # checks python3, PyQt5/6, pyte, pi binary
│   ├── kde.sh
│   ├── gnome.sh
│   ├── hyprland.sh
│   ├── sway_i3.sh
│   ├── xfce.sh
│   └── xbindkeys.sh         # generic X11 fallback
└── README.md
```

---

## License

MIT
