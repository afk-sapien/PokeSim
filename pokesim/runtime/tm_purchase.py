"""Commit a Champion shop purchase as one recoverable cartridge checkpoint."""
import hashlib
import io
import time
import uuid
from dataclasses import replace

from pokecore.gen1 import W_WALK_COUNTER

from .. import champion_shop, tm_shop
from ..checkpoints import CheckpointStore, sync_directory
from ..ram import W_BAG_ITEMS, W_CUR_MAP, W_MONEY, W_NUM_BAG_ITEMS, W_X, W_Y, read_snapshot
from ..state import journal, kv
from . import trace
from .reward_delivery import BARRIER, PENDING, recover_storage


def at_counter(policy, memory):
    """Whether a trip to buy the policy's plan has reached the counter. Most steps are during travel, so
    this reads the map and position and decodes nothing else."""
    return (bool(getattr(policy, 'tm_plan', None)) and policy.goal.key == 'buy_tm'
            and (memory[W_CUR_MAP], memory[W_X], memory[W_Y]) == tm_shop.COUNTER)


def sale(policy, memory, frame, offers):
    """The sale the policy's plan makes now, as ``(before, item, quantity, price)``, or None. The player
    stands still at the counter outside battles and menus, the plan is still worth it with the counter's
    ready ``offers`` and the bag does not hold the item yet. The application and the headless run
    (adapter.py) both sell through it."""
    plan = policy.tm_plan
    before = read_snapshot(memory, frame)
    if (not before.valid or not before.started or before.in_battle or before.textbox or before.start_menu
            or memory[W_WALK_COUNTER] or (before.map, before.x, before.y) != tm_shop.COUNTER
            or getattr(getattr(policy, 'heal', None), 'latched', False)
            or not tm_shop.valid_plan(before, plan, policy.tm_moves, policy.tm_compatible, offers)
            or dict(before.items).get(plan['item'])):
        return None
    item = plan['item']
    price = champion_shop.PRICES[item] if plan.get('supply') else tm_shop.PRICES[item]
    return before, item, plan.get('quantity', 1), price


def credit(memory, before, item, quantity, price):
    """Write a sale into ``memory``: the price leaves the purse and the item takes the bag's next entry."""
    digits = f'{before.money - price:06d}'
    memory[W_MONEY:W_MONEY + 3] = bytes(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    offset = W_BAG_ITEMS + len(before.items) * 2
    memory[offset:offset + 3] = bytes((item, quantity, 255))
    memory[W_NUM_BAG_ITEMS] = len(before.items) + 1


def purchase(emu):
    """Buy the policy's selected item only while standing at the Celadon counter."""
    policy = emu.policy
    if not at_counter(policy, emu.pb.memory):
        return None
    preparation = emu.store.get('interaction_preparation') or {}
    if (not getattr(emu, 'isolated_ram', False) or emu.paused or emu.manual_mode
            or getattr(emu, 'preparation', None) or emu.store.get('trade_hold')
            or preparation.get('phase') in {'travelling', 'storage', 'rendezvous', 'ready'}):
        return None
    if getattr(emu, 'step_tracker', None) is not None:
        emu.step_tracker.flush(force=True)
    found = sale(policy, emu.pb.memory, emu.frame, champion_shop.ready(emu.store))
    if found is None:
        return None
    before, item, quantity, price = found
    plan = policy.tm_plan
    target, supply = plan['target'], plan.get('supply', False)
    pending = emu.store.get(PENDING)
    if pending and pending.get('decision') == 'COMMIT' and pending.get('phase') != 'complete':
        raise ValueError('A previous custom transaction still needs recovery')
    expected = replace(before, money=before.money - price, items=before.items + ((item, quantity),))
    emu.snapshot = before
    emu._autosave()
    source = emu.store.latest_state()
    metadata = emu.store.checkpoint_metadata(source)
    if not metadata or metadata.get('frame') != before.frame:
        raise ValueError('Champion purchases require a current verified checkpoint')
    state = emu._state_bytes()
    clone = emu._boot()
    try:
        clone.load_state(io.BytesIO(state))
        credit(clone.memory, before, item, quantity, price)
        if read_snapshot(clone.memory, emu.frame) != expected:
            raise ValueError('The Champion purchase changed unexpected gameplay state')
        output = io.BytesIO()
        clone.save_state(output)
        raw = output.getvalue()
    finally:
        clone.stop(save=False)
    identifier = uuid.uuid4().hex
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    sync_directory(directory.parent)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    record = {'id': identifier, 'phase': 'staged', 'decision': None, 'kind': 'tm_purchase',
              'item': item, 'quantity': quantity, 'price': price, 'recipient': list(plan['signature']),
              'sha256': metadata['sha256'], 'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    emu.store.set(PENDING, record)
    with emu.store.durable() as db:
        from ..activity_ledger import increment
        increment(db, 'bought', item, quantity)
        if supply and item in champion_shop.OFFERS:
            champion_shop.consume(db, item)
        kv.put(db, BARRIER, identifier)
        kv.put(db, PENDING, {**record, 'decision': 'COMMIT', 'phase': 'committed'})
        name = champion_shop.NAMES[item] if supply else tm_shop.label(item, policy.tm_moves)
        if quantity > 1:
            name = f'{quantity} × {name}'
        recipient = before.party[target].nick or before.party[target].name
        title = f'Bought {name}' if supply else f'Bought {name} for {recipient}'
        journal.add(db, time.time(), 'item', title,
                    f'Spent ₽{price:,} at the PokeSim Champion counter in Celadon. '
                    'The purchase entered the bag for use through the normal game menus.',
                    1, 3, before.map_name)
    try:
        path = recover_storage(emu.store)
        with trace.reason(emu, 'gift'):
            emu._load_state_file(path)
        emu.policy.on_restore()
        emu.input_epoch += 1
    except BaseException:
        emu.fatal_error = 'A committed Champion purchase needs recovery. Restart this adventure.'
        emu.stopping = True
        raise
    return {**record, 'phase': 'complete', 'decision': 'COMMIT'}
