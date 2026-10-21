#!/usr/bin/env python3
"""Build an OpenRGB Custom Gradient Wave profile from a wallpaper palette."""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps


def srgb_channel(value: int) -> float:
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def rgb_to_lab(color: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = (srgb_channel(value) for value in color)
    x = (red * 0.4124564 + green * 0.3575761 + blue * 0.1804375) / 0.95047
    y = red * 0.2126729 + green * 0.7151522 + blue * 0.0721750
    z = (red * 0.0193339 + green * 0.1191920 + blue * 0.9503041) / 1.08883

    def pivot(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = pivot(x), pivot(y), pivot(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    # Favor different hues over shadows/highlights of the same color.
    return math.sqrt(0.05 * (left[0] - right[0]) ** 2
                     + (left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2)


def wallpaper_tuning(image: Image.Image) -> dict[str, float]:
    """Estimate visual intensity, not semantic style, from a small RGB image."""
    sample = image.copy()
    sample.thumbnail((96, 96), Image.Resampling.LANCZOS)
    pixels = [sample.getpixel((x, y)) for y in range(sample.height) for x in range(sample.width)]
    total_weight = 0.0
    saturation_sum = 0.0
    lightness = []
    for color in pixels:
        _, saturation, value = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in color))
        # Dark backgrounds should not drown out bright neon accents. Squared
        # value also stops almost-black color noise from setting the mood.
        weight = value ** 2
        total_weight += weight
        saturation_sum += saturation * weight
        lightness.append(rgb_to_lab(color)[0] / 100.0)
    colorfulness = saturation_sum / total_weight if total_weight else 0.0
    lightness.sort()
    contrast = lightness[int((len(lightness) - 1) * 0.9)] - lightness[int((len(lightness) - 1) * 0.1)]

    # Adjacent color changes distinguish flat art from busy, textured scenes.
    changes = []
    for y in range(sample.height):
        for x in range(sample.width):
            index = y * sample.width + x
            for neighbor in (index + 1 if x + 1 < sample.width else None,
                             index + sample.width if y + 1 < sample.height else None):
                if neighbor is not None:
                    changes.append(max(abs(a - b) for a, b in zip(pixels[index], pixels[neighbor])) / 255.0)
    detail = min(1.0, 10.0 * sum(changes) / len(changes)) if changes else 0.0
    chromatic = min(1.0, max(0.0, (colorfulness - 0.12) / 0.63))
    chromatic = chromatic * chromatic * (3.0 - 2.0 * chromatic)
    # Even soft palettes need a little chroma on LEDs to avoid looking white.
    baseline = 0.18 * min(1.0, colorfulness / 0.12)
    boost = baseline + 0.47 * chromatic * (0.45 + 0.30 * contrast + 0.25 * detail)
    return dict(saturation_boost=boost, colorfulness=colorfulness,
                contrast=contrast, detail=detail, brightness_lift=0.8 * (1.0 - chromatic))


def led_adjust(color: tuple[int, int, int], minimum_brightness: int,
               saturation_boost: float = 0.0,
               brightness_lift: float = 0.0) -> tuple[int, int, int]:
    red, green, blue = (value / 255.0 for value in color)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    # Retain white in soft images; remove more of it for vivid, busy images.
    # Protect near-neutral pixels from having tiny color casts amplified.
    neutral_guard = min(1.0, saturation / 0.2) ** 2
    saturation += (1.0 - saturation) * saturation_boost * neutral_guard
    # Soft colors should be luminous pastels rather than dim gray shades.
    # Neon images keep their original brightness differences.
    value += max(0.0, 0.88 - value) * brightness_lift
    value = max(value, minimum_brightness / 255.0)
    adjusted = colorsys.hsv_to_rgb(hue, saturation, value)
    return tuple(round(channel * 255) for channel in adjusted)


def extract_palette(path: Path, count: int, minimum_brightness: int,
                    tuning: dict[str, float] | None = None) -> list[tuple[int, int, int]]:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
            image = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            image = image.convert("RGB")
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)
        analysis = wallpaper_tuning(image)
        if tuning is not None:
            tuning.update(analysis)
        # Keep small accents even when a flat neutral background fills the frame.
        quantized = image.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        raw = quantized.getpalette()
        histogram = quantized.getcolors() or []

    candidates: list[tuple[int, tuple[int, int, int], tuple[float, float, float]]] = []
    for population, index in sorted(histogram, reverse=True):
        offset = index * 3
        color = tuple(raw[offset : offset + 3])
        candidates.append((population, color, rgb_to_lab(color)))

    if not candidates:
        raise ValueError("the wallpaper did not contain any readable colors")

    # Dark foregrounds and nearly neutral highlights are common in photos, but
    # make poor accent colors for a wave. Prefer the image's brighter chromatic
    # colors, retaining the full pool for dark or monochrome images.
    brightest = max(max(item[1]) for item in candidates)
    accents = [
        item for item in candidates
        if max(item[1]) >= brightest * 0.55
        and colorsys.rgb_to_hsv(*(channel / 255.0 for channel in item[1]))[1] >= 0.2
    ]
    pool = accents if len(accents) >= count else candidates
    maximum_population = max(item[0] for item in pool)
    selected = [max(pool, key=lambda item: item[0] * (0.35 + item[2][0] / 100.0))]
    while len(selected) < count:
        remaining = [candidate for candidate in pool if candidate not in selected]
        if not remaining:
            break
        selected.append(
            max(
                remaining,
                key=lambda item: math.sqrt(item[0] / maximum_population)
                * (max(item[1]) / max(brightest, 1))
                * min(distance(item[2], chosen[2]) for chosen in selected),
            )
        )

    palette: list[tuple[int, int, int]] = []
    for _, color, _ in selected:
        adjusted = led_adjust(color, minimum_brightness, analysis["saturation_boost"],
                              analysis["brightness_lift"])
        if adjusted not in palette:
            palette.append(adjusted)

    for _, color, _ in candidates:
        if len(palette) >= count:
            break
        adjusted = led_adjust(color, minimum_brightness, analysis["saturation_boost"],
                              analysis["brightness_lift"])
        if adjusted not in palette:
            palette.append(adjusted)

    if len(palette) < count:
        raise ValueError(f"could extract only {len(palette)} distinct colors")
    return palette[:count]


def pack_openrgb(color: tuple[int, int, int]) -> int:
    red, green, blue = color
    return red | green << 8 | blue << 16


def seed_gradient_frame(profile: dict, palette: list[tuple[int, int, int]]) -> None:
    """Save a wallpaper-colored frame for native loading and crossfade targets.

    The Effects Plugin palette alone does not replace the template's per-LED
    colors. Those colors are displayed before animation starts and are also
    the destination used by the profile adapter's crossfade.
    """
    for controller in profile["controllers"]:
        colors = []
        for zone in controller["zones"]:
            count = zone["leds_count"]
            for index in range(count):
                position = index * len(palette) / count
                left = int(position)
                fraction = position - left
                start = palette[left % len(palette)]
                end = palette[(left + 1) % len(palette)]
                color = tuple(round(a + (b - a) * fraction) for a, b in zip(start, end))
                colors.append(pack_openrgb(color))
        if len(colors) != len(controller["colors"]):
            raise ValueError(f"zone/LED count mismatch: {controller['name']}")
        controller["colors"] = colors


def build_profile(template_path: Path, output_path: Path, palette: list[tuple[int, int, int]]) -> int:
    with template_path.open(encoding="utf-8") as source:
        profile = json.load(source)

    effects = profile.get("plugins", {}).get("OpenRGB Effects Plugin", {}).get("Effects", [])
    gradients = [effect for effect in effects if effect.get("EffectClassName") == "CustomGradientWave"]
    if not gradients:
        raise ValueError("template has no CustomGradientWave effect")

    closed_gradient = palette + [palette[0]]
    packed = [pack_openrgb(color) for color in closed_gradient]
    for effect in gradients:
        settings = effect.setdefault("CustomSettings", {})
        settings["colors"] = packed
        settings["direction"] = 0
        settings["spread"] = 100
        effect["FPS"] = 60
        effect["AutoStart"] = True

    seed_gradient_frame(profile, palette)

    profile_name = output_path.stem
    if not re.fullmatch(r"[A-Za-z0-9._-]+", profile_name):
        raise ValueError("output filename must use only letters, numbers, dot, underscore, or hyphen")
    profile["profile_name"] = profile_name

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(profile, output, indent=4)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, output_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return len(gradients)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wallpaper", type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--colors", type=int, choices=(2, 3, 4, 5), default=3)
    parser.add_argument("--minimum-brightness", type=int, default=72)
    args = parser.parse_args()

    if not args.wallpaper.is_file():
        parser.error(f"wallpaper is not a file: {args.wallpaper}")
    if not args.template.is_file():
        parser.error(f"template is not a file: {args.template}")
    if not 0 <= args.minimum_brightness <= 255:
        parser.error("--minimum-brightness must be between 0 and 255")

    try:
        tuning: dict[str, float] = {}
        palette = extract_palette(args.wallpaper, args.colors, args.minimum_brightness, tuning)
        effects = build_profile(args.template, args.output, palette)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    print(f"Wallpaper tuning: saturation boost {tuning['saturation_boost']:.0%}; "
          f"colorfulness {tuning['colorfulness']:.0%}, contrast {tuning['contrast']:.0%}, "
          f"detail {tuning['detail']:.0%}")
    print("Palette: " + " -> ".join(f"#{r:02X}{g:02X}{b:02X}" for r, g, b in palette))
    print(f"Generated {args.output} with {effects} Custom Gradient Wave effect(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
