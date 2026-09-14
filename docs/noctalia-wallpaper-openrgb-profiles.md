# Noctalia wallpaper-aware OpenRGB profiles

Initial integration: 2026-09-06. OpenRGB 1.0 regression diagnosed and generic
profile adapter installed 2026-09-13.

## Purpose

Load an OpenRGB profile that matches the active Noctalia wallpaper without
hardcoding a profile in the generic OpenRGB autostart entry.

The first mapping is:

```text
tori_gate.jpg -> ~/.config/OpenRGB/profiles/tori-blue.json
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
`wallpaper_changed` hook receives the newly applied path from Noctalia and
runs once for each changed output.

The mapping and load logic are in:

```text
~/.local/bin/openrgb-wallpaper-profile
```

The helper uses `flock` because both monitors can report the same wallpaper
change. It also records the applied profile in:

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
3. Calls `~/.local/bin/openrgb-apply-profile`, which compares controller names,
   locations, zones, and LED counts between the selected profile and OpenRGB's
   current controller cache.
4. The adapter writes mode, zone, and color updates sequentially through the
   persistent SDK server, allowing each asynchronous hardware operation to
   settle before the next one.
5. Verifies both ENE DIMMs through their physical SMBus registers and writes
   the state marker only after verification succeeds. The versioned profiles
   store uniform motherboard colors in Static mode so the IT5711 retains them
   across its onboard LEDs and ARGB headers.

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

Edit the `case` statement in `~/.local/bin/openrgb-wallpaper-profile`:

```bash
case "${wallpaper_path##*/}" in
    tori_gate.jpg)
        profile="$profile_dir/tori-blue.json"
        ;;
    another-wallpaper.jpg)
        profile="$profile_dir/another-profile.json"
        ;;
    *)
        exit 0
        ;;
esac
```

Save the OpenRGB profile and keep the generated persistent profile under
`~/.config/OpenRGB/profiles/` with a `.json` suffix. Do not update temporary
restore snapshots such as `pre-headless.orp`; those are intentionally separate
from persistent OpenRGB profiles.

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
