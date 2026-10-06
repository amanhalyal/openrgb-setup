# Shutdown RGB and AIO lighting

## Purpose

Turn off both ENE DRAM modules and the Gigabyte motherboard ARGB chain before
shutdown, reboot, or halt. The attached fans and AIO follow the motherboard
headers.

## Active design

The system unit is installed at `/etc/systemd/system/openrgb-off.service` from
`systemd/openrgb-off.service`. Its only stop action is:

```text
/usr/local/libexec/openrgb-shutdown-off
```

That path is a symlink to `scripts/openrgb-shutdown-off`. The helper:

1. Takes a system-level hardware lock.
2. Terminates the desktop OpenRGB server so one process owns the controllers.
3. Copies the Off profile and uses its controller data to seed a disposable
   configuration, so shutdown and the profile always use identical zone sizes.
4. Starts one isolated SDK server on port 6743.
5. Waits until the complete saved layout is visible.
6. Applies `profiles/off.json` with paced mode, zone, and color operations.
7. Verifies both ENE controllers through their physical SMBus registers.
8. Terminates the isolated server.

The Off profile uses each DIMM's hardware Off mode and motherboard Static black
across the 16 configured LEDs (ARGB headers 6, 8, and 0, plus two onboard zones).
Static mode persists reliably on the IT5711 and
its fan/AIO headers; Direct black did not.

The unit stops after `user@1000.service` has stopped, so desktop RGB observers
cannot restore lighting over the final Off write. It requires the repository's
`/home` mount and stops before journald, keeping the helper, profiles, and logs
available until the write and verification finish. Adjust the UID and repository
path in the unit if installing on another machine.

## October 6, 2026 shutdown regression

The idle repair updated `profiles/off.json` to the resized 16-LED motherboard
layout, but the shutdown helper still copied `config/Configuration.json`, whose
motherboard layout was 194 LEDs (64, 64, 64, 1, 1). The SDK adapter rejects that
mismatch before applying any profile. Shutdown therefore could leave the AIO
illuminated. The helper now derives its disposable configuration from the exact
Off profile it will apply; future Off profile geometry changes also update the
shutdown geometry automatically.

The previous shutdown journal only recorded the helper starting. It also showed
`/home` unmounting while the helper was still running, so explicit mount and
journal ordering were added. Detection failures now log the adapter error and
isolated server output instead of suppressing all diagnostic details.

## Why the old sequence was replaced

The former unit killed OpenRGB and then launched seven standalone OpenRGB
processes: one for the DIMMs, one for each motherboard zone, and a final Static
write. Each process redetected and reinitialized the same hardware. OpenRGB 1.0
can also overlap an asynchronous ENE mode update with its LED write, which can
leave one DIMM partially programmed or wedged.

The shutdown path now uses the same SDK adapter as wallpaper and idle profile
changes. It has a separate server because the user session and its SDK server
may already be stopping when the system unit runs.

## Installation

From the repository root:

```bash
sudo install -d -m 0755 /usr/local/libexec
sudo ln -sfn "$PWD/scripts/openrgb-shutdown-off" \
  /usr/local/libexec/openrgb-shutdown-off
sudo install -m 0644 systemd/openrgb-off.service \
  /etc/systemd/system/openrgb-off.service
sudo systemctl daemon-reload
sudo systemctl enable openrgb-off.service
```

## Verification

The following hardware check temporarily stops the desktop OpenRGB server and
turns the lights off. Run it only when that interruption is acceptable, then
restore the normal profile:

```bash
sudo /usr/local/libexec/openrgb-shutdown-off
scripts/openrgb-apply-profile profiles/tori-blue.json
```

The shutdown helper should report OpenRGB state for all three controllers and
physical verification for both ENE DIMMs. Check the installed unit and earlier
shutdown runs with:

```bash
systemctl show openrgb-off.service \
  -p Before -p Conflicts -p ExecStop -p TimeoutStopUSec
journalctl --no-pager -u openrgb-off.service -o short-iso
```

On October 6, read-only checks reproduced the old layout rejection and validated
all three controller mappings for the new seed and the live desktop server.
Shell syntax and systemd unit validation also passed. The updated helper and unit
were installed without restarting OpenRGB or powering off the active desktop.
An actual power-off check remains for the next normal shutdown.

An Off to Tori Blue simulation passed on 2026-09-14. Both DIMMs verified in
hardware Off mode, the motherboard accepted Static black for 194 LEDs, and the
subsequent Tori restore verified both DIMMs and Static blue on the motherboard.
