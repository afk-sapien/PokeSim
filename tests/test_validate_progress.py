"""python -m pokesim.replay validate-progress replays a copied Gen I checkpoint."""
import hashlib

import pytest
from pokecore.emulator_state import runtime_provenance

from pokesim.checkpoints import CheckpointStore
from pokesim.replay import validate_progress

ROM = b'not a cartridge'


class Loaded(Exception):
    """Ends the replay once the state is loaded, since no cartridge plays here."""


class Emulator:
    def __init__(self, rom, **kwargs):
        pass

    def set_emulation_speed(self, speed):
        pass

    def load_state(self, stream):
        raise Loaded(stream.read())

    def stop(self, save):
        pass


def checkpoint(tmp_path, raw):
    metadata = {'rom_sha1': hashlib.sha1(ROM).hexdigest(), 'policy': 'strategic', 'policy_state': {},
                'run_memory': {}, 'emulator': runtime_provenance(), 'frame': 0}
    return CheckpointStore(tmp_path / 'states').write_checkpoint(raw, metadata, name='journal-1.state', compress=True)


def test_a_compressed_journal_checkpoint_reaches_the_emulator_as_its_raw_state(tmp_path, monkeypatch):
    rom = tmp_path / 'rom.gb'
    rom.write_bytes(ROM)
    monkeypatch.setattr(validate_progress, 'PyBoy', Emulator)
    with pytest.raises(Loaded) as loaded:
        validate_progress.run(rom, checkpoint(tmp_path, b'raw state'), 1)
    assert loaded.value.args == (b'raw state',)
