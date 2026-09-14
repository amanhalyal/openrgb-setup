#!/usr/bin/env bash
set -u

# Toggle only desktop presentation resources. Local LLM inference remains active.
STATE_DIR="/home/aman/.cache/headless-display-mode"
RGB_SNAPSHOT="$STATE_DIR/pre-headless.orp"
SNAPSHOT_TMP="$RGB_SNAPSHOT.tmp"
SNAPSHOT_FILE="${SNAPSHOT_TMP}.orp"
ACTIVE_MARKER="$STATE_DIR/active"

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

    output="$(timeout 40 /home/aman/.local/bin/openrgb-apply-profile "$profile" 2>&1)"
    if [[ $? -eq 0 ]]; then
        logger -t headless-display-mode "Restored ${profile##*/} through direct profile adapter"
        return 0
    fi

    logger -t headless-display-mode "RGB restore through profile adapter failed: ${output//$'\n'/; }"
    return 1
)

case "${1:-}" in
    off)
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
                logger -t headless-display-mode "Known active RGB profile unavailable; leaving displays and lighting unchanged"
                exit 1
            fi
            touch "$ACTIVE_MARKER"
        fi
        /usr/bin/noctalia msg dpms-off
        # Apply hardware off/black modes directly. The migrated JSON off profile
        # is not sufficient for the Gigabyte IT5711/ARGB chain, and the DRAM
        # controllers expose a native Off mode that is more reliable here.
        if ! /usr/bin/openrgb --noautoconnect \
            --device 0 --mode off \
            --device 1 --mode off \
            --device "B850 GAMING X WIFI6E" --zone 0 --size 64 --mode direct --color 000000 \
            --device "B850 GAMING X WIFI6E" --zone 1 --size 64 --mode direct --color 000000 \
            --device "B850 GAMING X WIFI6E" --zone 2 --size 64 --mode direct --color 000000 \
            --device "B850 GAMING X WIFI6E" --zone 3 --size 64 --mode direct --color 000000 \
            --device "B850 GAMING X WIFI6E" --mode static --color 000000 >/dev/null 2>&1; then
            logger -t headless-display-mode "Direct RGB off application failed"
        fi
        ;;
    on)
        /usr/bin/noctalia msg dpms-on

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
                rm -f -- "$ACTIVE_MARKER"
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
        printf 'Usage: %s {off|on}\n' "$0" >&2
        exit 2
        ;;
esac
