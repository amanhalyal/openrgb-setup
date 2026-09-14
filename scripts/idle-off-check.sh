#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later

set -u

script_path="$(readlink -f "${BASH_SOURCE[0]}")"
script_dir="$(dirname -- "$script_path")"

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

if ! DPMS_STATE=$(kscreen-doctor --dpms show 2>/dev/null); then
    exit 0
fi

if grep -q "off" <<<"$DPMS_STATE"; then
    exec "$script_dir/headless-display-mode.sh" off
else
    exec "$script_dir/headless-display-mode.sh" on
fi
