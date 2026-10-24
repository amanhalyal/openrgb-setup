"""Wallpaper mood and LED palette behavior without touching RGB hardware."""
import colorsys
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gradient', ROOT / 'src/wallpaper-gradient-profile.py')
gradient = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gradient)


class WallpaperGradientTests(unittest.TestCase):
    def test_generated_fade_targets_use_wallpaper_colors_instead_of_template(self):
        template = ROOT / 'profiles/cathedral-inferno.json'
        original = template.read_bytes()
        # A blue/green wallpaper must never inherit Cathedral's red channel.
        palette = [(0, 100, 200), (0, 200, 100), (0, 120, 240)]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'wallpaper.json'
            gradient.build_profile(template, output, palette)
            profile = json.loads(output.read_text())
        self.assertEqual(template.read_bytes(), original)
        for controller in profile['controllers']:
            self.assertEqual(len(controller['colors']), sum(z['leds_count'] for z in controller['zones']))
            self.assertTrue(all(c & 255 == 0 for c in controller['colors']))
            self.assertGreater(len(set(controller['colors'])), 1)
        effect = profile['plugins']['OpenRGB Effects Plugin']['Effects'][0]
        self.assertEqual(effect['CustomSettings']['colors'],
                         [gradient.pack_openrgb(c) for c in palette + palette[:1]])

    def test_gradient_frame_handles_empty_and_single_led_zones(self):
        profile = {'controllers': [{'name': 'test', 'colors': [255],
                                   'zones': [{'leds_count': 0}, {'leds_count': 1}]}]}
        gradient.seed_gradient_frame(profile, [(0, 0, 200), (0, 200, 0)])
        self.assertEqual(profile['controllers'][0]['colors'], [gradient.pack_openrgb((0, 0, 200))])

    def test_pastel_minimal_image_retains_muted_colors(self):
        image = Image.new('RGB', (96, 96), (220, 205, 230))
        image.paste((190, 210, 230), (0, 0, 48, 96))
        tuning = gradient.wallpaper_tuning(image)
        self.assertLess(tuning['saturation_boost'], 0.2)
        adjusted = gradient.led_adjust((190, 210, 230), 72, tuning['saturation_boost'])
        self.assertLess(colorsys.rgb_to_hsv(*adjusted)[1], 0.4)

    def test_neon_on_dark_background_gets_stronger_tuning(self):
        image = Image.new('RGB', (96, 96), (3, 3, 6))
        for x in range(0, 96, 8):
            image.paste((240, 35, 180), (x, 0, x + 2, 96))
            image.paste((20, 210, 240), (x + 2, 0, x + 4, 96))
        self.assertGreater(gradient.wallpaper_tuning(image)['saturation_boost'], 0.45)

    def test_flat_art_gets_less_boost_than_busy_art_with_same_colors(self):
        flat = Image.new('RGB', (96, 96), (200, 60, 150))
        flat.paste((40, 140, 200), (0, 0, 48, 96))
        busy = Image.new('RGB', (96, 96), (200, 60, 150))
        for x in range(0, 96, 4):
            busy.paste((40, 140, 200), (x, 0, x + 2, 96))
        self.assertLess(gradient.wallpaper_tuning(flat)['saturation_boost'],
                        gradient.wallpaper_tuning(busy)['saturation_boost'])

    def test_grayscale_contrast_does_not_invent_color(self):
        image = Image.linear_gradient('L').convert('RGB')
        self.assertEqual(gradient.wallpaper_tuning(image)['saturation_boost'], 0)
        self.assertEqual(gradient.led_adjust((100, 100, 100), 72, 0.6), (100, 100, 100))

    def test_black_and_single_pixel_have_finite_tuning(self):
        for color in [(0, 0, 0), (255, 255, 255), (180, 20, 130)]:
            tuning = gradient.wallpaper_tuning(Image.new('RGB', (1, 1), color))
            self.assertTrue(0 <= tuning['saturation_boost'] <= 0.65)

    def test_boost_preserves_hue_and_brightness(self):
        for color in [(93, 104, 179), (172, 133, 192), (138, 131, 185)]:
            adjusted = gradient.led_adjust(color, 72, 0.4)
            before, after = colorsys.rgb_to_hsv(*color), colorsys.rgb_to_hsv(*adjusted)
            self.assertAlmostEqual(before[0], after[0], delta=0.003)
            self.assertEqual(max(adjusted), max(color))
            self.assertGreater(after[1], before[1])
            self.assertLess(after[1], 1)

    def test_grade_preserves_neutrals_and_clamps_value(self):
        for level in (0, 40, 128, 230, 255):
            adjusted = gradient.led_adjust((level, level, level), 72, 0.6,
                                           extra_saturation=0.5, contrast=2.0)
            self.assertEqual(len(set(adjusted)), 1)
            self.assertTrue(all(72 <= channel <= 255 for channel in adjusted))

    def test_extra_saturation_preserves_hue_and_value(self):
        color = (93, 104, 179)
        adjusted = gradient.led_adjust(color, 72, extra_saturation=0.5)
        before, after = colorsys.rgb_to_hsv(*color), colorsys.rgb_to_hsv(*adjusted)
        self.assertAlmostEqual(before[0], after[0], delta=0.003)
        self.assertEqual(max(adjusted), max(color))
        self.assertGreater(after[1], before[1])

    def test_palette_uses_image_tuning_and_reports_it(self):
        image = Image.new('RGB', (96, 96), (220, 205, 230))
        image.paste((190, 210, 230), (0, 0, 32, 96))
        image.paste((230, 210, 190), (32, 0, 64, 96))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pastel.png'
            image.save(path)
            tuning = {}
            palette = gradient.extract_palette(path, 3, 72, tuning)
        self.assertEqual(len(set(palette)), 3)
        self.assertLess(tuning['saturation_boost'], 0.2)
        self.assertTrue(all(colorsys.rgb_to_hsv(*c)[1] < 0.4 for c in palette))

    def test_soft_colors_are_lifted_without_changing_hue(self):
        color = (90, 140, 150)
        adjusted = gradient.led_adjust(color, 72, 0.18, 0.8)
        self.assertGreater(max(adjusted), 200)
        self.assertAlmostEqual(colorsys.rgb_to_hsv(*color)[0],
                               colorsys.rgb_to_hsv(*adjusted)[0], delta=0.003)

    def test_small_colored_accents_survive_large_neutral_background(self):
        image = Image.new('RGB', (320, 160), (150, 155, 160))
        for box, color in [((0, 0, 24, 160), (220, 140, 155)),
                           ((24, 0, 48, 160), (110, 160, 160)),
                           ((48, 0, 72, 160), (220, 170, 130))]:
            image.paste(color, box)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accents.png'
            image.save(path)
            palette = gradient.extract_palette(path, 3, 72)
        hues = [colorsys.rgb_to_hsv(*color)[0] for color in palette]
        self.assertTrue(any(0.45 < h < 0.6 for h in hues), palette)
        self.assertTrue(any(h > 0.9 for h in hues), palette)
        self.assertTrue(any(0.03 < h < 0.15 for h in hues), palette)


if __name__ == '__main__':
    unittest.main()
