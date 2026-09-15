# OpenRGB Setup for Nexus

Reliable, wallpaper-aware RGB control for a Linux desktop with ENE DDR5 memory
and a Gigabyte motherboard.

This repository contains the scripts and investigation notes behind the live
lighting setup on **Nexus**. It works around OpenRGB 1.0 profile-loading and
ENE SMBus timing problems while keeping normal OpenRGB profiles as the source
of truth.

## What it controls

- Two G.SKILL DDR5 modules exposed as ENE DRAM at `0x71` and `0x73`
- A Gigabyte B850 Gaming X WIFI6E motherboard and its ARGB headers
- Wallpaper-driven profile selection through Noctalia
- Integrated OpenRGB Effects Plugin profiles for animated wallpaper themes
- Display-idle lighting shutdown and profile restoration
- Lighting shutdown before system power-off

## Why an adapter is needed

OpenRGB 1.0 can report a successful profile application without fully updating
this hardware. Its standalone CLI also races an asynchronous ENE mode change
against a synchronous LED-buffer write. The result can be a partial color
buffer, a profile that never leaves the default rainbow mode, or an ENE
controller that requires complete PSU power removal to reset.

The active adapter avoids that path:

```text
Noctalia wallpaper hook
        │
        ▼
openrgb-wallpaper-profile
        │ selects a saved JSON profile
        ▼
openrgb-apply-profile
        │
        ├─ controller-only profile → serialized SDK writes → ENE verification
        │
        └─ integrated plugin profile → native profile load → animation check
        │
        ▼
success marker written
```

Mode, zone, color, and controller operations are serialized. For the ENE DIMMs,
success requires the physical mode and all LED color registers to match the
profile; an OpenRGB exit code or cached SDK state alone is insufficient.

## Repository layout

| Path | Purpose |
| --- | --- |
| `scripts/` | Active wallpaper, idle, and profile entry points |
| `src/` | OpenRGB SDK profile adapter and ENE hardware verification |
| `profiles/` | Versioned static and animated wallpaper profiles |
| `config/` | Detector settings, motherboard layout, and wallpaper mappings |
| `systemd/` | System shutdown unit |
| `docs/` | Setup notes, incident records, and recovery procedures |
| `misc/` | Preserved scripts from before the SDK migration |

The live hooks retain their original paths under `~/.local/bin`. Those paths
are symlinks into this repository, so operational edits are tracked by Git
without requiring changes to Noctalia's configuration.

Create those compatibility links after cloning:

```bash
mkdir -p ~/.local/bin ~/.config/OpenRGB/profiles
for script in openrgb-add-wallpaper-profile openrgb-apply-profile openrgb-wallpaper-profile headless-display-mode.sh idle-off-check.sh; do
  ln -sfn "$PWD/scripts/$script" "$HOME/.local/bin/$script"
done
for profile in "$PWD"/profiles/*.json; do
  ln -sfn "$profile" "$HOME/.config/OpenRGB/profiles/$(basename "$profile")"
done
```

## Applying a profile

Validate controller identity, layout, modes, and colors without writing:

```bash
python3 src/openrgb-profile-sdk.py --check \
  ~/.config/OpenRGB/profiles/tori-blue.json
```

Apply and verify a profile through the running OpenRGB server:

```bash
scripts/openrgb-apply-profile \
  ~/.config/OpenRGB/profiles/tori-blue.json
```

Force the current wallpaper mapping to run again:

```bash
OPENRGB_FORCE=1 scripts/openrgb-wallpaper-profile
```

Overlapping wallpaper events wait for the active RGB write to finish. This
ensures a quick A -> B -> A wallpaper sequence finishes on the last selection
instead of dropping it while the ENE controllers are being verified.

The adapter exits unsuccessfully and does not update the wallpaper state marker
when controller mapping, native profile activation, animation, OpenRGB state,
or ENE hardware verification fails.

## Adding a wallpaper profile

After saving a normal or Effects Plugin profile from OpenRGB, run:

```bash
openrgb-add-wallpaper-profile
```

The wizard opens the wallpaper picker at `~/Wallpapers` and the profile picker
at `~/.config/OpenRGB/profiles`. It validates the JSON, copies the profile into
the repository, replaces OpenRGB's runtime copy with a symlink, updates
`config/wallpaper-profiles.tsv`, and offers to apply the profile immediately.
Existing destination files are never replaced without confirmation.

The optional arguments make the same operation scriptable:

```bash
openrgb-add-wallpaper-profile \
  --wallpaper ~/Wallpapers/forest.png \
  --profile ~/.config/OpenRGB/profiles/forest.json \
  --apply --yes
```

Mappings use wallpaper and profile basenames. This allows the absolute paths
emitted by Noctalia to work without embedding a user-specific home directory.
Controller-only profiles are matched to live hardware and verified before
completion; OpenRGB 1.0 profiles containing plugin state are loaded natively
and checked for activation.

## Requirements

- Linux with access to the relevant `/dev/i2c-*` and HID devices
- OpenRGB 1.0 with SDK server protocol v6 enabled
- Python 3
- `libi2c`, `jq`, `flock`, and systemd user services
- Noctalia for the wallpaper and idle hooks used by this setup

This is a machine-specific operational repository. Review device names,
addresses, paths, and zone layouts before adapting it to another computer.

### Tested configuration

- OpenRGB `1.0-2.1`, SDK protocol v6
- OpenRGB Effects Plugin `1.0`, plugin API v5
- Linux `7.2.4` with `i2c-dev` and `i2c-piix4`
- ENE `AUDA0-E6K5-0101` DDR5 lighting controllers
- Gigabyte IT5711 motherboard controller

The physical ENE verification currently supports `AUDA0-*` controllers using
the version-2 color registers. Unknown ENE hardware is rejected before it can
be reported as verified.

> [!CAUTION]
> RGB memory control uses the SMBus shared with DDR5 support devices. Do not
> run another RGB or SMBus control program concurrently. Preserve a cold-power
> recovery path and adapt the hardware checks before using this on a different
> ENE controller family.

## Documentation

- [Wallpaper-aware profiles](docs/noctalia-wallpaper-openrgb-profiles.md)
- [ENE DRAM application race](docs/ene-dram-apply-race-20260914.md)
- [Idle display and RGB behavior](docs/idle-display-rgb.md)
- [Shutdown lighting](docs/shutdown-rgb-aio.md)
- [Legacy idle implementation](docs/rgb-idle-lighting.md)

## Recovery

If an ENE DIMM remains dark while its registers are still accessible, shut the
machine down and remove PSU power until all motherboard lighting is off. A warm
reboot may leave the lighting controller powered and will not necessarily clear
the fault. The incident and confirmed fix are documented in
[`docs/ene-dram-apply-race-20260914.md`](docs/ene-dram-apply-race-20260914.md).

## License

Copyright © 2026 Aman Halyal. Licensed under the
[GNU General Public License v2.0 or later](LICENSE).
