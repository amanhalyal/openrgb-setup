# Idle display and RGB control

## Purpose

Troubleshoot the inactive/locked desktop state where the monitors should power
off and PC lighting should be turned off.

## Intended behavior

Noctalia controls the idle sequence:

1. After 600 seconds (10 minutes), lock the session.
2. After 660 seconds (11 minutes), run the headless transition.
3. The transition saves the active OpenRGB profile, powers down both displays
   through DPMS, and applies the versioned Off profile through the serialized
   SDK adapter.
4. On input/unlock, displays and the saved RGB profile are restored through the
   same adapter.

The off branch first asks Noctalia whether the session is still locked. This
rejects a delayed idle callback after login before it can turn the restored
lighting off again.

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
command = "/home/YOUR_USER/.local/bin/headless-display-mode.sh off"
resume_command = "/home/YOUR_USER/.local/bin/headless-display-mode.sh on"
```

The script uses:

- `~/.cache/headless-display-mode/pre-headless.orp` for the last known active
  lighting state.
- `~/.cache/headless-display-mode/active` to record that this script switched
  the lights off and therefore owns the next restore.
- `~/.local/bin/openrgb-apply-profile` to translate the saved JSON profile into
  ordinary device operations because OpenRGB 1.0's profile loader is broken on
  this hardware.
- `~/.config/OpenRGB/profiles/off.json`, with native `off` mode for both DRAM
  controllers and Static black for the Gigabyte B850 motherboard/ARGB chain.
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

## Investigation record: 2026-10-06 — Off profile after ARGB resize

The live motherboard zones were resized to `6, 8, 0, 1, 1` (16 LEDs), but
`off.json` still described `64, 64, 64, 1, 1` (194 LEDs). The SDK adapter
rejected the mismatched profile. The headless handler then turned displays
back on, so each idle shutdown left both the lighting and monitors on.

The Off profile now matches the live layout, with zero colors throughout,
native Off mode for both DRAM controllers, and Static black for the motherboard.
The handler now keeps displays powered off if RGB application fails, preserving
the recovery snapshot. A stale recovery marker from a failed shutdown was
cleared after successfully restoring the current wallpaper effect.

Validation confirmed all three controller mappings, Off state for both RAM
modules and the motherboard, physical ENE register checks, and restoration of
the animated Peachy profile on all three controllers. Both monitor DPMS states
were checked off and then on. Noctalia's configuration remains valid with lock
at 600 seconds and headless shutdown at 660 seconds (60 seconds while locked).

The full automatic idle sequence was verified on 2026-10-06 (IST):

- At 10:07:51, Noctalia locked the session after the idle lock timeout.
- At 10:08:53, the headless action triggered and both monitors powered off.
- By 10:09:05, the SDK adapter successfully applied the corrected Off profile.
- At 10:10:00, a second live check confirmed the session remained locked,
  both monitors reported `dpmsStatus: false`, both ENE DRAM controllers were
  in Off mode, and the motherboard was in Static mode with all colors black.
- The user confirmed that the monitors and RGB lighting were off.

Historical logs also showed idle actions suppressed by Firefox audio/video
inhibitors. Keeping the desktop awake during playback is the user's chosen
behavior; automatic lock and shutdown resume when playback inhibition ends.

## Investigation record: 2026-10-06 — wake raced with idle shutdown

The user could not wake the displays after the automatic shutdown. At 22:13:05,
Noctalia logged the headless action as triggered and then resumed almost
immediately, but the asynchronous off script still finished applying `off.json`
at 22:13:17. Its older command could therefore power the monitors back down
after activity had already resumed.

The headless script now holds a per-session transition lock for the entire off
or restore operation. If a wake arrives during shutdown, the restore command
runs after the in-progress shutdown and leaves the displays on. Manually
running the restore command at 22:15:34 brought both monitors back and restored
the saved RGB profile; Noctalia recorded the session unlock at 22:15:41.

## OpenRGB 1.0 profile migration and idle-off failure

On 2026-09-12, OpenRGB was upgraded from `1.0rc3-3.1` to `1.0-2.1`. The new
build migrated persistent profiles from legacy `.orp` files to JSON files under
`~/.config/OpenRGB/profiles/`, renaming the old files to `.orp.bak`.

The idle helper still requested the old `~/.config/OpenRGB/off.orp` path. The
headless transition therefore saved its restore snapshot but left the lights
blue. Updating the path to `off.json` made OpenRGB report success, but the
Gigabyte/ARGB chain still remained lit. The current profile stores native DRAM
`off` mode and motherboard Static black and is applied through the SDK adapter.

Persistent JSON profiles remain appropriate for wallpaper changes. Temporary
restore snapshots remain `.orp` files by design.

## Investigation record: 2026-09-14 — post-unlock overwrite

After login from an inactive session, both DIMMs and one motherboard section
restored, while the fan and AIO headers stayed dark. Forcing Tori Blue produced
blue briefly and then returned the lighting to Off. Noctalia's log showed a
second headless action about 60 seconds after resume, matching the configured
`locked_timeout`. That delayed callback overwrote the restored profile.

The off handler now refuses to act unless `noctalia msg status` reports
`locked: true`. It also no longer starts a standalone OpenRGB process alongside
the SDK server. Off, restore, and wallpaper changes all share the same profile
lock and persistent SDK server. The three versioned profiles store the IT5711
motherboard in Static mode because its Direct mode does not reliably retain a
uniform color on the attached fan and AIO headers.

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

### Superseded IT5711 restore workaround

The 2026-09-06 implementation performed this sequence:

1. Acquire the shared OpenRGB profile lock.
2. Stop `app-openrgb@autostart.service` to discard the stale IT5711 handle.
3. Start the service again and wait up to 20 seconds for SDK port `6742`.
4. Load `pre-headless.orp` through the fresh SDK controller.
5. Require both `Connected to server` and `Profile loaded successfully`.
6. Retry once if loading fails.
7. Remove `active` only after a successful restore. Otherwise, retain it so
   recovery remains retryable.

This restart-and-native-profile workaround was replaced by the serialized SDK
adapter described below.

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
controller layout, applies mode and color writes sequentially through one SDK
server, verifies OpenRGB readback, and checks the physical ENE registers. Both
the wallpaper hook and idle resume handler use this adapter.

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
