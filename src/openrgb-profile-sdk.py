#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply saved controller state through a persistent OpenRGB SDK server.

Uses SDK v6's device/mode/LED and native profile APIs. Controller-only profiles
are applied and verified directly; integrated plugin profiles are loaded by the
server so their plugin state is restored. No hardware names, colors, or mode
substitutions are made.
"""
import argparse
import copy
from contextlib import contextmanager
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import sys
import time
import uuid

FIELDS = ('flags speed_min speed_max brightness_min brightness_max '
          'colors_min colors_max speed brightness direction color_mode').split()
HARDWARE_SETTLE_SECONDS = 0.75
I2C_SLAVE = 0x0703
ENE_MODE_VALUES = {
    'Off': 0,
    'Static': 1,
    'Breathing': 2,
    'Flashing': 3,
    'Spectrum Cycle': 4,
    'Rainbow': 5,
    'Chase Fade': 7,
    'Chase': 9,
    'Random Flicker': 13,
    'Double Fade': 14,
}


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def string(value):
    raw = value.encode() + b'\0'
    return pack('H', len(raw)) + raw


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        result = self.data[self.pos:self.pos + size]
        if len(result) != size:
            raise ValueError('Truncated SDK response')
        self.pos += size
        return result

    def number(self, fmt='I'):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

    def text(self):
        return self.take(self.number('H')).rstrip(b'\0').decode()

    def colors(self):
        return [self.number() for _ in range(self.number('H'))]

    def mode(self):
        mode = {'name': self.text()}
        mode.update({key: self.number() for key in FIELDS})
        mode['colors'] = self.colors()
        return mode


def parse_controller(data):
    r = Reader(data)
    if r.number() != len(data):
        raise ValueError('SDK controller size mismatch')
    result = {'type': r.number()}
    for key in ('name', 'vendor', 'description', 'version', 'serial', 'location'):
        result[key] = r.text()
    count = r.number('H')
    result['active_mode'] = r.number('i')
    result['modes'] = []
    for _ in range(count):
        result['modes'].append(r.mode())
    result['zones'] = []
    for _ in range(r.number('H')):
        zone = {'name': r.text()}
        zone.update({key: r.number() for key in ('type', 'leds_min', 'leds_max', 'leds_count')})
        r.take(r.number('H'))  # matrix map, irrelevant to LED ordering
        zone['segments'] = []
        for _ in range(r.number('H')):
            segment = {'name': r.text()}
            segment.update({key: r.number() for key in ('type', 'start_idx', 'leds_count')})
            r.take(r.number('H'))
            segment['flags'] = r.number()
            zone['segments'].append(segment)
        zone['flags'] = r.number()
        zone['active_mode'] = r.number('i')
        zone['modes'] = [r.mode() for _ in range(r.number('H'))]
        zone['display_name'] = r.text()
        result['zones'].append(zone)
    result['leds'] = [{'name': r.text()} for _ in range(r.number('H'))]
    result['colors'] = r.colors()
    result['led_display_names'] = [r.text() for _ in range(r.number('H'))]
    result['flags'] = r.number()
    result['display_name'] = r.text()
    result['configuration'] = r.take(r.number()).rstrip(b'\0').decode()
    if r.pos != len(data):
        raise ValueError('Unexpected SDK controller fields')
    return result


class Client:
    def __init__(self):
        host = os.environ.get('OPENRGB_SDK_HOST', '127.0.0.1')
        port = int(os.environ.get('OPENRGB_SDK_PORT', '6742'))
        self.sock = socket.create_connection((host, port), timeout=3)
        version = struct.unpack('<I', self.request(0, 40, pack('I', 6)))[0]
        if version < 6:
            raise ValueError('OpenRGB SDK version 6 or newer required')
        self.send(0, 50, b'Profile state adapter\0')

    def send(self, device, command, data=b''):
        self.sock.sendall(pack('4sIII', b'ORGB', device, command, len(data)) + data)

    def receive(self, size):
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError('OpenRGB disconnected')
            data += chunk
        return data

    def request(self, device, command, data=b'', ack=False):
        self.send(device, command, data)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            magic, reply_device, reply_command, size = struct.unpack('<4sIII', self.receive(16))
            if magic != b'ORGB' or size > 8 * 1024 * 1024:
                raise ValueError('Invalid SDK packet')
            payload = self.receive(size)
            if reply_command == 10 and reply_device == device:
                acked, status = struct.unpack('<II', payload)
                if acked == command:
                    if status:
                        raise ValueError(f'OpenRGB rejected command {command}: status {status}')
                    if ack:
                        return payload
            if (reply_device, reply_command) == (device, command):
                return payload
        raise TimeoutError('No matching SDK response')

    def controller(self, index):
        return parse_controller(self.request(index, 1, pack('I', 6)))

    def controllers(self):
        data = Reader(self.request(0, 0))
        count = data.number()
        if count > 1024:
            raise ValueError('Invalid controller count')
        ids = [data.number() for _ in range(count)]
        return [dict(self.controller(i), sdk_id=i) for i in ids]

    def profile_names(self):
        data = Reader(self.request(0, 150))
        declared_size = data.number()
        if declared_size != len(data.data):
            raise ValueError('SDK profile-list size mismatch')
        names = [data.text() for _ in range(data.number('H'))]
        if data.pos != len(data.data):
            raise ValueError('Unexpected SDK profile-list fields')
        return names

    def active_profile(self):
        return self.request(0, 156).rstrip(b'\0').decode()

    def load_profile(self, name):
        self.request(0, 152, name.encode() + b'\0', ack=True)


def location(value):
    # Kernel device numbers can change at boot; keep bus description/address.
    return re.sub(r'/dev/(?:i2c-\d+|hidraw\d+)', '/dev/device', value)


def mode_plan(active, available):
    matches = [i for i, mode in enumerate(available) if mode['name'] == active['name']]
    if len(matches) != 1:
        raise ValueError(f"Unavailable mode: {active['name']}")
    index = matches[0]
    mode = dict(available[index])
    for key in ('flags', 'speed_min', 'speed_max', 'brightness_min', 'brightness_max', 'colors_min', 'colors_max'):
        if active[key] != mode[key]:
            raise ValueError(f"Mode capabilities changed: {active['name']}/{key}")
    for key in ('speed', 'brightness', 'direction', 'color_mode'):
        mode[key] = active[key]
    mode['colors'] = active.get('colors', [])
    for key in ('speed', 'brightness'):
        if not min(mode[key + '_min'], mode[key + '_max']) <= mode[key] <= max(mode[key + '_min'], mode[key + '_max']):
            raise ValueError(f'Invalid saved {key}')
    if any(type(c) is not int or not 0 <= c <= 0xFFFFFF for c in mode['colors']):
        raise ValueError('Invalid effect colors')
    if mode['color_mode'] == 2 and not mode['colors_min'] <= len(mode['colors']) <= mode['colors_max']:
        raise ValueError('Invalid effect color count')
    return index, mode


def plan(profile, live):
    if profile.get('plugins') or profile.get('base_color_enabled'):
        raise ValueError('Plugin/base-color profiles require native OpenRGB support')
    operations, used = [], set()
    if not profile.get('controllers'):
        raise ValueError('Profile contains no controllers')
    for saved in profile['controllers']:
        candidates = [i for i, device in enumerate(live)
                      if device['name'] == saved['name'] and device['type'] == saved['type']
                      and (device['serial'] == saved['serial'] if saved.get('serial')
                           else location(device['location']) == location(saved['location']))]
        if len(candidates) != 1 or candidates[0] in used:
            raise ValueError(f"Missing/ambiguous controller: {saved['name']} {saved['location']}")
        index = candidates[0]
        used.add(index)
        device = live[index]
        if len(saved['zones']) != len(device['zones']):
            raise ValueError(f"Zone layout changed: {saved['name']}")
        zone_modes = []
        for zone_index, (source, target) in enumerate(zip(saved['zones'], device['zones'])):
            if source['name'] != target['name'] or source['leds_count'] != target['leds_count']:
                raise ValueError(f"Zone layout changed: {saved['name']}/{source['name']}; resize in OpenRGB first")
            if source.get('segments'):
                raise ValueError('Segment layout profiles require native OpenRGB configuration')
            active_zone = source.get('active_mode', -1)
            if active_zone == -1:
                if target['modes']:
                    zone_modes.append((zone_index, -1, None))
            else:
                zi, zm = mode_plan(source['modes'][active_zone], target['modes'])
                zone_modes.append((zone_index, zi, zm))
        colors = saved['colors']
        if len(colors) != len(device['colors']) or any(type(c) is not int or not 0 <= c <= 0xFFFFFF for c in colors):
            raise ValueError('Invalid per-LED color array')
        active = saved['modes'][saved['active_mode']]
        mode_index, mode = mode_plan(active, device['modes'])
        operations.append((device['sdk_id'], saved, mode_index, mode, colors, zone_modes))
    return operations


def mode_bytes(mode):
    return (string(mode['name']) + pack('I' * len(FIELDS), *(mode[key] for key in FIELDS))
            + pack('H', len(mode['colors'])) + pack('I' * len(mode['colors']), *mode['colors']))


def ene_target(saved, mode, colors):
    """Return expected ENE hardware registers, or None for other devices."""
    match = re.search(r'\((/dev/i2c-\d+)\), address (0x[0-9a-fA-F]+)$', saved['location'])
    if saved['name'] != 'ENE DRAM' or not match:
        return None
    if not saved.get('version', '').startswith('AUDA0-'):
        raise ValueError(f"Unsupported ENE hardware verification: {saved.get('version', 'unknown')}")
    target = {
        'path': match.group(1),
        'address': int(match.group(2), 16),
        'location': saved['location'],
        'direct': mode['name'] == 'Direct',
    }
    if target['direct']:
        target['colors'] = b''.join(bytes((color & 0xFF,
                                          (color >> 16) & 0xFF,
                                          (color >> 8) & 0xFF)) for color in colors)
    else:
        if mode['name'] not in ENE_MODE_VALUES:
            raise ValueError(f"Unknown ENE mode for hardware verification: {mode['name']}")
        value = ENE_MODE_VALUES[mode['name']]
        if mode['color_mode'] == 3:
            value = {'Breathing': 6, 'Chase Fade': 8, 'Chase': 10}.get(mode['name'], value)
        target['mode'] = value
        if mode['color_mode'] == 1:
            target['colors'] = b''.join(bytes((color & 0xFF,
                                              (color >> 16) & 0xFF,
                                              (color >> 8) & 0xFF)) for color in colors)
    return target


def verify_ene_hardware(targets):
    """Verify physical ENE registers while the OpenRGB process is quiesced."""
    if not targets:
        return
    server_pid = int(os.environ['OPENRGB_SERVER_PID'])
    os.kill(server_pid, signal.SIGSTOP)
    try:
        library = ctypes.CDLL('libi2c.so.0', use_errno=True)
        for target in targets:
            fd = os.open(target['path'], os.O_RDWR)
            try:
                fcntl.ioctl(fd, I2C_SLAVE, target['address'])

                def read(register):
                    swapped = (register >> 8) | ((register & 0xFF) << 8)
                    if library.i2c_smbus_write_word_data(fd, 0, swapped) < 0:
                        raise OSError(ctypes.get_errno(), 'ENE register selection failed')
                    value = library.i2c_smbus_read_byte_data(fd, 0x81)
                    if value < 0:
                        raise OSError(ctypes.get_errno(), 'ENE register read failed')
                    return value

                direct = read(0x8020)
                if direct != int(target['direct']):
                    raise ValueError(f"ENE Direct-mode hardware mismatch: {target['location']}")
                if not target['direct'] and read(0x8021) != target['mode']:
                    raise ValueError(f"ENE mode hardware mismatch: {target['location']}")
                if 'colors' in target:
                    base = 0x8100 if target['direct'] else 0x8160
                    actual = bytes(read(base + offset) for offset in range(len(target['colors'])))
                    if actual != target['colors']:
                        raise ValueError(f"ENE color hardware mismatch: {target['location']}")
            finally:
                os.close(fd)
            print(f"Verified ENE hardware: {target['location']}")
    finally:
        os.kill(server_pid, signal.SIGCONT)


def state_matches(actual, mode, colors, zone_modes):
    actual_mode = actual['modes'][actual['active_mode']]
    keys = ('name', 'speed', 'brightness', 'direction', 'color_mode', 'colors')
    for zone_index, zi, zm in zone_modes:
        zone = actual['zones'][zone_index]
        if zone['active_mode'] != zi:
            return False
        if zm and not all(zone['modes'][zi][key] == zm[key] for key in keys):
            return False
    return all(actual_mode[key] == mode[key] for key in keys) and actual['colors'] == colors


def verify_loaded_state(client, operations):
    """Accept a native load only when SDK state and physical RAM agree."""
    targets = []
    for index, saved, _, mode, colors, zone_modes in operations:
        actual = client.controller(index)
        if not state_matches(actual, mode, colors, zone_modes):
            raise ValueError(f"Native state mismatch: {saved['name']}")
        target = ene_target(actual, mode, colors)
        if target:
            targets.append(target)
    verify_ene_hardware(targets)


def blend_colors(source, target, progress):
    """Interpolate each RGB channel; packed integers must not be blended."""
    amount = progress * progress * (3 - 2 * progress)
    return [sum(round(((a >> shift) & 255) * (1 - amount)
                      + ((b >> shift) & 255) * amount) << shift
                for shift in (0, 8, 16)) for a, b in zip(source, target)]


def transition_profile(profile, live):
    """Build a disposable Direct-mode bridge, preserving the outgoing colors."""
    bridge = copy.deepcopy(profile)
    bridge['profile_name'] = 'wallpaper-transition-' + uuid.uuid4().hex
    bridge.pop('plugins', None)
    bridge.pop('base_color', None)
    bridge['base_color_enabled'] = False
    # Validate the destination layout even for native/plugin profiles.
    destination = copy.deepcopy(bridge)
    operations = plan(destination, live)
    by_id = {device['sdk_id']: device for device in live}
    targets = {}
    for saved, operation in zip(bridge['controllers'], operations):
        index = operation[0]
        targets[index] = list(saved['colors'])
        saved['colors'] = list(by_id[index]['colors'])
        direct = next((i for i, mode in enumerate(saved['modes'])
                       if mode['name'] == 'Direct'), None)
        if direct is None:
            raise ValueError(f"Crossfade needs Direct mode: {saved['name']}")
        saved['active_mode'] = direct
        for zone in saved['zones']:
            zone['active_mode'] = -1
    return bridge, plan(bridge, live), targets


def write_transition_colors(client, index, saved, colors):
    # UPDATEZONELEDS takes the device mutex and performs its hardware write
    # before ACK. UPDATELEDS merely queues a background write, so its ACK
    # cannot safely pace a fade or precede physical register verification.
    offset = 0
    for zone_index, zone in enumerate(saved['zones']):
        count = zone['leds_count']
        if count:
            data = pack('IH', zone_index, count) + pack('I' * count, *colors[offset:offset + count])
            client.request(index, 1051, pack('I', len(data) + 4) + data, ack=True)
        offset += count


def crossfade(client, operations, targets, seconds):
    start = time.monotonic()
    frames = 0
    while True:
        progress = min(1.0, (time.monotonic() - start) / seconds)
        for index, saved, _, _, colors, _ in operations:
            blended = blend_colors(colors, targets[index], progress)
            write_transition_colors(client, index, saved, blended)
        frames += 1
        if progress == 1.0:
            break
        time.sleep(max(0, start + frames / 30 - time.monotonic()))
    print(f'Crossfaded {len(operations)} controllers in '
          f'{time.monotonic() - start:.2f}s ({frames} frames)')


@contextmanager
def profile_transition(client, profile, live, seconds):
    temporary_name = None
    try:
        if seconds:
            try:
                bridge, operations, targets = transition_profile(profile, live)
                preparation_start = time.monotonic()
                by_id = {device['sdk_id']: device for device in live}
                changed = [op for op in operations
                           if not state_matches(by_id[op[0]], op[3], by_id[op[0]]['colors'], op[5])]
                # Loading even an empty controller list stops the outgoing
                # plugin. Leave controllers already in Direct alone, avoiding
                # redundant mode writes and their settling delay.
                bridge['controllers'] = [op[1] for op in changed]
                # Profile upload/delete require a loopback local-client grant.
                client.request(0, 52, pack('I', 1 << 16), ack=True)
                client.request(0, 154, json.dumps(bridge).encode() + b'\0', ack=True)
                temporary_name = bridge['profile_name']
                client.load_profile(temporary_name)
                if any(ene_target(by_id[op[0]], op[3], op[4]) for op in changed):
                    time.sleep(HARDWARE_SETTLE_SECONDS)
                # An outgoing effect can render one last frame while its stop
                # notification is handled. Start from that final live frame,
                # rather than replaying the earlier snapshot over it.
                stopped = {device['sdk_id']: device for device in client.controllers()}
                for index, saved, _, _, colors, _ in operations:
                    colors[:] = stopped[index]['colors']
                    # Native loading can leave an ENE hardware frame behind
                    # its SDK cache when an effect stops. Synchronize colors
                    # with synchronous writes, without replaying settled modes.
                    write_transition_colors(client, index, saved, colors)
                try:
                    verify_loaded_state(client, operations)
                except ValueError as error:
                    print(f'{error}; preparing Direct mode with serialized writes')
                    apply(client, operations)
                print(f'Prepared crossfade in {time.monotonic() - preparation_start:.2f}s')
                crossfade(client, operations, targets, seconds)
            except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error) as error:
                # Always proceed to the real target, including after a partial
                # fade, so failure cannot strand the lights at an interim color.
                print(f'Transition unavailable: {error}; applying target directly')
        yield
    finally:
        if temporary_name:
            try:
                client.request(0, 153, temporary_name.encode() + b'\0', ack=True)
            except (OSError, ValueError) as error:
                print(f'Temporary transition profile cleanup failed: {error}', file=sys.stderr)


def apply(client, operations):
    ene_targets = []
    for index, saved, mode_index, mode, colors, zone_modes in operations:
        mode_data = pack('i', mode_index) + mode_bytes(mode)
        client.request(index, 1101, pack('I', len(mode_data) + 4) + mode_data, ack=True)
        # SDK acknowledgements precede the asynchronous hardware write. Never
        # overlap that write with a color or another controller operation.
        time.sleep(HARDWARE_SETTLE_SECONDS)
        for zone_index, zi, zm in zone_modes:
            data = pack('ii', zone_index, zi) + (mode_bytes(zm) if zm else b'')
            client.request(index, 1103, pack('I', len(data) + 4) + data, ack=True)
            time.sleep(HARDWARE_SETTLE_SECONDS)
        color_data = pack('H', len(colors)) + pack('I' * len(colors), *colors)
        client.request(index, 1050, pack('I', len(color_data) + 4) + color_data, ack=True)
        time.sleep(HARDWARE_SETTLE_SECONDS)
        deadline = time.monotonic() + 3
        while True:
            actual = client.controller(index)
            if state_matches(actual, mode, colors, zone_modes):
                break
            if time.monotonic() >= deadline:
                raise ValueError(f"State readback mismatch: {saved['name']} {saved['location']}")
            time.sleep(0.1)
        # Use the live location because Linux I2C device numbers can change at
        # boot even when the saved controller identity still matches.
        target = ene_target(actual, mode, colors)
        if target:
            ene_targets.append(target)
        print(f"Verified OpenRGB state: {saved['name']} ({saved['location']}): {mode['name']}, {len(colors)} LEDs")
    time.sleep(HARDWARE_SETTLE_SECONDS)
    verify_ene_hardware(ene_targets)


def apply_native_profile(client, profile):
    """Load an integrated OpenRGB 1.0 profile, including plugin state."""
    profile_name = profile.get('profile_name')
    if not profile_name or profile_name not in client.profile_names():
        raise ValueError(f'Native OpenRGB profile is not registered: {profile_name!r}')

    client.load_profile(profile_name)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if client.active_profile() == profile_name:
            break
        time.sleep(0.1)
    else:
        raise ValueError(f'OpenRGB did not activate profile: {profile_name}')

    autostart_effects = [effect for plugin in profile.get('plugins', {}).values()
                         for effect in plugin.get('Effects', []) if effect.get('AutoStart')]
    if autostart_effects:
        snapshots = []
        for _ in range(4):
            snapshots.append([controller['colors'] for controller in client.controllers()])
            time.sleep(0.35)
        changed = [any(snapshot[index] != snapshots[0][index]
                       for snapshot in snapshots[1:])
                   for index in range(len(snapshots[0]))]
        if not any(changed):
            raise ValueError(f'Autostart effect did not animate any controller: {profile_name}')
        print(f'Verified native OpenRGB profile: {profile_name}; animated controllers: '
              f'{sum(changed)}/{len(changed)}')
    else:
        print(f'Verified native OpenRGB profile: {profile_name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', nargs='?')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--fade-seconds', type=float,
                        default=os.environ.get('OPENRGB_FADE_SECONDS', '0'),
                        help='crossfade duration, 0 disables (default: OPENRGB_FADE_SECONDS or 0)')
    args = parser.parse_args()
    if not 0 <= args.fade_seconds <= 5:
        parser.error('--fade-seconds must be between 0 and 5')
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    with (runtime / 'openrgb-sdk-apply.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        client = Client()
        try:
            live = client.controllers()
            if args.inspect:
                print(json.dumps({'controllers': live}, indent=2))
                return
            with open(args.profile) as source:
                profile = json.load(source)
            if profile.get('plugins'):
                profile_name = profile.get('profile_name')
                if not profile_name or profile_name not in client.profile_names():
                    raise ValueError(f'Native OpenRGB profile is not registered: {profile_name!r}')
                if args.check:
                    print(f'Validated native OpenRGB profile: {profile_name}; no writes')
                else:
                    with profile_transition(client, profile, live, args.fade_seconds):
                        apply_native_profile(client, profile)
                return
            operations = plan(profile, live)
            if args.check:
                print(f'Validated {len(operations)} controller mappings; no writes')
            else:
                with profile_transition(client, profile, live, args.fade_seconds):
                    apply_controller_profile(client, profile, operations)
        finally:
            client.sock.close()


def apply_controller_profile(client, profile, operations):
    # Loading a non-plugin profile tells integrated plugins to stop
    # effects from the previous profile. Verify the native load
    # first; replay serially only if it did not reach the hardware.
    profile_name = profile.get('profile_name')
    if profile_name in client.profile_names():
        client.load_profile(profile_name)
        time.sleep(HARDWARE_SETTLE_SECONDS)
        try:
            verify_loaded_state(client, operations)
        except ValueError as error:
            print(f'{error}; using serialized hardware writes')
            # Preserve the original settling budget before recovery.
            time.sleep(2 - HARDWARE_SETTLE_SECONDS)
        else:
            print(f'Verified native controller profile: {profile_name}')
            return
    apply(client, operations)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error) as error:
        print(f'RGB profile failed: {error}', file=sys.stderr)
        sys.exit(1)
