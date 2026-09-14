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
3. Seeds a disposable config with the validated three-controller layout.
4. Starts one isolated SDK server on port 6743.
5. Waits until the complete saved layout is visible.
6. Applies `profiles/off.json` with paced mode, zone, and color operations.
7. Verifies both ENE controllers through their physical SMBus registers.
8. Terminates the isolated server.

The Off profile uses each DIMM's hardware Off mode and motherboard Static black
across the 194 configured LEDs. Static mode persists reliably on the IT5711 and
its fan/AIO headers; Direct black did not.

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

Test the helper while the machine is running, then restore the normal profile:

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

An Off to Tori Blue simulation passed on 2026-09-14. Both DIMMs verified in
hardware Off mode, the motherboard accepted Static black for 194 LEDs, and the
subsequent Tori restore verified both DIMMs and Static blue on the motherboard.
