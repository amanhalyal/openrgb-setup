#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

script_path="$(readlink -f "${BASH_SOURCE[0]}")"
script_dir="$(dirname -- "$script_path")"
state_dir="${XDG_CACHE_HOME:-$HOME/.cache}/headless-display-mode"

# Noctalia's native screen_off action owns display power and wakes immediately
# on input. This observer follows actual Hyprland DPMS state; it never blanks
# displays or depends on the custom-command resume callback.
if ! monitors="$(timeout 5 /usr/bin/hyprctl -j monitors 2>/dev/null)"; then
    exit 0
fi
if /usr/bin/jq -e 'length > 0 and all(.[]; .dpmsStatus == false)' <<<"$monitors" >/dev/null; then
    if [[ ! -e "$state_dir/active" || ! -e "$state_dir/rgb-off-applied" ]]; then
        exec "$script_dir/headless-display-mode.sh" rgb-off
    fi
elif /usr/bin/jq -e 'any(.[]; .dpmsStatus == true)' <<<"$monitors" >/dev/null; then
    if [[ -e "$state_dir/active" ]]; then
        exec "$script_dir/headless-display-mode.sh" rgb-on
    fi
fi
