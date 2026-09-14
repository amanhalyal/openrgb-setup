# Shutdown RGB and AIO lighting

## Purpose

Ensure RGB lighting is turned off before shutdown, including an AIO and fans
connected to the motherboard ARGB headers.

## Shutdown hook

The system-level unit is:

```text
/etc/systemd/system/openrgb-off.service
```

It is enabled and ordered before `shutdown.target`, `reboot.target`, and
`halt.target`. Its shutdown action stops OpenRGB and directly applies hardware
`off`/black modes to the configured controllers and motherboard zones.

The persistent JSON profiles are available for wallpaper/manual use, but the
idle path deliberately uses direct hardware commands because the migrated
`off.json` profile did not reliably turn off the Gigabyte/ARGB chain.

```text
/home/aman/.config/OpenRGB/profiles/off.json
```

Check the unit:

```bash
systemctl is-enabled openrgb-off.service
systemctl status openrgb-off.service
systemctl show openrgb-off.service -p Before,Conflicts,ExecStop,TimeoutStopUSec
```

Check its previous-run history:

```bash
journalctl --no-pager -u openrgb-off.service -o short-iso
```

## Current device mapping

OpenRGB currently detects:

- Device 0: ENE DRAM at I2C address `0x71`
- Device 1: ENE DRAM at I2C address `0x73`
- Device 2: Gigabyte B850 Gaming X WIFI6E motherboard

The motherboard exposes the ARGB headers as:

```text
ARGB_V2_1
ARGB_V2_2
ARGB_V2_3
ARGB_V2_4
```

The AIO and fans are connected to those headers, so device 2 is the relevant
controller. The motherboard does not expose a native `Off` mode; use static
black instead. The active idle path applies this directly rather than loading
`off.json`; see `idle-display-rgb.md`.

```bash
openrgb --device 2 --mode static --color 000000
```

For the DRAM devices, use their supported off mode:

```bash
openrgb --device 0 --mode off
openrgb --device 1 --mode off
```

## Investigation record: 2026-09-04

The shutdown hook was verified from the previous boot:

```text
22:21:05  Stopping Turn off RGB lighting on shutdown
22:21:08  Profile loaded successfully
22:21:09  openrgb-off.service stopped
```

Therefore the off profile is being loaded before shutdown. OpenRGB does not
detect a separate AIO controller; it only detects the motherboard and DRAM.
If the AIO remains lit, the profile may not be forcing the motherboard ARGB
zones to static black, or the AIO may retain its last hardware state after the
USB/software controller exits.

The explicit motherboard command was tested successfully while inactive:

```text
openrgb --device 2 --mode static --color 000000
exit code: 0
```

This matters for the planned Fire Stick/presentation setup because the PC's
display and RGB power policy is independent of any future HDMI streamer view.
The Fire Stick should not be treated as the RGB or shutdown controller.

## Recommended hardening

If AIO lighting remains on after a future shutdown, update the shutdown action
to explicitly apply the three device states rather than relying only on the
profile:

```sh
/usr/bin/openrgb --device 0 --mode off
/usr/bin/openrgb --device 1 --mode off
/usr/bin/openrgb --device 2 --mode static --color 000000
```

Test the commands while the machine is running before changing the systemd
unit. Do not edit the shutdown unit without preserving a backup and verifying
its ordering afterward.

For the broader Fire Stick architecture and the decision to keep backend
services on Legion or Citadel, see
`firestick-homelab-setup-and-scenarios.md`.

## Useful checks

```bash
timeout 10 openrgb --list-devices
openrgb --device 2 --mode static --color 000000
journalctl --no-pager -u openrgb-off.service -o short-iso
```

For wallpaper-driven profile selection at login and during theme changes, see
`noctalia-wallpaper-openrgb-profiles.md`. That mechanism deliberately disables
OpenRGB's per-process exit profile; this system-level shutdown service remains
responsible for turning the lights off.
