"""Commit a Champion shop purchase as one recoverable cartridge checkpoint."""
import hashlib
import io
import time
import uuid
from dataclasses import replace

from .. import tm_shop
from ..checkpoints import CheckpointStore, sync_directory
from ..ram import W_BAG_ITEMS, W_CUR_MAP, W_MONEY, W_NUM_BAG_ITEMS, W_X, W_Y, read_snapshot
from .reward_delivery import BARRIER, PENDING, _put, recover_storage


def purchase(emu):
    """Buy the policy's selected TM only while standing at the Celadon counter."""
    policy = emu.policy
    plan = getattr(policy, 'tm_plan', None)
    # Most calls are during travel. Avoid decoding all storage until arrival.
    mem = emu.pb.memory
    if policy.goal.key != 'buy_tm' or (mem[W_CUR_MAP], mem[W_X], mem[W_Y]) != tm_shop.COUNTER:
        return None
    preparation = emu.store.get('interaction_preparation') or {}
    if (not plan or not getattr(emu, 'isolated_ram', False) or emu.paused or emu.manual_mode
            or getattr(emu, 'preparation', None) or emu.store.get('trade_hold')
            or preparation.get('phase') in {'travelling', 'storage', 'rendezvous', 'ready'}):
        return None
    before = read_snapshot(emu.pb.memory, emu.frame)
    if (not before.valid or not before.started or before.in_battle or before.textbox or before.start_menu
            or emu.pb.memory[0xcfc5] or (before.map, before.x, before.y) != tm_shop.COUNTER
            or policy.goal.key != 'buy_tm' or getattr(policy, 'heal_latch', False)
            or not tm_shop.valid_plan(before, plan, policy.tm_moves, policy.tm_compatible)):
        return None
    item, target = plan['item'], plan['target']
    if dict(before.items).get(item):
        return None
    pending = emu.store.get(PENDING)
    if pending and pending.get('decision') == 'COMMIT' and pending.get('phase') != 'complete':
        raise ValueError('A previous custom transaction still needs recovery')
    price = tm_shop.PRICES[item]
    expected = replace(before, money=before.money - price, items=before.items + ((item, 1),))
    emu.snapshot = before
    emu._autosave()
    source = emu.store.latest_state()
    metadata = emu.store.checkpoint_metadata(source)
    if not metadata or metadata.get('frame') != before.frame:
        raise ValueError('TM purchases require a current verified checkpoint')
    state = emu._state_bytes()
    clone = emu._boot()
    try:
        clone.load_state(io.BytesIO(state))
        digits = f'{expected.money:06d}'
        clone.memory[W_MONEY:W_MONEY + 3] = bytes(int(digits[i:i + 2], 16) for i in (0, 2, 4))
        offset = W_BAG_ITEMS + len(before.items) * 2
        clone.memory[offset:offset + 3] = bytes((item, 1, 255))
        clone.memory[W_NUM_BAG_ITEMS] = len(expected.items)
        if read_snapshot(clone.memory, emu.frame) != expected:
            raise ValueError('The TM purchase changed unexpected gameplay state')
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
              'item': item, 'price': price, 'recipient': list(plan['signature']),
              'sha256': metadata['sha256'], 'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    emu.store.set(PENDING, record)
    with emu.store.lock, emu.store.db:
        emu.store.db.execute('PRAGMA synchronous=FULL')
        from ..activity_ledger import increment
        increment(emu.store.db, 'bought', item)
        _put(emu.store.db, BARRIER, identifier)
        _put(emu.store.db, PENDING, {**record, 'decision': 'COMMIT', 'phase': 'committed'})
        name = tm_shop.label(item, policy.tm_moves)
        recipient = before.party[target].nick or before.party[target].name
        emu.store.db.execute('''INSERT INTO events(ts,type,title,body,notable,priority,map,playtime)
            VALUES (?,?,?,?,?,?,?,?)''', (time.time(), 'item', f'Bought {name} for {recipient}',
            f'Spent ₽{price:,} at the PokeSim Champion TM counter in Celadon. '
            'One TM entered the bag for teaching through the normal game menus.',
            1, 3, before.map_name, ''))
    try:
        path = recover_storage(emu.store)
        emu._load_state_file(path)
        emu.policy.on_restore()
        emu.input_epoch += 1
    except BaseException:
        emu.fatal_error = 'A committed TM purchase needs recovery. Restart this adventure.'
        emu.stopping = True
        raise
    return {**record, 'phase': 'complete', 'decision': 'COMMIT'}
