"""Exercise a failed Mewtwo encounter on a copied approach checkpoint at maximum speed."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokesim import config
from pokesim.emulator import Emulator
from pokesim.policies.base import PolicyContext
from pokesim.ram import W_BAG_ITEMS, W_NUM_BAG_ITEMS, read_snapshot
from pokesim.screen import Screen
from pokesim.store import Store
from pokesim.strategy_data import ITEMS, event_set, object_hidden


def run(rom, checkpoint, failure, frames, revisit=False):
    config.ROM_PATH = rom
    config.SPEED = 0
    config.SEED = 42
    checksum = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='pokesim-legendary-') as directory:
        store = Store(Path(directory))
        emu = Emulator(store)
        emu._load_state_file(checkpoint)
        start = emu.frame
        failure_injected = False
        failed_encounter = None
        restored = None
        restart = None
        guided_return = False
        trace = []
        initial = emu.snapshot
        assert initial.map == 227 and 150 not in initial.owned
        try:
            while emu.frame - start < frames:
                s = read_snapshot(emu.pb.memory, emu.frame)
                scr = Screen(emu.pb.memory)
                if not failure_injected and s.in_battle == 1 and s.enemy_species == 131:
                    if failure == 'no_balls':
                        remaining = [(item, qty) for item, qty in s.items if item not in
                                     {ITEMS[n] for n in ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL', 'MASTER_BALL')}]
                        emu.pb.memory[W_NUM_BAG_ITEMS] = len(remaining)
                        values = [value for pair in remaining for value in pair] + [255]
                        for offset, value in enumerate(values):
                            emu.pb.memory[W_BAG_ITEMS + offset] = value
                    failure_injected = True
                    trace.append({'frame': emu.frame - start, 'action': 'simulate_' + failure})
                    s = read_snapshot(emu.pb.memory, emu.frame)
                if failed_encounter is None and not s.in_battle and event_set(s.event_flags, 'EVENT_BEAT_MEWTWO'):
                    assert 150 not in s.owned
                    failed_encounter = {'frame': emu.frame - start, 'hidden': object_hidden(s, 227, 0),
                                        'items': list(s.items), 'hp': [p.hp for p in s.party]}
                    trace.append({'frame': emu.frame - start, 'action': 'encounter_failed'})
                if failed_encounter and restart is None and emu.legendary_recovery.pending:
                    emu._autosave()
                    saved = emu.legendary_recovery.state_dict()
                    before = emu.frame
                    emu.pb.stop(save=False)
                    emu = Emulator(store)
                    emu._load_state_file(store.latest_state())
                    assert emu.frame == before and emu.legendary_recovery.state_dict() == saved
                    restart = {'frame': emu.frame - start, 'state': saved}
                    trace.append({'frame': emu.frame - start, 'action': 'restart_same_checkpoint'})
                    continue
                if failed_encounter and restored is None and not event_set(s.event_flags, 'EVENT_BEAT_MEWTWO'):
                    assert not object_hidden(s, 227, 0) and s.map != 227
                    restored = {'frame': emu.frame - start, 'map': s.map_name, 'items': list(s.items)}
                    trace.append({'frame': emu.frame - start, 'action': 'encounter_restored'})
                collection = emu.policy.collection
                if (revisit and restored and not guided_return and not s.in_battle
                        and collection.attempts.get('legendary:131:227', 0) <= collection.elapsed):
                    # Isolate the restored encounter after the real retry wait. Shopping,
                    # storage, navigation, and the second battle still use the normal policy.
                    collection.project = {'method': 'static', 'species': 131, 'map': 227,
                        'fragment': 'MEWTWO', 'flag': 'EVENT_BEAT_MEWTWO', 'key': 'legendary:131:227',
                        'legendary': True}
                    collection.remaining = 180000
                    collection.idle_frames = 0
                    collection.project_maps = []
                    collection.progress_token = None
                    guided_return = True
                    trace.append({'frame': emu.frame - start, 'action': 'select_restored_mewtwo_for_validation'})
                if 150 in s.owned:
                    trace.append({'frame': emu.frame - start, 'action': 'mewtwo_caught'})
                    break
                if failure == 'knockout' and failed_encounter is None and s.in_battle == 1 and s.enemy_species == 131 and scr.kind(s) in ('battle', 'moves'):
                    # Deliberately override capture controls for the first copied fight only.
                    actions = emu.policy._root(scr, 'fight') if scr.kind(s) == 'battle' else emu.policy._select(scr, 3)
                else:
                    actions = emu.policy.step(PolicyContext(s, 0, 0, emu.pb.memory))
                for action in actions:
                    if action.button:
                        emu.pb.button_press(action.button)
                    if action.hold:
                        emu.pb.tick(action.hold, render=False)
                    if action.button:
                        emu.pb.button_release(action.button)
                    if action.gap:
                        emu.pb.tick(action.gap, render=False)
                    emu.frame += action.hold + action.gap
                    emu._observe()
                if len(trace) == 0 or emu.frame - trace[-1]['frame'] - start >= 12000:
                    trace.append({'frame': emu.frame - start, 'map': s.map_name,
                                  'goal': emu.policy.goal.title, 'mode': emu.policy.mode})
                    print(json.dumps(trace[-1]), flush=True)
            final = read_snapshot(emu.pb.memory, emu.frame)
            assert failed_encounter and restored and restart
            if revisit:
                assert 150 in final.owned, 'The restored encounter was not caught within the replay budget'
            assert emu.reloads == 0
            assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == checksum
            return {'scenario': failure, 'frames': emu.frame - start, 'wall_seconds': round(time.monotonic() - started, 2),
                    'source_sha256': checksum, 'source_unchanged': True, 'rewinds': emu.reloads,
                    'guided_return': guided_return,
                    'failed_encounter': failed_encounter, 'restored_encounter': restored, 'restart': restart,
                    'caught': 150 in final.owned, 'final_owned': len(final.owned), 'final_map': final.map_name,
                    'recovery': emu.legendary_recovery.state_dict(),
                    'events': [{'type': e['type'], 'title': e['title']} for e in store.events(limit=100)], 'trace': trace}
        finally:
            emu.pb.stop(save=False)
            store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--failure', choices=('knockout', 'no_balls'), required=True)
    parser.add_argument('--frames', type=int, default=360000)
    parser.add_argument('--revisit', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.frames <= 0 or args.output.resolve() in (args.rom.resolve(), args.checkpoint.resolve(), args.checkpoint.with_suffix('.json').resolve()):
        parser.error('Use a positive frame budget and a separate output file')
    result = run(args.rom, args.checkpoint, args.failure, args.frames, args.revisit)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('scenario', 'frames', 'rewinds', 'caught', 'final_map')}))
