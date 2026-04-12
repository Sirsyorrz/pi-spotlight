#!/usr/bin/env bash
# detect.sh — detect the current desktop environment
# Echoes one of: kde | gnome | hyprland | sway | i3 | xfce | x11 | wayland | unknown
# Usage: source detect.sh  OR  DE=$(bash detect.sh)

detect_de() {
    # Check compositor / WM-specific env vars first (most reliable)
    if [[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]]; then
        echo "hyprland"; return
    fi

    if [[ -n "$SWAYSOCK" ]]; then
        echo "sway"; return
    fi

    # XDG_CURRENT_DESKTOP is set by most DEs
    local desktop="${XDG_CURRENT_DESKTOP,,}"  # lowercase

    case "$desktop" in
        *kde*|*plasma*)
            echo "kde"; return ;;
        *gnome*)
            echo "gnome"; return ;;
        *xfce*)
            echo "xfce"; return ;;
        *i3*)
            echo "i3"; return ;;
        *sway*)
            echo "sway"; return ;;
        *hyprland*)
            echo "hyprland"; return ;;
    esac

    # DESKTOP_SESSION fallback
    local session="${DESKTOP_SESSION,,}"
    case "$session" in
        *plasma*|*kde*)   echo "kde";      return ;;
        *gnome*)          echo "gnome";    return ;;
        *xfce*)           echo "xfce";     return ;;
        *i3*)             echo "i3";       return ;;
        *sway*)           echo "sway";     return ;;
        *hyprland*)       echo "hyprland"; return ;;
    esac

    # Check running process names
    if pgrep -x "plasmashell"  &>/dev/null; then echo "kde";       return; fi
    if pgrep -x "gnome-shell"  &>/dev/null; then echo "gnome";     return; fi
    if pgrep -x "xfce4-session"&>/dev/null; then echo "xfce";      return; fi
    if pgrep -x "i3"           &>/dev/null; then echo "i3";        return; fi
    if pgrep -x "sway"         &>/dev/null; then echo "sway";      return; fi
    if pgrep -x "Hyprland"     &>/dev/null; then echo "hyprland";  return; fi

    # Generic Wayland vs X11
    if [[ -n "$WAYLAND_DISPLAY" ]]; then
        echo "wayland"; return
    fi
    if [[ -n "$DISPLAY" ]]; then
        echo "x11"; return
    fi

    echo "unknown"
}

detect_de
