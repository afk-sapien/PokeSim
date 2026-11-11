"""Score a save's PC with pcvalue and list what it would release, without changing anything.

    uv run python tools/pc_dry_run.py FOLDER [--show 25] [--rom-dir DIR]

FOLDER holds a copied adventure: ``start.state`` with its ``start.json``, and the adventure's
``pokesim.sqlite`` for Keep locks, linked adventures and the League reward ledger. The ledger seed is
used to find reward copies and is never printed.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pokesim import pcvalue  # noqa: E402
from pokesim.scenarios import Scenario, open_run  # noqa: E402
from pokesim.store import Store  # noqa: E402


def gen2_rows(run, store):
    from pokecore.gen2.breeding import breeding_stock
    from pokesim.gen2 import release
    from pokecore.gen2.ram import Memory
    from pokesim.trade.partners import owners
    snap = run.read()
    policy = run.policy
    player = Memory(run.pb.memory, run.data).word('wPlayerID')
    stock = set(breeding_stock(run.data, [mon.species for mon in snap.party + snap.stored if not mon.egg]))
    names = {sid: data['name'] for sid, data in run.data.species.items()}
    preferences = store.trade_preferences()
    rows = release.entries(snap, names, preferences, release.plan_partners(policy.collection), stock,
                           owners(player, store.trade_partners()), store.league_marks(2))
    today = release.spares(snap, policy.demand, stock, preferences, release.plan_partners(policy.collection),
                           owners=owners(player, store.trade_partners()))
    old = [f'{names.get(mon.species, "?")} Lv {mon.level} box {mon.box + 1}' for mon in today]
    return snap, rows, pcvalue.Inputs(demand=dict(policy.demand), rarity=release.rarity(run.data)), old


def gen1_rows(run, store):
    from pokesim.policies import team
    from pokesim.policies.storage import StorageController
    from pokesim.ram import read_snapshot
    from pokesim.strategy_data import SPECIES
    snap = read_snapshot(run.pb.memory, run.frame)
    collection = run.policy.collection
    project = collection.project or {}
    # A Gen 1 project names species, not a specific Pokémon, so it only adds stock.
    stock = set(project.get('family', [project['parent']])) if project.get('parent') else set()
    if project.get('method') == 'trade':
        stock.add(project['give'])
    preferences = store.trade_preferences()
    partners = frozenset(store.trade_partners())
    rows = team.entries(snap, preferences, (), stock, partners, collection.gift_species(), store.league_marks(1))
    # Today's rule names one target at a time, so ask again with each answer set aside.
    old, avoid = [], set()
    while len(old) < 200:
        slot = StorageController.release_target(snap, project, preferences, collection, avoid, partners)
        if not slot:
            break
        avoid.add(tuple(slot))
        mon = next(mon for mon in snap.storage_entries() if (mon['box'], mon['position']) == tuple(slot))
        old.append(f'{SPECIES[mon["species"]]["name"].title()} Lv {mon["level"]} box {mon["box"] + 1}')
    from pokesim.investment import dex_rarity
    return snap, rows, pcvalue.Inputs(demand=dict(collection.demand()), rarity=dex_rarity), old


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--show', type=int, default=25)
    parser.add_argument('--rom-dir', type=Path, default=Path.home() / 'roms' / 'pokemon')
    args = parser.parse_args()
    folder = args.folder
    scenario = Scenario(folder=folder, name=folder.name, checkpoint=folder / 'start.state')
    run, _ = open_run(scenario, sorted(args.rom_dir.glob('*.gb*')))
    # The folder is a copy, so opening it as a data dir, which adds its working folders, is harmless.
    store = Store(folder)
    generation = run.generation
    snap, rows, inputs, old = (gen2_rows if generation == 2 else gen1_rows)(run, store)
    rated = pcvalue.rate(rows, inputs)
    line = pcvalue.queue(rated)
    free = sum(20 - count for count in snap.box_counts)
    print(f'# {folder.name}: Gen {generation}, {sum(snap.box_counts)} stored, {free} free slots')
    print('status', dict(Counter(row.status for row in rated)), 'origin', dict(Counter(row.entry.origin for row in rated)))
    print('deadlocked' if pcvalue.deadlocked(rated) else f'{len(line)} may go')
    print('queue: Lv 50 and up', sum(row.entry.level >= 50 for row in line),
          'trained Lv 100', sum(row.entry.level == 100 for row in line),
          'shiny', sum(any(label == 'Shiny' for label, _ in row.parts) for row in line),
          'origin', dict(Counter(row.entry.origin for row in line)))
    for index, row in enumerate(line[:args.show], 1):
        box, position = row.entry.slot
        print(f'{index:3}. {row.entry.name} Lv {row.entry.level} box {box + 1} slot {position + 1} '
              f'({row.entry.origin}, {row.status}): {row.describe()}')
    print(f'today: {len(old)} release candidates', '; '.join(old[:10]))


if __name__ == '__main__':
    main()
