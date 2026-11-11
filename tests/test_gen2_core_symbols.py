"""pokecore's Gen II memory map agrees with the symbols in PokeSim's generated game data."""
import json
import os
from pathlib import Path

import pytest

from pokecore.gen2 import memory_map


@pytest.mark.parametrize('version', ['gold', 'silver', 'crystal'])
def test_core_memory_map_matches_the_generated_symbols(version):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    generated = json.loads((Path(directory) / 'gen2' / version / 'data.json').read_text())['symbols']
    wrong = {name: (bank, hex(address), generated.get(name))
             for name, (bank, address) in memory_map.symbols(version).items()
             if generated.get(name) != [bank, address]}
    assert not wrong
