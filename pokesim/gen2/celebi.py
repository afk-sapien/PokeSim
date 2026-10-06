"""Optional GS Ball distribution followed by Crystal's original Celebi quest."""
import hashlib
import io
import json
import time
import uuid

from .. import config
from ..checkpoints import CheckpointStore
from ..runtime.reward_delivery import BARRIER, PENDING, recover_storage
from .ram import Memory, read_snapshot

CLAIM = 'gen2-gs-ball-distribution-v1'


def activate(emu):
    if (emu.data.game != 'crystal' or not getattr(config, 'CELEBI_EVENT', False)
            or emu.store.get(CLAIM) or emu.paused or emu.manual_mode or emu.preparation
            or emu.store.get('trade_hold') or emu.policy.collection.get('tower')):
        return None
    before = read_snapshot(emu.pb.memory, emu.data, emu.frame)
    mem = Memory(emu.pb.memory, emu.data)
    if (not before.hall_of_fame_count or before.in_battle or mem.byte('wScriptRunning')
            or '┌' in before.tiles[12] or emu.policy.menu):
        return None
    if before.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER') or 251 in before.owned:
        emu.store.set(CLAIM, 'already_available')
        return None
    source = emu._autosave()
    metadata = emu.store.checkpoint_metadata(source)
    from .rewards import clone_emulator, write
    clone = clone_emulator(emu)
    try:
        write(clone.memory, emu.data, 'sGSBallFlag', b'\x0b')
        if read_snapshot(clone.memory, emu.data, emu.frame) != before:
            raise ValueError('GS Ball distribution changed unrelated adventure state')
        stream = io.BytesIO()
        clone.save_state(stream)
        raw = stream.getvalue()
    finally:
        clone.stop(save=False)
    identifier = uuid.uuid4().hex
    directory = emu.store.dir / 'custom-rewards' / identifier
    directory.mkdir(parents=True)
    CheckpointStore.atomic_write(directory / 'result.state', raw)
    metadata = {**metadata, 'sha256': hashlib.sha256(raw).hexdigest(), 'reward_id': identifier}
    record = {'id': identifier, 'phase': 'committed', 'decision': 'COMMIT', 'kind': 'gs_ball_event',
              'sha256': metadata['sha256'], 'metadata': metadata, 'trade_id': emu.store.get('trade_barrier')}
    with emu.store.lock, emu.store.db:
        emu.store.db.execute('PRAGMA synchronous=FULL')
        for key, value in ((CLAIM, identifier), (PENDING, record), (BARRIER, identifier)):
            emu.store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, json.dumps(value)))
        emu.store.db.execute('INSERT INTO events(ts,type,title,body,notable,priority,map,playtime) VALUES (?,?,?,?,?,?,?,?)',
            (time.time(), 'milestone', 'Custom GS Ball distribution unlocked',
             'Visit Goldenrod Pokémon Center to begin Crystal’s original Celebi quest.', 1, 4, before.map_name, ''))
    try:
        emu._load_state_file(recover_storage(emu.store))
    except BaseException:
        emu.fatal_error = 'A committed GS Ball event needs recovery. Restart this adventure.'
        raise
    return record


def journey(policy, snapshot, Goal):
    if policy.data.game != 'crystal' or 251 in snapshot.owned:
        return None
    mem = Memory(policy.memory, policy.data)
    if not snapshot.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER'):
        if mem.byte('sGSBallFlag') != 0x0b:
            return None
        y = 6 if snapshot.map == policy.data.map_ids['GOLDENROD_POKECENTER_1F'] and (snapshot.x, snapshot.y) == (3, 7) else 7
        return Goal('celebi_delivery', 'Receive the GS Ball in Goldenrod', 'GOLDENROD_POKECENTER_1F', 3, y)
    if snapshot.event('EVENT_FOREST_IS_RESTLESS'):
        if policy.data.items['GS_BALL'] not in dict(snapshot.items):
            return Goal('celebi_kurt_returns', 'Meet Kurt outside his house', 'AZALEA_TOWN', 9, 6)
        if not snapshot.can_catch:
            goal = policy.storage_goal(snapshot)
            return Goal('collection_box', 'Make room for Celebi', goal.map_name, goal.x, goal.y, goal.face)
        return Goal('legend_celebi', 'Bring the GS Ball to the Ilex Forest shrine', 'ILEX_FOREST', 8, 23, 'up')
    if snapshot.event('EVENT_CAN_GIVE_GS_BALL_TO_KURT'):
        if snapshot.event('EVENT_GAVE_GS_BALL_TO_KURT') and mem.byte('wDailyFlags1') & 1:
            return None
        return policy.person(snapshot, 'celebi_kurt', 'Ask Kurt to examine the GS Ball', 'KURTS_HOUSE', 'Kurt1')
    return None
