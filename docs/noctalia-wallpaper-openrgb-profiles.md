# Noctalia wallpaper-aware OpenRGB profiles

Initial integration: 2026-09-06. OpenRGB 1.0 regression diagnosed and generic
profile adapter installed 2026-09-13.

## Purpose

Load an OpenRGB profile that matches the active Noctalia wallpaper without
hardcoding a profile in the generic OpenRGB autostart entry.

Noctalia's wallpaper directory is `~/Wallpapers`. The current mappings are:

```text
tori_gate.jpg -> ~/.config/OpenRGB/profiles/tori-blue.json
wallhaven-3q2783.jpg -> ~/.config/OpenRGB/profiles/cathedral-inferno.json
wallhaven-5y57x8.png -> ~/.config/OpenRGB/profiles/white.json
```

Wallpapers without a mapping leave the current RGB state unchanged.

## Active configuration

Noctalia provides two hooks in `~/.config/noctalia/config.toml`:

```toml
[hooks]
started = "/home/YOUR_USER/.local/bin/openrgb-wallpaper-profile"
wallpaper_changed = "/home/YOUR_USER/.local/bin/openrgb-wallpaper-profile \"$NOCTALIA_WALLPAPER_PATH\""
```

The `started` hook synchronizes RGB with the restored wallpaper at login. The
`wallpaper_changed` hook receives the newly applied absolute path from Noctalia
and runs once for each changed output. The script matches the basename, so paths
below `~/Wallpapers` do not need to be duplicated in every mapping.

The mapping and load logic are in:

```text
~/.local/bin/openrgb-wallpaper-profile
```

The helper uses a bounded, blocking `flock` because both monitors can report the
same wallpaper change and a user can select another wallpaper while ENE hardware
verification is still running. New events wait instead of being discarded. It
also records the applied profile in:

```text
$XDG_RUNTIME_DIR/openrgb-wallpaper-profile.current
```

This avoids applying the same profile twice during one login session. Set
`OPENRGB_FORCE=1` when an intentional reapply is required.

## Current status

OpenRGB is normally started by the XDG desktop entry:

```text
~/.config/autostart/openrgb.desktop
```

Its generic launch command remains:

```text
openrgb --startminimized --server
```

OpenRGB 1.0rc3 used legacy `.orp` profiles. The current OpenRGB 1.0 package stores persistent profiles as `.json` files under `~/.config/OpenRGB/profiles/`. Temporary restore snapshots created by the headless helper remain `.orp` files. The old 1.0rc3 workflow had to stop the tray/server and load a profile with exclusive local hardware access because:

1. `--client` and automatic local connection together duplicated the
   controller list.
2. Even with `--noautoconnect --nodetect`, profile processing happened before
   the asynchronously received server controllers were added. OpenRGB printed
   `Profile failed to load` but still returned exit status 0.
3. The client briefly loaded blue and then applied the configured `off` exit
   profile as it terminated, making the lights come on and immediately go
   dark.

On the first boot after upgrading, OpenRGB 1.0 reported that the migrated JSON
profile loaded successfully but left the lights unchanged. The migrated profile
describes four motherboard ARGB headers and twelve zones, while the live 1.0
controller exposes three ARGB headers and five zones. The success message only
confirmed that OpenRGB accepted the profile, not that it wrote compatible state
to the hardware.

The stale duplicate motherboard entry was removed from `Configuration.json`,
and `off`, `purple`, and `tori-blue` were regenerated onto the current three-
controller/five-zone motherboard layout. The pre-migration files are retained
under `~/.config/OpenRGB/profile-layout-backup-20260913-1130/`.

The wallpaper helper now:

1. Starts `app-openrgb@autostart.service` if necessary.
2. Waits until the server exposes the complete saved controller layout.
3. Calls `~/.local/bin/openrgb-apply-profile`. Controller-only profiles use the
   compatibility adapter, which compares controller names, locations, zones,
   and LED counts between the profile and OpenRGB's current controller cache.
4. The compatibility adapter writes mode, zone, and color updates sequentially
   through the persistent SDK server, allowing each asynchronous hardware
   operation to settle before the next one.
5. Profiles containing OpenRGB 1.0 plugin state use the server's native profile
   manager so effects such as Custom Gradient Wave are restored along with the
   controller selection. The helper verifies the active profile and confirms
   that an autostart animation changes controller colors over time.
6. For controller-only profiles, the helper verifies both ENE DIMMs through
   their physical SMBus registers. The state marker is written only after the
   selected verification path succeeds.

## Confirmed OpenRGB 1.0 profile-loading regression

On 2026-09-13, all three corrected profiles were tested in two ways:

1. Through the running SDK server with `--noautoconnect --nodetect --client`.
2. Locally with exclusive hardware access after stopping the SDK server.

Purple, `off`, and Tori Blue all produced exit status 0 and the message
`Profile loaded successfully` through both paths. None produced a visible
lighting change. Therefore neither exit status nor the success message can be
used as hardware verification with OpenRGB 1.0 on this machine.

A control test then bypassed profile loading and issued ordinary device
commands while the server was stopped:

```bash
# Purple
openrgb --noautoconnect \
  --device 0 --mode direct --color B700FF \
  --device 1 --mode direct --color B700FF
openrgb --noautoconnect \
  --device "B850 GAMING X WIFI6E" --mode static --color B700FF

# Off
openrgb --noautoconnect \
  --device 0 --mode off \
  --device 1 --mode off
openrgb --noautoconnect \
  --device "B850 GAMING X WIFI6E" --mode static --color 000000

# Tori Blue
openrgb --noautoconnect \
  --device 0 --mode direct --color 0037FF \
  --device 1 --mode direct --color 0037FF
openrgb --noautoconnect \
  --device "B850 GAMING X WIFI6E" --mode static --color 0037FF
```

The visible sequence Purple -> Off -> Tori Blue worked. This proves that device
permissions, controller detection, and hardware writes are functional; the
failure is specifically in OpenRGB 1.0 profile application.

## Generic profile adapter

### Profile crossfades

Wallpaper changes and idle Off/restore transitions now blend directly between
the outgoing and incoming colors over **0.8 seconds**, with a smooth easing
curve and up to 30 frames per second. There is no intermediate black frame;
black is the destination only when the selected profile is Off.

The adapter snapshots the outgoing controller colors and loads a disposable
Direct-mode profile to stop Effects Plugin rendering before blending. It changes
only controllers whose Direct-mode settings differ, waits for ENE mode changes
when needed, synchronizes controller colors, and verifies the
physical ENE registers before sending sequential, synchronous color updates.
Animated destinations blend toward their saved color frame, then their real
profile is loaded and its animation starts. The outgoing animation pauses
during the blend. Preparation and final verification add time beyond the
0.8-second visible blend.

For normal wallpaper switches, already-configured Direct controllers are omitted
from the temporary profile. This removes the unconditional 0.75-second pause;
measured preparation now takes 0.13–0.25 seconds. Waking from hardware Off still
waits for the RAM's Direct-mode change before fading in. The temporary profile
also omits `base_color`, so native loading cannot replace the outgoing colors
with a uniform color before the blend starts.

Source profiles, effect settings, and the canonical 16-LED motherboard layout
are preserved. Temporary transition profiles are removed after application.
If transition preparation or rendering fails, the adapter still attempts the
real target profile through the normal verified application path.

`OPENRGB_WALLPAPER_FADE_SECONDS` and `OPENRGB_IDLE_FADE_SECONDS` control the
duration for their respective hooks; set either to `0` to disable its fade.
Manual applications and system shutdown retain their existing behavior unless
explicitly opted in, for example:

```bash
OPENRGB_FADE_SECONDS=1.2 scripts/openrgb-apply-profile profiles/white.json
```

Durations from 0 to 5 seconds are supported. `--check` never starts a transition.
Live tests produced 18–19 hardware-paced frames over approximately 0.9 seconds
with the default duration, and all three controllers passed final verification.
The implementation uses the native profile and synchronous color-update APIs
described in the [OpenRGB SDK source](https://github.com/CalcProgrammer1/OpenRGB/blob/master/NetworkServer.cpp).

### Verified native loads

As of October 16, 2026, controller-only profiles first use the native profile
loader, wait 0.75 seconds for hardware settling, and verify both SDK state and
physical ENE registers. When those checks pass, the adapter skips the redundant
serialized replay. If verification reports a mismatch, it retains the original
serialized recovery path. With the corrected 16-LED motherboard profiles,
Torii Blue completed in 2.2 seconds (previously 12.5), White in 1.0 second,
and Off in 2.0 seconds during live verification. These times include verification;
the native load happens before the settling and verification steps.

The installed compatibility layer keeps JSON profiles as the source of truth
and applies each matched controller through the persistent SDK server. It:

1. Validates profile/controller identity and layout before writing.
2. Resolves duplicate controller names using their stable locations.
3. Serializes mode, zone, color, and controller updates with a hardware settle
   interval between them.
4. Verifies SDK readback and the physical ENE mode/color registers.
5. Writes the session state marker only after every check succeeds.
6. Uses the same implementation for Purple, Off, Tori Blue, and future profiles
   with the same supported mode/color representation.

The adapter is also the single restore engine used by
`headless-display-mode.sh`, preventing the boot/wallpaper and idle paths from
diverging again.

## Implementation record: 2026-09-15 — animated cathedral profile

The `wallhaven-3q2783.jpg` wallpaper under `~/Wallpapers` is mapped to the
versioned `cathedral-inferno.json` profile. The profile embeds an autostart
`CustomGradientWave` from OpenRGB Effects Plugin 1.0 and targets both ENE DIMMs
plus all selected Gigabyte motherboard zones.

OpenRGB 1.0's profile-manager SDK packets are used for profiles containing a
`plugins` object. This is required because replaying only controller colors
would capture one animation frame without restoring the effect. Successful
application requires the server to report `cathedral-inferno` as active and at
least one selected controller to change colors across successive SDK samples.
The tested profile animates all three controllers.

Switching back to a controller-only profile first invokes the native profile
manager so the Effects plugin receives its profile-change notification and
stops the previous animation. The compatibility adapter then serializes and
hardware-verifies the static controller state as before.

Profile writes can take several seconds, especially when both ENE DIMMs require
physical register verification. The wallpaper hook therefore waits on its lock
for up to 60 seconds. Previously it used a non-blocking lock, which discarded a
rapid second selection such as Cathedral -> Torii -> Cathedral. A regression
test confirmed both queued invocations complete and the last-selected cathedral
profile remains active with all three controllers animating.

## Investigation record: 2026-09-14 — partial profile after boot

After login, the case/ARGB lighting changed to Tori Blue but both ENE DRAM
controllers and an onboard motherboard zone retained their firmware state.
The wallpaper journal recorded a successful application and all three
controllers were detected. The adapter was still issuing one combined command
for both DIMMs and the motherboard, and it used the saved Direct mode for the
IT5711. Both behaviors are unreliable on this controller combination despite a
zero exit status.

Source inspection showed that the standalone CLI queues its mode change but
immediately performs the LED write. ENE logical register operations themselves
use separate register-select and data transfers, so overlapping operations can
partially program or wedge a DIMM. The durable adapter keeps one server in sole
ownership, waits between writes, and verifies physical ENE registers. The
versioned motherboard profiles use Static for uniform colors because that mode
reliably updates and retains the IT5711 ARGB headers and onboard LEDs. Tori Blue
was force-applied after the change and all three controllers verified.

## OpenRGB settings required by this design

In `~/.config/OpenRGB/OpenRGB.json`, the per-process exit profile is disabled:

```json
"exit_profile": {
    "enabled": false,
    "name": "off"
}
```

Shutdown lighting is still handled by the system-level
`openrgb-off.service`, so disabling the GUI/client exit profile does not
remove the shutdown-off behavior.

Sony DualSense, DualSense Edge, and DualShock 4 detection are disabled in
OpenRGB. A Bluetooth DualSense was otherwise inserted into the server's
controller list during startup, changing the expected three PC-lighting
controllers to four and stalling SDK profile transfer. This setting affects
only OpenRGB lighting detection, not normal controller input or game support.

The expected PC-lighting controllers are:

- ENE DRAM at I2C address `0x71`
- ENE DRAM at I2C address `0x73`
- Gigabyte B850 Gaming X WIFI6E motherboard

## Adding another wallpaper mapping

Save the complete profile from OpenRGB's main profile control, then run:

```bash
openrgb-add-wallpaper-profile
```

The first graphical picker starts in `~/Wallpapers`. The second starts in
`~/.config/OpenRGB/profiles`, so the newly saved OpenRGB JSON can be selected
directly. The wizard then:

1. Validates that the selected files are an image and an OpenRGB 1.0 JSON
   profile with at least one controller.
2. Offers to copy an externally selected wallpaper into `~/Wallpapers`.
3. Copies the JSON into the repository's `profiles/` directory without
   overwriting a different file unless the user confirms.
4. Replaces the runtime profile with a symlink to the versioned copy.
5. Adds or replaces the wallpaper basename in
   `config/wallpaper-profiles.tsv` using an atomic file update.
6. Optionally applies and verifies the new mapping immediately.

For automation or repeatable testing, bypass either picker with explicit paths:

```bash
openrgb-add-wallpaper-profile \
  --wallpaper ~/Wallpapers/another-wallpaper.jpg \
  --profile ~/.config/OpenRGB/profiles/another-profile.json \
  --apply --yes
```

OpenRGB 1.0 embeds Effects Plugin state in the profile's `plugins` object; do
not save or map a separate plugin-only profile. Temporary restore snapshots
such as `pre-headless.orp` are intentionally separate from persistent profiles.

Advanced users can edit `config/wallpaper-profiles.tsv` directly. Each
non-comment line contains a wallpaper filename and profile filename separated
by one tab. The hook rejects profile entries containing a path separator.

## Verification

Check the current wallpaper and run the mapping manually:

```bash
noctalia msg wallpaper-get
OPENRGB_FORCE=1 ~/.local/bin/openrgb-wallpaper-profile
```

Verify the physical transition; OpenRGB's success text alone is insufficient.
Then confirm that the tray/server was restored and inspect the hook journal:

```bash
systemctl --user status 'app-openrgb@autostart.service'
journalctl --user -b -t openrgb-wallpaper --no-pager
cat "$XDG_RUNTIME_DIR/openrgb-wallpaper-profile.current"
```

Validate the Noctalia configuration after changing hooks:

```bash
noctalia config validate ~/.config/noctalia/config.toml
```

## Troubleshooting

If the lights briefly turn on and then go off, confirm that OpenRGB's
`UserInterface.autoload_profiles.exit_profile.enabled` value is `false`.

If the log claims success but the lights did not change, do not treat
`Profile loaded successfully` as proof. Compare the profile and controller
layouts, then use the raw device-command control test above to distinguish a
profile-loader failure from a hardware-access failure.

If the OpenRGB tray is missing after an error, restore it with:

```bash
systemctl --user start 'app-openrgb@autostart.service'
```

If a controller appears unexpectedly in OpenRGB, check the detector settings
and the live list before changing saved profiles:

```bash
timeout 15 openrgb --list-devices
grep -nE 'Sony DualSense|Sony DualShock' ~/.config/OpenRGB/OpenRGB.json
```

## Related pages

- `shutdown-rgb-aio.md` documents the system shutdown-off service.
- `idle-display-rgb.md` documents the independent lock/idle save-and-restore
  path.
- `spiderman-2-dualsense-cachyos.md` documents normal DualSense game support,
  which is independent of OpenRGB detector enablement.
