import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from pokesim.audio import AudioFeed, MAX_FRAMES, enable_checkpoint_sound
from pokesim.emulator import Emulator
from pokesim.web.app import create_app


def test_audio_feed_expires_and_bounds_slow_listeners(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr('pokesim.audio.time.monotonic', lambda: clock[0])
    feed = AudioFeed()
    assert not feed.active()
    assert feed.read(-1, 'playing')[:2] == (0, b'')
    assert feed.active()
    for _ in range(MAX_FRAMES + 50):
        feed.publish(b'\x01\x02')
    count = MAX_FRAMES + 50
    assert feed.read(0, 'playing')[:2] == (count, b'\x01\x02' * MAX_FRAMES)
    assert feed.read(count - 1, 'playing')[:2] == (count, b'\x01\x02')
    assert feed.read(count, 'playing')[:2] == (count, b'')
    clock[0] += 0.5
    feed.publish(b'cd')
    assert feed.read(0, 'playing')[:2] == (count + 1, b'cd')
    clock[0] += 1
    assert not feed.active()
    assert feed.read(0, 'playing')[:2] == (count + 1, b'')
    feed.publish(b'ab')
    assert feed.read(0, 'paused')[:2] == (count + 2, b'')


def test_audio_is_isolated_between_listeners_and_adventures():
    one, two = AudioFeed(), AudioFeed()
    one.read(-1, 'playing')
    one.publish(b'ab')
    assert one.read(0, 'playing')[:2] == (1, b'ab')
    assert one.read(0, 'playing')[:2] == (1, b'ab')
    assert two.read(0, 'playing')[:2] == (0, b'')


@pytest.mark.parametrize('speed', [0.5, 1, 4, 16, 50])
def test_audio_measures_actual_pace_for_playback(monkeypatch, speed):
    clock = [10.0]
    monkeypatch.setattr('pokesim.audio.time.monotonic', lambda: clock[0])
    feed = AudioFeed()
    feed.read(-1, 'playing')
    for index in range(12):
        clock[0] = 10 + index / (60 * speed)
        feed.publish(b'ab')
    sequence, data, measured = feed.read(0, 'playing')
    assert sequence == 12 and data == b'ab' * 12
    assert measured == pytest.approx(speed)


@pytest.mark.parametrize('speed,paused,manual,state', [
    (1, False, False, 'playing'), (16, False, False, 'playing'),
    (0, False, False, 'playing'), (0.5, False, False, 'playing'),
    (1, True, False, 'paused'), (16, True, True, 'playing'),
])
def test_audio_endpoint_reports_playback_without_changing_speed(tmp_path, speed, paused, manual, state):
    emu = Emulator.__new__(Emulator)
    emu.speed, emu.paused, emu.manual_mode = speed, paused, manual
    emu.audio = AudioFeed()
    store = SimpleNamespace(shots=tmp_path)
    with TestClient(create_app(emu, store)) as client:
        response = client.get('/api/audio')
        assert response.status_code == 200
        assert response.headers['X-Audio-State'] == state
        assert response.headers['X-Audio-Rate'] == '48000'
        assert float(response.headers['X-Audio-Speed']) > 0
        assert response.headers['Cache-Control'] == 'no-store'
        emu.audio.publish(b'\x01\x02')
        response = client.get('/api/audio?after=0')
        assert response.content == (b'\x01\x02' if state == 'playing' else b'')
        assert client.get('/api/audio?after=-2').status_code == 422
    assert emu.speed == speed


@pytest.mark.parametrize('speed', [0.5, 1, 4, 16, 0])
def test_ticks_sample_every_frame_only_for_a_listener(speed):
    from test_frame_publishing import emulator
    emu = emulator()
    emu._sync_audio = Mock()
    emu.pb.sound.raw_buffer = b'ab'
    emu.pb.sound.raw_buffer_head = 2
    emu.speed = speed
    emu._tick(12)
    assert emu.pb.tick.call_count == 3
    assert all(not call.kwargs['sound'] for call in emu.pb.tick.call_args_list)
    emu.pb.tick.reset_mock()
    emu.audio.read(-1, 'playing')
    emu._tick(12)
    assert emu.pb.tick.call_count == 12
    assert all(call.kwargs['sound'] for call in emu.pb.tick.call_args_list)
    assert emu.audio.read(0, 'playing')[1] == b'ab' * 12
    emu.audio.until = 0
    emu.pb.tick.reset_mock()
    emu._tick(12)
    assert emu.pb.tick.call_count == 3
    assert all(not call.kwargs['sound'] for call in emu.pb.tick.call_args_list)


def test_real_rom_sound_switch_preserves_save_and_queued_buttons(tmp_path):
    rom = Path('roms/pokered.gb')
    if not rom.is_file():
        pytest.skip('Private ROM is not available')
    from pyboy import PyBoy
    from pyboy.utils import WindowEvent
    emu = Emulator.__new__(Emulator)
    emu.rom = rom
    emu.isolated_ram = True
    emu.audio = AudioFeed()
    emu._audio_enabled = False
    emu.pb = emu._boot()
    try:
        emu.pb.tick(300, render=False, sound=False)
        before = bytes(emu.pb.memory[0xA000:0xE000])
        state = io.BytesIO()
        emu.pb.save_state(state)
        raw = state.getvalue()
        fixed = enable_checkpoint_sound(raw)
        assert fixed != raw and len(fixed) == len(raw)
        # Only the serialized APU changes. CPU, game RAM, and cartridge save stay intact.
        assert fixed[:9144] == raw[:9144]
        assert fixed[10900:] == raw[10900:]
        assert enable_checkpoint_sound(fixed) == fixed
        emu.pb.button_press('a')
        emu._sync_audio(True)
        assert bytes(emu.pb.memory[0xA000:0xE000]) == before
        assert int(emu.pb.events[-1]) == WindowEvent.PRESS_BUTTON_A
        buffers = []
        for _ in range(180):
            emu.pb.tick(1, render=False, sound=True)
            buffers.append(bytes(emu.pb.sound.raw_buffer[:emu.pb.sound.raw_buffer_head]))
        assert all(len(buffer) > 0 for buffer in buffers)
        assert max(b''.join(buffers)) > 0
        emu.pb.button_release('a')
        before = bytes(emu.pb.memory[0xA000:0xE000])
        emu._sync_audio(False)
        assert bytes(emu.pb.memory[0xA000:0xE000]) == before
        assert int(emu.pb.events[-1]) == WindowEvent.RELEASE_BUTTON_A
        emu.pb.tick(120, render=False, sound=False)
        emu._sync_audio(True)
        emu.pb.tick(1, render=False, sound=True)
        assert emu.pb.sound.raw_buffer_head > 0
        # Save/export tools still accept a checkpoint made while listening.
        active = io.BytesIO()
        emu.pb.save_state(active)
        other = PyBoy(str(rom), window='null', sound_emulated=False,
                      ram_file=io.BytesIO(bytes(32768)))
        try:
            other.load_state(io.BytesIO(active.getvalue()))
            assert bytes(other.memory[0xA000:0xE000]) == bytes(emu.pb.memory[0xA000:0xE000])
        finally:
            other.stop(save=False)
    finally:
        emu.pb.stop(save=False)


def test_checkpoint_adapter_leaves_unknown_formats_untouched():
    for raw in [b'', b'garbage', bytes(20000)]:
        assert enable_checkpoint_sound(raw) == raw
