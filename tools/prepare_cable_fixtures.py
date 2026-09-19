"""Prepare disposable, explicitly synthetic party fixtures for Cable Club testing."""
import argparse
import io
from pathlib import Path

from pyboy import PyBoy
from pokesim.ram import read_snapshot
from pokesim.screen import Screen
from pokesim.strategy_data import MOVES, SPECIES
from pokesim.trade.boxes import encode_text
import re


def symbols(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{2}):([0-9a-fA-F]{4}) (.+)', line)
        if match:
            result[match[3]] = (int(match[1], 16), int(match[2], 16))
    return result


def press(pb, button, frames=8, after=24):
    pb.button_press(button)
    pb.tick(frames)
    pb.button_release(button)
    pb.tick(after)


def prepare(rom, sym, state, out, name, species, default_name=False):
    pb = PyBoy(str(rom), window='null', sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    with state.open('rb') as f:
        pb.load_state(f)
    syms = symbols(sym)
    def put(key, data):
        addr = syms[key][1]
        pb.memory[addr:addr + len(data)] = data
    put('wPlayerName', encode_text(name))
    put('wPlayerID', [0x12, 0x34] if name == 'RED' else [0x56, 0x78])
    level = 30
    row = SPECIES[species]
    stats = [((base + 10) * 2 * level // 100) + (level + 10 if i == 0 else 5)
             for i, base in enumerate(row['stats'])]
    mon = bytearray(44)
    mon[0] = species
    mon[1:3] = stats[0].to_bytes(2, 'big')
    mon[3] = level
    mon[5:7] = bytes(row['types'])
    mon[7] = row['catch_rate']
    moves = (row['initial_moves'] + [move for learned, move in row['learnset'] if learned <= level])[-4:]
    moves += [0] * (4 - len(moves))
    mon[8:12] = bytes(moves)
    mon[12:14] = bytes([0x12, 0x34] if name == 'RED' else [0x56, 0x78])
    assert row['growth'] == 'MEDIUM_SLOW'
    experience = 6 * level ** 3 // 5 - 15 * level ** 2 + 100 * level - 140
    mon[14:17] = experience.to_bytes(3, 'big')
    mon[27:29] = bytes([0xaa, 0xaa])
    mon[29:33] = bytes(MOVES[move]['pp'] if move else 0 for move in moves)
    mon[33] = level
    for i, stat in enumerate(stats):
        mon[34 + i * 2:36 + i * 2] = stat.to_bytes(2, 'big')
    put('wPartyMon1', mon)
    put('wPartySpecies', [species])
    put('wPartyMon1Nick', encode_text(row['name'].upper() if default_name else 'SPOOKY' if name == 'RED' else 'SPOON'))
    put('wPartyMon1OT', encode_text(name))
    press(pb, 'start')
    for _ in range(20):
        screen = Screen(pb.memory)
        row = next((i for i, line in enumerate(screen.rows) if 'SAVE' in line), None)
        if row is not None and screen.cursor:
            if screen.cursor[1] == row:
                press(pb, 'a')
                break
            press(pb, 'down' if screen.cursor[1] < row else 'up')
        else:
            pb.tick(30)
    saved = False
    for _ in range(60):
        screen = Screen(pb.memory)
        if 'SAVED' in screen.text.upper():
            saved = True
            pb.tick(120)
            break
        press(pb, 'a')
    assert saved, Screen(pb.memory).text
    ram = io.BytesIO()
    pb.stop(ram_file=ram)
    (out / f'{name.lower()}.sav').write_bytes(ram.getvalue())
    print(name, 'saved synthetic fixture', flush=True)


def cold_boot(rom, save, output):
    pb = PyBoy(str(rom), ram_file=io.BytesIO(save.read_bytes()), window='null', sound_emulated=False, log_level='ERROR')
    pb.set_emulation_speed(0)
    pb.tick(180)
    for i in range(160):
        if 'CONTINUE' in Screen(pb.memory).text:
            press(pb, 'a', after=240)
            press(pb, 'a', after=240)
            assert 'CONTINUE' not in Screen(pb.memory).text
            s = read_snapshot(pb.memory, 0)
            assert s.valid and s.started and s.map == 89
            # Save data contains ROM map pointers. Reenter through a real warp
            # so the recipient version rebuilds its map header from its own ROM.
            for _ in range(8):
                press(pb, 'down', after=120)
                if read_snapshot(pb.memory, 0).map != 89:
                    break
            assert read_snapshot(pb.memory, 0).map != 89
            for _ in range(8):
                press(pb, 'up', after=120)
                if read_snapshot(pb.memory, 0).map == 89:
                    break
            assert read_snapshot(pb.memory, 0).map == 89
            with output.open('wb') as f:
                pb.save_state(f)
            print(rom.name, 'cold boot', [(m.nick, m.species) for m in read_snapshot(pb.memory,0).party], flush=True)
            pb.stop(save=False)
            return
        press(pb, 'start' if i % 3 == 0 else 'a')
    raise RuntimeError(Screen(pb.memory).text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--default-names', action='store_true')
    parser.add_argument('--left-species', type=int, default=147)
    parser.add_argument('--right-species', type=int, default=38)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    for name, species in [('RED', args.left_species), ('BLUE', args.right_species)]:
        prepare(args.reference / 'pokered.gbc', args.reference / 'pokered.sym',
                args.state, args.out, name, species, args.default_names)
        cold_boot(args.reference / ('pokered.gbc' if name == 'RED' else 'pokeblue.gbc'),
                  args.out / f'{name.lower()}.sav', args.out / f'{name.lower()}.state')


if __name__ == '__main__':
    main()
