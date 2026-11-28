import hashlib
import json
import os
import sqlite3

from pokesim.audio import AudioFeed
from pokesim.emulator import Emulator
from pokesim.replay.profile_simulation import capture, listen


def test_capture_takes_the_newest_autosave_in_the_order_the_runtime_resumes(tmp_path):
    source = tmp_path / 'source'
    (source / 'states').mkdir(parents=True)
    sqlite3.connect(source / 'pokesim.sqlite').close()
    (source / 'adventure.json').write_text(json.dumps({'settings': {'version': 'red'}}))
    # A reward checkpoint, then a newer trade checkpoint whose name sorts before it.
    for at, name in ((1, 'auto-v1-reward-1'), (2, 'auto-v1-link-2')):
        state = source / 'states' / f'{name}.state'
        state.write_bytes(name.encode())
        state.with_suffix('.json').write_text(json.dumps({'sha256': hashlib.sha256(name.encode()).hexdigest(),
                                                          'frame': at}))
        os.utime(state, ns=(at * 10**18, at * 10**18))
    (tmp_path / 'rom.gb').write_bytes(b'')
    (tmp_path / 'game-data').mkdir()
    capture(source, tmp_path / 'fixture', tmp_path / 'rom.gb', tmp_path / 'game-data')
    fixture = json.loads((tmp_path / 'fixture' / 'fixture.json').read_text())
    assert fixture['checkpoint'] == 'auto-v1-link-2.state'
    copied = sorted(path.name for path in (tmp_path / 'fixture' / 'adventure' / 'states').iterdir())
    assert copied == ['auto-v1-link-2.json', 'auto-v1-link-2.state']


def test_audio_mode_reads_the_feed_as_the_page_does():
    emu = Emulator.__new__(Emulator)
    emu.speed, emu.paused, emu.manual_mode = 1, False, False
    emu.audio = AudioFeed()
    sequence = listen(emu, -1)
    assert sequence == 0
    assert emu.audio.active()
    emu.audio.publish(b'ab')
    assert listen(emu, sequence) == 1
