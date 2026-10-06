"""Exercise a paired Gen II cable exchange on disposable checkpoint copies."""
import argparse
import json
from pathlib import Path

from pokesim.gen2.cable import CableSide
from pokesim.gen2.data import GameData
from pokesim.gen2.menus import choose
from pokesim.gen2.navigation import Navigator
from pokesim.gen2.ram import read_snapshot
from pokesim.interactions.link_worker import CableParticipant


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left', required=True)
    parser.add_argument('--right', required=True)
    parser.add_argument('--left-game', default='gold')
    parser.add_argument('--right-game', default='silver')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sides = []
    try:
        for name, game, state in [('left', args.left_game, args.left), ('right', args.right_game, args.right)]:
            data = GameData.load('.release-local/gen2-data', game)
            spec = CableParticipant(name, f'.release-local/gen2/{game}.gbc', state, party_slot=1)
            side = CableSide(spec, data)
            for button in ('b', 'b', 'b', 'b', 'b', 'left', 'left', 'down'):
                side.pb.button_press(button)
                side.pb.tick(8, True)
                side.pb.button_release(button)
                side.pb.tick(24, True)
            side.nav = Navigator(data)
            sides.append(side)
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        for i, side in enumerate(sides):
            side.attach(i + 1)
        previous = [None, None]
        with (args.output / 'trace.jsonl').open('w') as log:
            for step in range(1600):
                buttons = []
                for i, side in enumerate(sides):
                    s = read_snapshot(side.pb.memory, side.data, side.frame)
                    m = side.memory
                    side.nav.observe(s)
                    name = side.data.maps[s.map]['constant']
                    button = 'a'
                    if side.counts['ExitLinkCommunications']:
                        button = None
                    elif side.counts['SaveAfterLinkTrade'] and side.counts['Gen2ToGen2LinkComms'] >= 2:
                        button = 'a' if any('▶' in row and 'CANCEL' in row for row in s.tiles) else 'down'
                    elif side.counts['Gen2ToGen2LinkComms']:
                        if 'STATS' in s.text and 'TRADE' in s.text:
                            row = next(r for r in s.tiles if 'STATS' in r and 'TRADE' in r)
                            cursor = max(row.find('▶'), row.find('▷'))
                            button = 'right' if cursor < 10 else 'a'
                        elif 'EXP POINTS' in s.text:
                            button = 'b'
                        elif 'CANCEL' in s.text and 'TRADE' in s.text:
                            button = choose(s.tiles, 'TRADE') or 'a'
                        elif any(mon.nick in s.text for mon in s.party) and 'CANCEL' in s.text:
                            cursor = m.byte('wMenuCursorY') - 1
                            target = min(side.spec.party_slot, len(s.party) - 1)
                            button = 'a' if cursor == target else 'down' if cursor < target else 'up'
                    elif 'TURN OFF' in s.text:
                        button = choose(s.tiles, 'TURN OFF') or 'b'
                    elif 'CHANGE BOX' in s.text or 'Choose a' in s.text or 'STATS' in s.text:
                        button = 'b'
                    elif '┌' in s.tiles[12] or m.byte('wScriptRunning') and name != 'TRADE_CENTER':
                        button = 'a'
                    elif name == 'TRADE_CENTER':
                        occupied = {(x, y) for _, x, y in s.objects}
                        point, face = ((6, 4), 'left') if (3, 4) in occupied else ((3, 4), 'right')
                        path = side.nav.local(s, [point], side.pb.memory)
                        if path:
                            button = path[0]
                        elif m.byte('wPlayerDirection') & 12 != {'left': 8, 'right': 12}[face]:
                            button = face
                        else:
                            button = 'a'
                    else:
                        target = side.data.map_ids['POKECENTER_2F']
                        path = side.nav.toward(s, target, [(5, 3)], side.pb.memory)
                        if path:
                            button = path[0]
                        elif path == []:
                            button = 'up' if m.byte('wPlayerDirection') & 12 != 4 else 'a'
                        else:
                            button = None
                    buttons.append(button)
                    signature = (s.map, s.x, s.y, button, tuple(side.counts.items()))
                    if signature != previous[i] or step % 100 == 0:
                        row = {'step': step, 'side': i, 'map': name, 'x': s.x, 'y': s.y,
                               'button': button, 'counts': dict(side.counts), 'text': s.tiles}
                        log.write(json.dumps(row) + '\n')
                        log.flush()
                        print(step, i, name, s.x, s.y, button, dict(side.counts), flush=True)
                        previous[i] = signature
                    side.pb.screen.image.save(args.output / f'{i}.png')
                if all(side.counts['ExitLinkCommunications'] for side in sides):
                    for _ in range(120):
                        for side in sides:
                            side.tick()
                    for side in sides:
                        side.detach()
                    print('BOTH CARTRIDGES SAVED AND LEFT THE TRADE MENU', flush=True)
                    break
                for side, button in zip(sides, buttons):
                    if button:
                        side.pb.button_press(button)
                for frame in range(40):
                    if frame == 8:
                        for side in sides:
                            side.release_buttons()
                    moved = False
                    for side in sides:
                        moved = side.tick() or moved
                    if not moved:
                        raise RuntimeError('Both cable endpoints are parked')
    finally:
        for i, side in enumerate(sides):
            side.pb.screen.image.save(args.output / f'{i}.png')
            with (args.output / f'{i}.state').open('wb') as output:
                side.pb.save_state(output)
            side.stop()


if __name__ == '__main__':
    main()
