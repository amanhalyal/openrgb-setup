# ARGB header and lighting-zone layout

## Observed physical mapping

The canonical Gigabyte motherboard layout is **16 LEDs**: `6, 8, 0, 1, 1`
for `ARGB_V2_1`, `ARGB_V2_2`, `ARGB_V2_3`, `Chipset Accent`, and `LED_C`,
respectively. This matches the live controller and every saved profile.

The observed lighting layout is:

| OpenRGB zone/device | Attached lighting | Responsive positions | Behavior |
| --- | --- | ---: | --- |
| `ARGB_V2_1` | Four case fans | 6 | All four fans correspond to this header. They appear to share the same six-position pattern. |
| `ARGB_V2_2` | AIO pump and AIO fans | 8 | The pump and fans correspond to this header and use an eight-position pattern. |
| ENE DRAM controllers | Two RAM modules | 8 per module | Each RAM module is exposed separately from the motherboard ARGB headers. |
| `LED_C` / chipset lighting | Motherboard chipset light | One visible block | The visible chipset light behaves as one indivisible color block. |

`ARGB_V2_1` and `ARGB_V2_2` should be treated as **provisionally parallel or
mirrored** until the per-LED test below confirms it. With a parallel hub, the
correct OpenRGB zone size is the number of addressable positions on one branch,
not the sum across every attached fan.

## Confirming the ARGB topology

Before resizing a zone, use OpenRGB's Direct/per-LED control:

1. Turn every LED in the zone black.
2. Set only LED 1 to red.
3. Advance the red color through each LED position.
4. Continue beyond the expected final position to determine whether any later
   indices control additional hardware.

Interpret the result as follows:

- If the same position illuminates on every fan, the fans are parallel or
  mirrored. Use the addressable count of one fan: likely 6 for `ARGB_V2_1` and
  8 for `ARGB_V2_2`.
- If later indices address different fans individually, the devices are in
  series. Use the highest responsive index, normally LEDs per device multiplied
  by the number of serial devices.
- If indices 7-64 on `ARGB_V2_1`, or 9-64 on `ARGB_V2_2`, produce no response,
  those positions are only unused configured capacity.

Do not change `ARGB_V2_1` to 24 merely because four six-LED fans are attached;
24 is correct only if the test proves that the four fans are serially
addressable.

## Canonical zone sizes

| Zone | LED count |
| --- | ---: |
| `ARGB_V2_1` | 6 |
| `ARGB_V2_2` | 8 |
| `ARGB_V2_3` | 0 |
| `Chipset Accent` | 1 |
| `LED_C` | 1 |

On October 16, 2026, the remaining older profiles (`tori-blue`, `white`,
`purple`, and `glacial-blue`) and `config/Configuration.json` were updated
from 194 to 16 motherboard LEDs. Per-zone LED metadata and color arrays were
trimmed together, retaining the first 6 and 8 colors on the connected headers
and each onboard zone's original color. RAM layouts and plugin settings were
preserved. All eight installed profiles passed controller-layout validation
against the running SDK server. New wallpaper-gradient previews inherit this
layout from `cathedral-inferno.json`.

## Multi-color rotating fan effect

For three colors visible simultaneously, use one **Custom Gradient Wave**
effect and select the relevant ARGB zones. Recommended starting settings are:

- Colors: `color 1 -> color 2 -> color 3 -> color 1`; repeating the first
  color closes the loop.
- Direction: Horizontal.
- Spread: 100.
- Frame rate: 60 FPS.
- Speed: low, adjusted by eye.

With `ARGB_V2_1` correctly sized to six positions, the effect samples the whole
gradient across the real LEDs instead of sampling only the beginning of a
64-position gradient. The four case fans should display the same pattern when
they are mirrored. Six LEDs allow roughly two positions per color, but smooth
motion requires blended boundaries because a sharply divided pattern can move
only in whole-LED steps.

An eight-position AIO pattern cannot divide evenly into three equal regions;
its closest distribution is approximately 3 + 3 + 2 positions.

### Wallpaper palette preview

Generate a disposable Custom Gradient Wave profile from a wallpaper and apply
it to the configured devices:

```bash
scripts/openrgb-wallpaper-gradient-preview ~/Wallpapers/example.png
```

With no path, the command asks Noctalia for the current wallpaper. It extracts
three distinct dominant colors, raises colors that are too dark to display
usefully on LEDs, repeats the first color to close the gradient, and uses the
working `cathedral-inferno.json` effect as its device-layout template. The
generated profile is stored as
`~/.config/OpenRGB/profiles/wallpaper-gradient-preview.json`; versioned profiles
are not modified.

Useful options:

```bash
# Show the palette and generate the profile without touching the lights
scripts/openrgb-wallpaper-gradient-preview --no-apply WALLPAPER

# Extract four colors or retain darker colors
scripts/openrgb-wallpaper-gradient-preview --colors 4 WALLPAPER
scripts/openrgb-wallpaper-gradient-preview --minimum-brightness 32 WALLPAPER
```

## Reference

OpenRGB cannot automatically determine the length of a conventional ARGB
chain. Its official resizing guide explains manual zone sizing, serial chains,
and parallel hubs: <https://openrgb.org/resize.html>.
