# Nexus OpenRGB configuration

This repository contains the scripts and operational notes used to manage
OpenRGB lighting on Nexus.

## Layout

- `scripts/` — active wallpaper, idle, and profile entry points
- `src/` — supporting implementations under development
- `docs/` — setup, behavior, and troubleshooting notes
- `misc/` — preserved pre-change copies and investigation artifacts

The active hooks continue to use paths under `~/.local/bin`. Those paths are
symlinks into this repository so configuration changes can be reviewed and
versioned here.

## Current incident baseline

On 2026-09-14, the ENE DRAM controller at I2C address `0x73` stopped producing
light after repeated OpenRGB detection and mode changes. Its registers remained
readable and contained the requested colors. A complete removal of PSU power
reset the controller, after which both DIMMs returned to their default rainbow
effect.

No RGB profile was applied while creating this repository.
