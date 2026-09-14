# Idle display and RGB control

## Purpose

Troubleshoot the inactive/locked desktop state where the monitors should power
off and PC lighting should be turned off.

## Intended behavior

Noctalia controls the idle sequence:

1. After 600 seconds (10 minutes), lock the session.
2. After 660 seconds (11 minutes), run the headless transition.
3. The transition saves the active OpenRGB profile, powers down both displays
   through DPMS, and directly applies hardware off/black modes to the RGB
   controllers.
4. On input/unlock, displays and the saved RGB profile are restored through the
   generic direct profile adapter.

The active configuration is in:

- `~/.config/noctalia/config.toml`
- `~/.local/bin/headless-display-mode.sh`

The older mechanism is retained only for reference:

- `~/.config/systemd/user/idle-off-check.timer`
- `~/.config/systemd/user/idle-off-check.service`
- `~/.local/bin/idle-off-check.sh`

The old timer is disabled. Do not enable both mechanisms, or they may compete
for display and RGB state.

## Active implementation

Noctalia invokes these commands from `~/.config/noctalia/config.toml`:

```toml
[idle.behavior.headless]
action = "command"
enabled = true
timeout = 660
locked_timeout = 60
command = "/home/aman/.local/bin/headless-display-mode.sh off"
resume_command = "/home/aman/.local/bin/headless-display-mode.sh on"
```

The script uses:

- `~/.cache/headless-display-mode/pre-headless.orp` for the last known active
  lighting state.
- `~/.cache/headless-display-mode/active` to record that this script switched
  the lights off and therefore owns the next restore.
- `~/.local/bin/openrgb-apply-profile` to translate the saved JSON profile into
  ordinary device operations because OpenRGB 1.0's profile loader is broken on
  this hardware.
- Direct hardware commands: native `off` for both DRAM controllers and resized
  static-black zones for the Gigabyte B850 motherboard/ARGB chain.
- `$XDG_RUNTIME_DIR/openrgb-wallpaper-profile.lock` to serialize access with
  the wallpaper-profile helper.
- `app-openrgb@autostart.service` for the OpenRGB tray and SDK server.

## Checks

```bash
noctalia msg status
hyprctl -j monitors | jq -r '.[] | [.name,.disabled,.dpmsStatus,.focused] | @tsv'
systemctl --user status idle-off-check.timer idle-off-check.service
find ~/.cache/headless-display-mode -maxdepth 1 -type f -printf '%f %s bytes\n'
```

Interpretation of Hyprland fields:

- `disabled: false` means the output remains configured/enabled.
- `dpmsStatus: false` means the output is DPMS-off.
- Therefore, an idle monitor can be configured but physically powered down.

Expected inactive state:

- Noctalia reports `locked: true`.
- Both monitors report `dpmsStatus: false`.
- `~/.cache/headless-display-mode/active` exists.
- `~/.cache/headless-display-mode/pre-headless.orp` exists.

## OpenRGB 1.0 profile migration and idle-off failure

On 2026-09-12, OpenRGB was upgraded from `1.0rc3-3.1` to `1.0-2.1`. The new
build migrated persistent profiles from legacy `.orp` files to JSON files under
`~/.config/OpenRGB/profiles/`, renaming the old files to `.orp.bak`.

The idle helper still requested the old `~/.config/OpenRGB/off.orp` path. The
headless transition therefore saved its restore snapshot but left the lights
blue. Updating the path to `off.json` made OpenRGB report success, but the
Gigabyte/ARGB chain still remained lit. The reliable solution is the direct
hardware sequence now in `headless-display-mode.sh`: native DRAM `off` mode and
static black across all motherboard ARGB zones.

Persistent JSON profiles remain appropriate for wallpaper changes. Temporary
restore snapshots remain `.orp` files by design.

The corrected direct sequence was rerun on 2026-09-12. OpenRGB detected both DRAM
controllers and the B850 motherboard, returned exit code 0, and the lights were
visually confirmed off.

## Investigation record: 2026-09-04

The monitors initially appeared active because `disabled: false` was read
without checking DPMS. Noctalia had in fact triggered the headless action:

```text
09:57 lock triggered
09:58 headless triggered
```

The state marker and RGB snapshot were present, confirming that the transition
ran. `kscreen-doctor --dpms show` hung during investigation, so Hyprland's JSON
state and Noctalia status were used instead.

## Investigation record: 2026-09-06 — RAM restored, motherboard stayed dark

### Symptom

After activity resumed from the locked/inactive state, both ENE DRAM devices
lit up but the Gigabyte motherboard and its ARGB headers remained off.

The detected lighting devices were:

- ENE DRAM at I2C address `0x71`
- ENE DRAM at I2C address `0x73`
- `B850 GAMING X WIFI6E`, IT5711 firmware `1.0.29.6`, at `/dev/hidraw9`

The affected OpenRGB package was `1.0rc3-3.1`.

### Root cause

There were two contributing problems:

1. OpenRGB reported successful profile loading for the IT5711 controller even
   though the motherboard did not physically apply the restored state. This
   matches [OpenRGB issue #4824](https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4824).
   Restarting or rescanning OpenRGB reopens and reinitializes the controller.
2. A subsequent `pre-headless.orp` snapshot had been taken after an earlier
   failed restore, so it correctly described the lit RAM but retained a dark
   motherboard state. Reinitializing the controller alone could not repair a
   snapshot that already requested black output.

OpenRGB exit status and the text `Profile loaded successfully` prove only that
the software accepted the profile. For this controller, visible motherboard
and ARGB output must also be checked.

### IT5711 restore workaround

`~/.local/bin/headless-display-mode.sh on` now performs this sequence:

1. Acquire the shared OpenRGB profile lock.
2. Stop `app-openrgb@autostart.service` to discard the stale IT5711 handle.
3. Start the service again and wait up to 20 seconds for SDK port `6742`.
4. Load `pre-headless.orp` through the fresh SDK controller.
5. Require both `Connected to server` and `Profile loaded successfully`.
6. Retry once if loading fails.
7. Remove `active` only after a successful restore. Otherwise, retain it so
   recovery remains retryable.

An exit trap ensures the OpenRGB tray/server is restarted if the restore is
interrupted.

During the repair, the legacy `tori-blue.orp` profile was applied after fresh
detection and the live state was saved again. The repaired `pre-headless.orp`
snapshot remains a temporary restore artifact; persistent profiles now live in
`~/.config/OpenRGB/profiles/` as JSON.

## Investigation record: 2026-09-13 — OpenRGB 1.0 false-success restore

After inactivity and unlock, Tori Blue was not restored. The `on` branch loaded
`pre-headless.orp` through OpenRGB 1.0, received `Profile loaded successfully`,
deleted the recovery marker, and left the controllers off. The same corrected
profile was tested through the SDK server and through exclusive local profile
loading; neither produced a visible change. Raw device commands did produce the
visually confirmed Purple -> Off -> Tori Blue sequence.

The durable fix is `~/.local/bin/openrgb-apply-profile`. It validates the saved
controller layout, converts every controller's saved mode and packed per-LED
colors into normal OpenRGB device arguments, stops the SDK server for exclusive
access, and restores it using an exit trap. Both the wallpaper hook and idle
resume handler use this adapter.

An idle restore simulation was completed at 12:50 on 2026-09-13: `off.json`
was applied, the real `headless-display-mode.sh on` branch restored the saved
Tori snapshot, the recovery marker was removed, and the OpenRGB service remained
active. The journal recorded:

```text
Restored pre-headless.orp through direct profile adapter
```

## If it fails again

1. Check Noctalia status and its log:

   ```bash
   noctalia msg status
   grep -Ei 'idle|headless|lock|dpms|error|fail' ~/.cache/noctalia/noctalia.log | tail -100
   ```

2. Check the configured command:

   ```bash
   grep -nE 'behavior_order|headless|command|resume_command|timeout|locked_timeout' ~/.config/noctalia/config.toml
   ```

3. Run the headless command manually only when the session is already locked or
   when testing an intentional display-off transition:

   ```bash
   ~/.local/bin/headless-display-mode.sh off
   ```

4. Restore manually with:

   ```bash
   ~/.local/bin/headless-display-mode.sh on
   ```

5. If only the RAM restores, check whether the recovery marker was retained
   and inspect the handler journal:

   ```bash
   test -e ~/.cache/headless-display-mode/active && echo active
   journalctl -b -t headless-display-mode --no-pager
   systemctl --user status 'app-openrgb@autostart.service'
   ```

6. If the snapshot itself contains the stale dark state, reapply the known
   wallpaper profile through the adapter:

   ```bash
   ~/.local/bin/openrgb-apply-profile \
     ~/.config/OpenRGB/profiles/tori-blue.json
   ```

   Confirm the motherboard and ARGB output visually before allowing the next
   idle transition to replace `pre-headless.orp` with the corrected live state.

Do not delete the `active` marker while the system is inactive; it is the
restore-state marker.

## Related setup scenarios

The Fire Stick is a possible future HDMI presentation client for the homelab,
but it is not part of this idle-control path. Citadel/Legion remain the
backend/control plane. See
`firestick-homelab-setup-and-scenarios.md` for the wallboard, streamer-view,
3440x1440 ultrawide, and VGA-only monitor scenarios.
