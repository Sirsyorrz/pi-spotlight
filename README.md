# spotlight-chat

A macOS Spotlight-style overlay for [`pi`](https://github.com/anthropics/claude-code) (Claude Code) on Linux.  
Press **Alt+Space** anywhere → ask a question or drop into a full interactive agent session.

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
- **Agent mode** — full interactive `pi` session via PTY, ANSI colours rendered live
- **Universal installer** — auto-detects KDE, GNOME, Hyprland, Sway, i3, XFCE, or any X11/Wayland environment
- **Settings panel** — model picker, tool permissions, working directory, `pi` binary auto-discovery
- **Config persistence** — preferences saved to `~/.config/spotlight-chat/config.json`
- **PyQt5 / PyQt6** — works with either; falls back automatically

---

## Requirements

| Dependency | Notes |
|---|---|
| `python3` | 3.8+ |
| `PyQt5` or `PyQt6` | `pip install PyQt5` |
| [`pi`](https://github.com/anthropics/claude-code) | `npm install -g @anthropic-ai/claude-code` |

---

## Install

```bash
git clone https://github.com/Sirsyorrz/spotlight-chat
cd spotlight-chat
bash install.sh
```

The installer will:

1. Check all dependencies and report anything missing
2. Create an XDG autostart entry (`~/.config/autostart/spotlight-chat.desktop`)
3. Register the **Alt+Space** hotkey for your desktop environment
4. Print manual instructions if your DE can't be auto-configured

Then start it immediately (or log out/in for autostart to kick in):

```bash
bash toggle.sh
```

### Supported environments

| Desktop | Hotkey method |
|---|---|
| KDE Plasma | `kwriteconfig5` → `khotkeysrc` |
| GNOME | `gsettings` custom-keybindings |
| Hyprland | Appended to `hyprland.conf` |
| Sway | Appended to `~/.config/sway/config` |
| i3 | Appended to `~/.config/i3/config` |
| XFCE | `xfconf-query` on keyboard-shortcuts channel |
| Generic X11 | `xbindkeys` (installed separately) |
| Generic Wayland | Manual instructions printed |

---

## Usage

### Quick mode

Press **Alt+Space**, type a question, press **Enter**. The response streams in below the input bar with thinking blocks collapsed.

### Agent mode

Click **⚡ Agent** in the header (or press **Ctrl+A**) to open a full `pi` terminal session. Output is rendered with full ANSI colour support. Type at the bottom bar and press **Enter** to send.

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

Settings are saved to `~/.config/spotlight-chat/config.json`:

```json
{
  "model": "anthropic/claude-sonnet-4-5",
  "quick_tools": "read",
  "agent_cwd": "~",
  "pi_bin": "~/.npm/bin/pi",
  "font_family": "JetBrains Mono",
  "font_size": 13,
  "window_width": 720,
  "position_y_fraction": 0.15
}
```

You can edit this file directly or use the in-app settings panel.

---

## Uninstall

### 1. Stop the running daemon

```bash
pkill -f spotlight.py
```

### 2. Remove autostart entry

```bash
rm -f ~/.config/autostart/spotlight-chat.desktop
```

### 3. Remove saved config

```bash
rm -rf ~/.config/spotlight-chat
```

### 4. Remove the hotkey (per DE)

**KDE** — open *System Settings → Shortcuts → Custom Shortcuts*, find **Spotlight Chat** and delete it.

**GNOME**
```bash
# list custom bindings to find the right index (e.g. custom0)
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings

# remove the binding (replace custom0 with the correct entry)
SCHEMA="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
PATH_="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
gsettings reset "${SCHEMA}:${PATH_}" name
gsettings reset "${SCHEMA}:${PATH_}" command
gsettings reset "${SCHEMA}:${PATH_}" binding

# remove from the list (set to empty or remove the entry)
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "[]"
```

**Hyprland** — remove the two lines added to `~/.config/hypr/hyprland.conf`:
```
bind = Alt, Space, exec, bash /path/to/toggle.sh
exec-once = python3 /path/to/spotlight.py --daemon
```

**Sway** — remove the two lines added to `~/.config/sway/config`:
```
bindsym Alt+space exec bash /path/to/toggle.sh
exec python3 /path/to/spotlight.py --daemon
```

**i3** — remove the two lines added to `~/.config/i3/config`:
```
bindsym Alt+space exec bash /path/to/toggle.sh
exec --no-startup-id python3 /path/to/spotlight.py --daemon
```

**XFCE**
```bash
xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/<Alt>space" --reset
```

**xbindkeys (generic X11)**
```bash
# remove the spotlight-chat block from ~/.xbindkeysrc, then reload
pkill xbindkeys && xbindkeys
```

### 5. Delete the repo

```bash
rm -rf /path/to/spotlight-chat
```

---

## How it works

- `spotlight.py` runs as a **background daemon** — a Qt app with `QuitOnLastWindowClosed=False`
- A **Unix socket** (`/tmp/spotlight-chat-<uid>.sock`) receives `toggle` / `show` / `hide` commands
- `toggle.sh` sends the toggle signal; if the daemon isn't running it starts it first
- **Quick mode** spawns `pi --mode json -p "..."` and streams JSON events line by line
- **Agent mode** spawns `pi` inside a **PTY** (`pty.openpty()`), reads raw bytes, and converts ANSI escape codes to HTML spans for the output widget

### File structure

```
spotlight-chat/
├── spotlight.py          # single-file app (quick + agent mode)
├── install.sh            # universal installer entry point
├── toggle.sh             # send toggle signal (used by hotkey)
├── install/
│   ├── detect.sh         # echoes: kde | gnome | hyprland | sway | i3 | xfce | x11 | wayland | unknown
│   ├── deps_check.sh     # checks python3, PyQt5/6, pi binary
│   ├── kde.sh
│   ├── gnome.sh
│   ├── hyprland.sh
│   ├── sway_i3.sh
│   ├── xfce.sh
│   └── xbindkeys.sh      # generic X11 fallback
└── README.md
```

---

## License

MIT
