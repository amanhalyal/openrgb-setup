# RGB Idle Lighting

> **Legacy implementation:** this timer-based design is disabled and retained
> only for historical reference. The active Noctalia implementation and the
> Gigabyte IT5711 restore workaround are documented in
> `~/Documents/wiki/idle-display-rgb.md`. Do not enable both mechanisms.

## Purpose

The case RGB lights follow the display power state:

- When the displays turn off because of inactivity, the current RGB state is
  saved and the case lights are switched off.
- When the displays turn on again, the saved RGB state is restored.
- The restore is not tied to a hard-coded profile or color.

## Components

| Path | Role |
| --- | --- |
| `~/.local/bin/idle-off-check.sh` | Checks DPMS state and toggles RGB |
| `~/.config/systemd/user/idle-off-check.service` | Runs the check once |
| `~/.config/systemd/user/idle-off-check.timer` | Schedules the check every 30 seconds |
| `~/.config/autostart/openrgb.desktop` | Starts OpenRGB after graphical login |
| `~/.cache/idle-off-rgb/pre-idle.orp` | Snapshot of the last active RGB state |
| `~/.cache/idle-off-rgb/off-by-idle` | Records that the idle script turned RGB off |

## Behavior

The script discovers the active `wayland-N` socket on every run. This avoids
breakage when the socket changes between logins, such as from `wayland-0` to
`wayland-1`.

When DPMS is off, the script:

1. Saves the live OpenRGB controller state to a temporary profile.
2. Moves the completed profile to `pre-idle.orp`.
3. Turns the configured RGB devices off.
4. Creates `off-by-idle` only if all preceding operations succeed.

When DPMS is on, the script reloads `pre-idle.orp` only when `off-by-idle`
exists. It removes the marker only after OpenRGB successfully restores the
snapshot. This prevents unrelated RGB changes from being overwritten.

If display detection or RGB snapshot creation fails, the script exits without
turning the lights off.

## Enable and verify the timer

```bash
systemctl --user daemon-reload
systemctl --user enable --now idle-off-check.timer
systemctl --user status idle-off-check.timer
```

Inspect recent runs with:

```bash
journalctl --user -u idle-off-check.service --since today
```

Validate the script after editing it:

```bash
bash -n ~/.local/bin/idle-off-check.sh
```

## Recovery

To restore the most recent pre-idle RGB state manually:

```bash
openrgb --profile ~/.cache/idle-off-rgb/pre-idle.orp
```

If no snapshot exists, load a known profile from
`~/.config/OpenRGB/profiles/`, for example:

```bash
openrgb --profile ~/.config/OpenRGB/profiles/purple.json
```

## Boot and login

Before graphical login, RGB behavior is controlled by the motherboard or RGB
controller firmware. After login, the OpenRGB autostart entry currently loads
the `purple` profile. The idle script subsequently preserves and restores
whatever RGB state is active immediately before the displays turn off.
