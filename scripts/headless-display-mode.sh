#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -u

# Toggle only desktop presentation resources. Local LLM inference remains active.
script_path="$(readlink -f "${BASH_SOURCE[0]}")"
script_dir="$(dirname -- "$script_path")"
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/headless-display-mode"
RGB_SNAPSHOT="$STATE_DIR/pre-headless.orp"
SNAPSHOT_TMP="$RGB_SNAPSHOT.tmp"
SNAPSHOT_FILE="${SNAPSHOT_TMP}.orp"
ACTIVE_MARKER="$STATE_DIR/active"
RGB_OFF_MARKER="$STATE_DIR/rgb-off-applied"
PROFILE_DIR="${OPENRGB_PROFILE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/OpenRGB/profiles}"

session_is_locked() {
    local status

    status="$(timeout 5 /usr/bin/noctalia msg status 2>/dev/null)" || return 1
    /usr/bin/jq -e '.locked == true' <<<"$status" >/dev/null
}

displays_are_off() {
    local monitors

    monitors="$(timeout 5 /usr/bin/hyprctl -j monitors 2>/dev/null)" || return 1
    /usr/bin/jq -e 'length > 0 and all(.[]; .dpmsStatus == false)' <<<"$monitors" >/dev/null
}

displays_are_on() {
    local monitors

    monitors="$(timeout 5 /usr/bin/hyprctl -j monitors 2>/dev/null)" || return 1
    /usr/bin/jq -e 'any(.[]; .dpmsStatus == true)' <<<"$monitors" >/dev/null
}

restore_rgb_profile() (
    local profile="$1"
    local runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    local output

    # Serialize with wallpaper changes, then use the generic adapter because
    # OpenRGB 1.0's profile loader reports success without changing hardware.
    exec 9>"$runtime_dir/openrgb-wallpaper-profile.lock"
    if ! /usr/bin/flock -w 15 9; then
        logger -t headless-display-mode "Timed out waiting for OpenRGB profile lock"
        return 1
    fi

    output="$(timeout 40 "$script_dir/openrgb-apply-profile" "$profile" 2>&1)"
    if [[ $? -eq 0 ]]; then
        logger -t headless-display-mode "Restored ${profile##*/} through hardware-verified SDK adapter"
        return 0
    fi

    logger -t headless-display-mode "RGB restore through profile adapter failed: ${output//$'\n'/; }"
    return 1
)

# Serialize RGB writes when input arrives during an Off application. Native
# monitor wake runs independently, so it never waits for this lock or SMBus.
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
exec 8>"$runtime_dir/headless-display-mode-transition.lock"
if ! /usr/bin/flock -w 120 8; then
    logger -t headless-display-mode "Timed out waiting for the display/RGB transition lock"
    exit 1
fi

case "${1:-}" in
    off|rgb-off)
        # Noctalia can replay the locked_timeout action shortly after unlock.
        # Ignore that stale callback so it cannot overwrite a restored profile.
        if ! session_is_locked; then
            logger -t headless-display-mode "Ignored RGB-off request because the session is unlocked"
            exit 0
        fi
        # The observer may have sampled DPMS before a keypress woke the screen.
        # RGB-only calls must never turn the screen back off.
        if [[ "$1" == rgb-off ]] && ! displays_are_off; then
            exit 0
        fi
        if [[ -e "$ACTIVE_MARKER" && -e "$RGB_OFF_MARKER" ]]; then
            if [[ "$1" == off ]]; then
                /usr/bin/noctalia msg dpms-off
            fi
            exit 0
        fi

        mkdir -p "$STATE_DIR"
        if [[ ! -e "$ACTIVE_MARKER" ]]; then
            # OpenRGB appends .orp to the name supplied to --save-profile.
            # Keep the basename separate so the temporary file is predictable.
            rm -f -- "$SNAPSHOT_FILE"

            # A new OpenRGB process cannot read the IT5711's Direct colors
            # back from hardware and would save the motherboard as black.
            # Snapshot the known active wallpaper profile itself instead.
            runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
            active_profile_file="$runtime_dir/openrgb-wallpaper-profile.current"
            active_profile=""
            if [[ -s "$active_profile_file" ]]; then
                active_profile="$(<"$active_profile_file")"
            fi

            if [[ ! -s "$active_profile" ]] \
                || ! cp -- "$active_profile" "$RGB_SNAPSHOT"; then
                rm -f -- "$SNAPSHOT_FILE"
                logger -t headless-display-mode "Known active RGB profile unavailable; preserving the current lighting state"
                exit 1
            fi
            touch "$ACTIVE_MARKER"
        fi
        if [[ "$1" == off ]]; then
            /usr/bin/noctalia msg dpms-off
        fi
        if ! restore_rgb_profile "$PROFILE_DIR/off.json"; then
            logger -t headless-display-mode "RGB off application failed; leaving displays powered off and preserving the restore snapshot"
            exit 1
        fi
        touch "$RGB_OFF_MARKER"
        # A wake can arrive during the RGB write. Restore immediately rather
        # than leave the Off profile active until the next observer tick.
        if [[ "$1" == rgb-off ]] && displays_are_on; then
            if restore_rgb_profile "$RGB_SNAPSHOT"; then
                rm -f -- "$ACTIVE_MARKER" "$RGB_OFF_MARKER"
            else
                exit 1
            fi
        fi
        ;;
    on|rgb-on)
        if [[ "$1" == on ]]; then
            /usr/bin/noctalia msg dpms-on
        elif ! displays_are_on; then
            exit 0
        fi

        # Recover a snapshot left by an interrupted/older off transition.
        # OpenRGB wrote this exact .orp file before the previous script could
        # promote it to the final snapshot name.
        if [[ ! -e "$ACTIVE_MARKER" && ! -e "$RGB_SNAPSHOT" && -s "$SNAPSHOT_FILE" ]]; then
            if mv -f -- "$SNAPSHOT_FILE" "$RGB_SNAPSHOT"; then
                touch "$ACTIVE_MARKER"
            else
                logger -t headless-display-mode "Unable to promote pending RGB snapshot"
                exit 1
            fi
        fi

        if [[ -e "$ACTIVE_MARKER" && -s "$RGB_SNAPSHOT" ]]; then
            if restore_rgb_profile "$RGB_SNAPSHOT"; then
                rm -f -- "$ACTIVE_MARKER" "$RGB_OFF_MARKER"
            else
                logger -t headless-display-mode "RGB restore failed; keeping recovery marker for retry"
                exit 1
            fi
        elif [[ -e "$ACTIVE_MARKER" ]]; then
            logger -t headless-display-mode "RGB restore snapshot missing; keeping recovery marker for retry"
            exit 1
        fi
        ;;
    *)
        printf 'Usage: %s {off|on|rgb-off|rgb-on}\n' "$0" >&2
        exit 2
        ;;
esac
