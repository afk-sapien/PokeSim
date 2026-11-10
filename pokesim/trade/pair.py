"""Stage and verify a trusted exchange while both game containers are stopped."""
import argparse
import hashlib
import json
from pokecore.emulator_state import validate_runtime
from pathlib import Path
import time

from ..broker import inventory, routine
from ..checkpoints import CheckpointStore
from ..ram import read_snapshot
from ..state import connect, kv, ledgers, schema
from ..state.journal import add as add_entry
from ..web.pokedex import live_status
from . import boxes
from . import preferences
from .execute import TradeError, _boot, perform, evolve_on_arrival


def verified(condition, message):
    """Post-trade checks must survive `python -O`, which strips `assert` outright.

    These run after both states are written and are the last thing standing between a
    corrupted exchange and a staged one, so they raise instead of asserting.
    """
    if not condition:
        raise TradeError(f'Refusing to stage the exchange: {message}')


def write_json(path, data):
    CheckpointStore.atomic_write(path, json.dumps(data, indent=2).encode())


def inspect(rom, state):
    metadata = CheckpointStore(state.parent).checkpoint_metadata(state)
    if metadata is None:
        raise ValueError('A verified checkpoint manifest is required')
    validate_runtime(metadata)
    if metadata.get('policy') != 'strategic':
        raise ValueError('Checkpoint runtime is incompatible with the trade worker')
    pb = _boot(rom, state, metadata['rom_sha1'])
    try:
        snapshot = read_snapshot(pb.memory, metadata['frame'])
        if not snapshot.valid or not snapshot.started or snapshot.in_battle or snapshot.textbox or snapshot.start_menu:
            raise ValueError('Waiting for a stable overworld checkpoint')
        slots = {(box, pos): boxes.read_slot(pb.memory, box, pos)
                 for box, count in enumerate(snapshot.box_counts, 1) for pos in range(1, count + 1)}
        return snapshot, metadata, slots
    finally:
        pb.stop(save=False)


PAIR_ROOT = Path('/pair')
ROM_ROOT = Path('/roms')


def stage(root, transaction):
    source, inventories, before = {}, [], {}
    work = root / 'transactions' / transaction
    work.mkdir(parents=True, exist_ok=True)
    for name in ['red', 'blue']:
        data, rom = PAIR_ROOT / name, ROM_ROOT / f'{name}.gb'
        state = CheckpointStore(data / 'states').latest_state()
        if state is None:
            raise ValueError('No checkpoint available')
        snapshot, metadata, slots = inspect(rom, state)
        project = metadata['policy_state'].get('collection', {}).get('project') or {}
        protected = [project[k] for k in ['species', 'parent'] if project.get(k)]
        policy = json.loads((root / 'policy.json').read_text(encoding='utf-8'))
        protected += policy.get('protected_species', {}).get(name, [])
        payload = live_status(snapshot.to_dict())
        with connect(data / 'pokesim.sqlite') as db:
            payload = preferences.apply(payload, preferences.read(db))
        inv = inventory.normalise(name, '', payload, protected)
        inventories.append(inv)
        before[name] = snapshot, slots
        backup = work / 'before' / name
        backup.mkdir(parents=True, exist_ok=True)
        for path in [state, state.with_suffix('.json')]:
            CheckpointStore.atomic_write(backup / path.name, path.read_bytes())
        schema.copy(data / 'pokesim.sqlite', backup / 'pokesim.sqlite')
        source[name] = {'rom': rom, 'state': backup / state.name}
    deals = routine.proposals(inventories, limit=1, allow_last_copies=policy.get('allow_last_copies', False))
    if not deals:
        write_json(work / 'result.json', {'status': 'no_opportunity'})
        return
    outputs = {}
    for name in source:
        directory = work / 'after' / name
        directory.mkdir(parents=True, exist_ok=True)
        outputs[name] = directory / f'auto-v1-trade-{transaction}.state'
    result = perform(deals[0], source, outputs)
    for index, name in enumerate(['red', 'blue']):
        manifest = outputs[name].with_suffix('.json')
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        metadata['trade_id'] = transaction
        write_json(manifest, metadata)
        after, _, slots = inspect(source[name]['rom'], outputs[name])
        previous, old_slots = before[name]
        sent = deals[0]['give' if index == 0 else 'take']
        selected = (sent['box'], sent['position'])
        verified(previous.party == after.party, f'{name} party changed')
        verified(previous.badges == after.badges and previous.box_counts == after.box_counts,
                 f'{name} badges or box counts changed')
        verified(previous.owned <= after.owned, f'{name} lost Pokédex entries')
        verified(all(slots[key] == value for key, value in old_slots.items() if key != selected),
                 f'{name} changed a box slot that was not traded')
        moved = result['moved'][index]
        verified(slots[selected].species == moved['received']['species'],
                 f'{name} received a different species than the deal recorded')
        other = deals[0]['take' if index == 0 else 'give']
        incoming = before[other['instance']][1][(other['box'], other['position'])]
        expected, _ = evolve_on_arrival(incoming)
        verified((slots[selected].struct, slots[selected].nickname, slots[selected].ot_name)
                 == (expected.struct, expected.nickname, expected.ot_name),
                 f'{name} received a Pokémon that does not match the agreed one')
        moved['owned_before'], moved['owned_after'] = len(previous.owned), len(after.owned)
    result.update(status='staged', id=transaction, proposal=deals[0])
    result['hashes'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in outputs.items()}
    write_json(work / 'result.json', result)


def journal(root, transaction):
    result = json.loads((root / 'transactions' / transaction / 'result.json').read_text(encoding='utf-8'))
    for moved in result['moved']:
        name = moved['instance']
        data = PAIR_ROOT / name
        key = f'trade:{transaction}'
        title = f"Traded {moved['sent']['nick']} for {moved['received']['nick']}"
        body = f"Received {moved['received']['name']} at level {moved['received']['level']}. {result['reason']}. Exchange {transaction}."
        if moved['received']['evolved_from']:
            body += ' The incoming partner evolved during the exchange.'
        # The journal row and idempotency marker commit together.
        with connect(data / 'pokesim.sqlite') as db:
            from ..activity_ledger import initialize as initialize_activity
            from ..trade_statistics import initialize as initialize_trades, record
            initialize_activity(db)
            initialize_trades(db)
            fresh = ledgers.complete_pair_trade(db, key)
            record(db, 'legacy:' + transaction, moved['sent'].get('species'), moved['received'].get('species'))
            if fresh:
                for side in result.get('proposal', {}).values():
                    if isinstance(side, dict) and side.get('instance') == name and side.get('trade_key'):
                        kv.delete(db, preferences.PREFIX + side['trade_key'])
                kv.put(db, 'trade_barrier', transaction)
                add_entry(db, int(time.time()), 'trade', title, body, 1, 4, 'Trade exchange')
                from ..progress_events import journal
                from ..strategy_data import SPECIES
                received = SPECIES.get(moved['received'].get('species'), {}).get('dex')
                journal(db, 'trade', species=received)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'journal'])
    parser.add_argument('transaction')
    parser.add_argument('--root', type=Path, default=Path('/trading'))
    args = parser.parse_args()
    if not args.transaction.isdigit():
        raise ValueError('Invalid transaction id')
    (stage if args.action == 'stage' else journal)(args.root, args.transaction)


if __name__ == '__main__':
    main()
