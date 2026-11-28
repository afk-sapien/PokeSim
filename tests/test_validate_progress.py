"""python -m pokesim.replay validate-progress replays a copied Gen I checkpoint."""
import hashlib

import pytest
from pokecore.emulator_state import runtime_provenance

from pokesim import yellow
from pokesim.checkpoints import CheckpointStore
from pokesim.policies import progression
from pokesim.replay import validate_progress

ROM = b'not a cartridge'


@pytest.fixture
def opened(monkeypatch):
    """The emulators the replay opens. They play no cartridge and read as a new game in Pallet Town."""
    emulators = []

    class Emulator:
        def __init__(self, rom, **kwargs):
            self.memory, self.state = bytearray(0x10000), None
            emulators.append(self)

        def set_emulation_speed(self, speed):
            pass

        def load_state(self, stream):
            self.state = stream.read()

        def tick(self, count, render=False):
            pass

        def stop(self, save):
            pass

    class YellowEmulator(Emulator):
        pass
    monkeypatch.setattr(validate_progress, 'PyBoy', Emulator)
    monkeypatch.setattr(yellow, 'YellowEmulator', YellowEmulator)
    return emulators


def replay(folder, raw=b'raw state'):
    folder.mkdir(exist_ok=True)
    rom = folder / 'rom.gb'
    rom.write_bytes(ROM)
    metadata = {'rom_sha1': hashlib.sha1(ROM).hexdigest(), 'policy': 'strategic', 'policy_state': {},
                'run_memory': {}, 'emulator': runtime_provenance(), 'frame': 0}
    checkpoint = CheckpointStore(folder / 'states').write_checkpoint(raw, metadata, name='journal-1.state',
                                                                     compress=True)
    return validate_progress.run(rom, checkpoint, 0)


def test_a_compressed_journal_checkpoint_reaches_the_emulator_as_its_raw_state(tmp_path, opened):
    replay(tmp_path)
    assert [emulator.state for emulator in opened] == [b'raw state']


def test_a_yellow_checkpoint_replays_as_yellow_on_the_yellow_emulator(tmp_path, monkeypatch, opened):
    monkeypatch.setattr(yellow, 'YELLOW_SHA1', hashlib.sha1(ROM).hexdigest())
    # Under Red's game data a Yellow replay is refused, as a scripted run refuses it.
    with pytest.raises(ValueError, match='POKESIM_GEN1_VARIANT=yellow'):
        replay(tmp_path / 'red')
    monkeypatch.setattr(progression, 'YELLOW', True)
    result = replay(tmp_path / 'yellow')
    assert (result['edition'], [type(emulator).__name__ for emulator in opened]) == ('yellow', ['YellowEmulator'])
