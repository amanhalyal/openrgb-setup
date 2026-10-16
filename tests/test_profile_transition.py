#!/usr/bin/env python3
"""Crossfade behavior and recovery without touching hardware."""
import copy
import importlib.util
import json
import struct
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('adapter', ROOT / 'src/openrgb-profile-sdk.py')
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((ROOT / 'profiles/tori-blue.json').read_text())
        self.live = copy.deepcopy(self.profile['controllers'])
        for index, device in enumerate(self.live):
            device['sdk_id'] = index
            device['colors'] = [0xFFFFFF] * len(device['colors'])
            for mode in device['modes']:
                mode.setdefault('colors', [])
            for zone in device['zones']:
                zone.setdefault('modes', [])

    def test_blue_to_white_has_no_black_midpoint(self):
        self.assertEqual(adapter.blend_colors([0xFF0000], [0xFFFFFF], 0), [0xFF0000])
        self.assertEqual(adapter.blend_colors([0xFF0000], [0xFFFFFF], .5), [0xFF8080])
        self.assertEqual(adapter.blend_colors([0xFF0000], [0xFFFFFF], 1), [0xFFFFFF])

    def test_idle_fade_reaches_exact_black(self):
        self.assertEqual(adapter.blend_colors([0xFFFFFF], [0], .5), [0x808080])
        self.assertEqual(adapter.blend_colors([0xFFFFFF], [0], 1), [0])

    def test_zone_packets_skip_empty_headers_and_preserve_color_offsets(self):
        client = Mock()
        saved = {'zones': [{'leds_count': 2}, {'leds_count': 0}, {'leds_count': 1}]}
        adapter.write_transition_colors(client, 7, saved, [0x123456, 0x654321, 0xABCDEF])
        first, second = client.request.call_args_list
        self.assertEqual(first.args[:2], (7, 1051))
        self.assertEqual(struct.unpack('<IIHII', first.args[2]),
                         (18, 0, 2, 0x123456, 0x654321))
        self.assertEqual(struct.unpack('<IIHI', second.args[2]), (14, 2, 1, 0xABCDEF))

    def test_bridge_preserves_original_profiles_and_canonical_layout(self):
        original = copy.deepcopy(self.profile)
        bridge, operations, targets = adapter.transition_profile(self.profile, self.live)
        self.assertEqual(self.profile, original)
        self.assertEqual([len(op[4]) for op in operations], [8, 8, 16])
        for operation in operations:
            index, saved, _, mode, colors, zones = operation
            self.assertEqual(mode['name'], 'Direct')
            self.assertEqual(colors, self.live[index]['colors'])
            self.assertEqual(targets[index], original['controllers'][index]['colors'])
            self.assertTrue(all(zone[1] == -1 for zone in zones))
        self.assertNotIn('plugins', bridge)
        self.assertNotIn('base_color', bridge)

    def test_unsupported_direct_mode_fails_before_any_write(self):
        self.profile['controllers'][0]['modes'][0]['name'] = 'Unsupported'
        self.live[0]['modes'][0]['name'] = 'Unsupported'
        with self.assertRaisesRegex(ValueError, 'Crossfade needs Direct'):
            adapter.transition_profile(self.profile, self.live)

    def test_interrupted_fade_still_applies_target_and_cleans_bridge(self):
        client = Mock()
        client.controllers.return_value = self.live
        with patch.object(adapter, 'verify_loaded_state'), \
                patch.object(adapter.time, 'sleep'), \
                patch.object(adapter, 'crossfade', side_effect=OSError('test disconnect')):
            with adapter.profile_transition(client, self.profile, self.live, .8):
                client.load_profile('real-target')
        self.assertEqual(client.load_profile.call_args.args, ('real-target',))
        self.assertEqual(client.request.call_args.args[1], 153)

    def test_disabled_fade_makes_no_requests(self):
        client = Mock()
        with adapter.profile_transition(client, self.profile, self.live, 0):
            pass
        client.request.assert_not_called()
        client.load_profile.assert_not_called()

    def test_bridge_is_cleaned_when_target_application_fails(self):
        client = Mock()
        client.controllers.return_value = self.live
        with patch.object(adapter, 'verify_loaded_state'), \
                patch.object(adapter.time, 'sleep'), patch.object(adapter, 'crossfade'):
            with self.assertRaisesRegex(RuntimeError, 'target failed'):
                with adapter.profile_transition(client, self.profile, self.live, .8):
                    raise RuntimeError('target failed')
        self.assertEqual(client.request.call_args.args[1], 153)

    def test_existing_direct_modes_skip_mode_writes_and_settle_delay(self):
        for device in self.live:
            device['active_mode'] = next(i for i, mode in enumerate(device['modes'])
                                         if mode['name'] == 'Direct')
            for zone in device['zones']:
                zone['active_mode'] = -1
        client = Mock()
        client.controllers.return_value = self.live
        with patch.object(adapter, 'verify_loaded_state'), \
                patch.object(adapter.time, 'sleep') as sleep, patch.object(adapter, 'crossfade'):
            with adapter.profile_transition(client, self.profile, self.live, .8):
                pass
        upload = next(call for call in client.request.call_args_list if call.args[1] == 154)
        self.assertEqual(json.loads(upload.args[2].rstrip(b'\0'))['controllers'], [])
        sleep.assert_not_called()

    def test_native_static_restore_writes_argb_headers_before_verification(self):
        client = Mock()
        client.profile_names.return_value = ['tori-blue']
        operations = adapter.plan(self.profile, self.live)
        recorder = Mock()
        with patch.object(adapter, 'write_transition_colors') as write, \
                patch.object(adapter, 'verify_loaded_state') as verify, \
                patch.object(adapter.time, 'sleep'):
            recorder.attach_mock(write, 'write')
            recorder.attach_mock(verify, 'verify')
            adapter.apply_controller_profile(client, self.profile, operations)
        motherboard = operations[-1]
        write.assert_called_once_with(client, motherboard[0], motherboard[1], motherboard[4])
        self.assertEqual([call[0] for call in recorder.mock_calls], ['write', 'verify'])

    def test_native_mismatch_keeps_serialized_recovery(self):
        client = Mock()
        client.profile_names.return_value = ['tori-blue']
        operations = adapter.plan(self.profile, self.live)
        with patch.object(adapter, 'write_transition_colors'), \
                patch.object(adapter, 'verify_loaded_state', side_effect=ValueError('mismatch')), \
                patch.object(adapter.time, 'sleep'), patch.object(adapter, 'apply') as recover:
            adapter.apply_controller_profile(client, self.profile, operations)
        recover.assert_called_once_with(client, operations)


if __name__ == '__main__':
    unittest.main()
