#!/bin/bash

# User services do not always inherit the graphical-session environment, and
# the Wayland socket number can change between logins (wayland-0, wayland-1,
# ...). Discover it each time instead of pinning it to one login session.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

if [ -z "${WAYLAND_DISPLAY:-}" ] || [ ! -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
    WAYLAND_SOCKET=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s \
        -name 'wayland-[0-9]*' -printf '%f\n' 2>/dev/null | sort -V | tail -n 1)
    [ -n "$WAYLAND_SOCKET" ] || exit 0
    export WAYLAND_DISPLAY="$WAYLAND_SOCKET"
fi

STATE_DIR="$HOME/.cache/idle-off-rgb"
STATE_FILE="$STATE_DIR/off-by-idle"
RGB_SNAPSHOT="$STATE_DIR/pre-idle.orp"
if ! DPMS_STATE=$(kscreen-doctor --dpms show 2>/dev/null); then
    exit 0
fi

if grep -q "off" <<<"$DPMS_STATE"; then
    if [ ! -f "$STATE_FILE" ]; then
        mkdir -p "$STATE_DIR"
        SNAPSHOT_TMP="$STATE_DIR/pre-idle.tmp.orp"

        # Do not switch the lights off unless their current state was saved;
        # otherwise there would be no reliable state to restore on wake.
        if openrgb --save-profile "$SNAPSHOT_TMP" \
            && mv -f "$SNAPSHOT_TMP" "$RGB_SNAPSHOT" \
            && openrgb --device 0 --mode off --device 1 --mode off --device 2 --mode static --color 000000; then
            touch "$STATE_FILE"
        else
            rm -f "$SNAPSHOT_TMP"
        fi
    fi
else
    if [ -f "$STATE_FILE" ]; then
        if [ -s "$RGB_SNAPSHOT" ] && openrgb --profile "$RGB_SNAPSHOT"; then
            rm -f "$STATE_FILE"
        fi
    fi
fi
