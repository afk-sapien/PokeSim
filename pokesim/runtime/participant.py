"""Adventure-owned durable cable preparation, staging and publication."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import time

from fastapi import HTTPException, Request

from ..checkpoints import CheckpointStore
from ..app.registry import digest, validate_id

PREFIX = 'managed_interaction:'


def _records(store):
    """Every unfinished interaction. A released one is inert to both callers.

    Each record keeps the whole policy snapshot it was staged from, so an adventure
    that has traded for days holds hundreds of megabytes of finished exchanges here.
    Parsing those on every startup is what the released filter avoids.
    """
    with store.lock:
        rows = store.db.execute("SELECT v FROM kv WHERE k LIKE ? AND "
                                "COALESCE(json_extract(v, '$.phase'), '') <> 'released'",
                                (PREFIX + '%',)).fetchall()
    return [json.loads(row[0]) for row in rows]


def _record(store, tid):
    validate_id(tid)
    value = store.get(PREFIX + tid)
    if value is None:
        raise ValueError('This adventure has no record of that interaction')
    return value


def _save(store, record):
    store.set(PREFIX + record['id'], record)
    return record


def _artifact(path, expected):
    path = Path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Interaction artifact checksum failed')
    return raw


def _promote(store, record):
    if record.get('decision') != 'COMMIT':
        raise ValueError('The interaction has no durable commit receipt')
    stage = record['staged']
    state = _artifact(stage['state_path'], stage['checkpoint_sha256'])
    metadata = {**record['source_metadata'], 'sha256': stage['checkpoint_sha256'], 'trade_id': record['id']}
    path = store.states / f"auto-v1-link-{record['id']}.state"
    if not path.exists():
        CheckpointStore.atomic_write(path, state)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != stage['checkpoint_sha256']:
        raise ValueError('The committed checkpoint is damaged')
    CheckpointStore.atomic_write(path.with_suffix('.json'), json.dumps(metadata).encode())
    with store.lock, store.db:
        from ..league_partners import merge
        merge(store.db, record.get('incoming_league_record'))
        store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', ('trade_barrier', json.dumps(record['id'])))
        hold = {'id': record['id'], 'source': record['source_name'], 'phase': 'prepared'}
        store.db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', ('trade_hold', json.dumps(hold)))
        marker = 'managed_journal:' + record['id']
        if not store.db.execute('SELECT 1 FROM kv WHERE k=?', (marker,)).fetchone():
            from ..interactions.centers import CENTERS
            location = CENTERS.get(record.get('source_center_map'), {}).get('name', 'Pokémon Center')
            title, body, detail = _trade_story(record)
            store.db.execute('''INSERT INTO events(ts,type,title,body,notable,priority,map,playtime,detail)
                VALUES (?,?,?,?,?,?,?,?,?)''', (time.time(), 'trade', title, body, 1, 4, location, '',
                json.dumps(detail) if detail else None))
            store.db.execute('INSERT INTO kv VALUES (?, ?)', (marker, 'true'))
    return path



def _traded_mon(side):
    """Name, species and level from one side of a swap, or None when the record predates this."""
    if not isinstance(side, dict) or not side.get('struct'):
        return None
    from ..ram import SPECIES_NAMES, decode_text
    from ..trade import boxes
    try:
        struct = bytes.fromhex(side['struct'])
        nickname = decode_text(bytes.fromhex(side['nickname'])) if side.get('nickname') else ''
    except ValueError:
        return None
    if len(struct) < boxes.BOX_STRUCT:
        return None
    species = struct[boxes.SPECIES]
    name = SPECIES_NAMES.get(species, f'species {species}')
    trainer = ''
    if side.get('ot_name'):
        try:
            trainer = decode_text(bytes.fromhex(side['ot_name']))
        except ValueError:
            trainer = ''
    return {'species': species, 'name': name.title(), 'nick': nickname or name.title(),
            'level': struct[boxes.LEVEL], 'trainer': trainer}


def _trade_story(record):
    """A journal entry that says what crossed the cable, falling back to the old wording."""
    generic = ('Cable Club trade completed',
               'Both cartridges completed their exchange and saved the result.', None)
    sent, got = _traded_mon(record.get('outgoing')), _traded_mon(record.get('incoming'))
    if not sent or not got:
        return generic
    from ..strategy_data import SPECIES
    # The checkpoint manifest carries no trainer name, so the names come from the Pokemon: the
    # original trainer of the one that arrived is the adventure on the other end of the cable.
    peer = got.get('trainer') or ''
    title = f"Traded {sent['nick']} for {got['nick']}"
    origin = f", first trained by {peer}" if peer else ''
    body = (f"{sent['nick']} the {sent['name']} at level {sent['level']} went down the cable, and "
            f"{got['nick']} the {got['name']} at level {got['level']} came back{origin}.")
    detail = {'kind': 'trade', 'peer': peer,
              'sent': {**sent, 'dex': SPECIES.get(sent['species'], {}).get('dex')},
              'received': {**got, 'dex': SPECIES.get(got['species'], {}).get('dex')}}
    return title, body, detail


COMPACT_PER_START = 100


def _compact_released(store):
    """Discard staged snapshots that adventures traded before release stripped them.

    SQLite rewrites the rows itself, so a backlog of finished exchanges never has to
    be parsed. The batch is capped because each row carries a whole policy snapshot.
    """
    with store.lock, store.db:
        store.db.execute(
            "UPDATE kv SET v = json_remove(v, '$.source_metadata') WHERE k IN ("
            "  SELECT k FROM kv WHERE k LIKE ?"
            "   AND json_extract(v, '$.phase') = 'released'"
            "   AND json_extract(v, '$.source_metadata') IS NOT NULL"
            "   LIMIT ?)", (PREFIX + '%', COMPACT_PER_START))


def recover_storage(store):
    """Reconcile committed files before the emulator chooses its startup checkpoint."""
    with store.lock:
        store.db.execute('PRAGMA synchronous=FULL')
    _compact_released(store)
    for record in _records(store):
        if record.get('decision') == 'COMMIT' and record['phase'] != 'released':
            _promote(store, record)
        elif record.get('decision') == 'ABORT':
            hold = store.get('trade_hold')
            if hold and hold['id'] == record['id']:
                store.set('trade_hold', None)
            preparation = store.get('interaction_preparation')
            if preparation and preparation['id'] == record['id']:
                store.set('interaction_preparation', None)
            record['phase'] = 'aborted'
            _save(store, record)
        elif record['phase'] not in {'aborted', 'released'} and not store.get('trade_hold'):
            store.set('trade_hold', {'id': record['id'], 'source': record.get('source_name'), 'phase': 'recovering'})


class Participant:
    def __init__(self, runtime, bootstrap):
        self.runtime = runtime
        self.store = runtime.store
        self.emu = runtime.emulator
        self.bootstrap = bootstrap
        self.root = self.store.dir / 'interactions'
        self.root.mkdir(exist_ok=True)

    def inventory(self):
        from ..web.pokedex import live_status
        from ..trade.preferences import apply
        from ..broker.inventory import normalise
        from ..broker.routine import offers
        from ..policies.collection import LEAGUE
        status = self.emu.status()
        payload = apply(live_status(status.get('game'), (status.get('strategy') or {}).get('collection')),
                        self.store.trade_preferences())
        from ..league_partners import apply as league_partners
        payload = league_partners(payload, self.store)
        inv = normalise(self.bootstrap.adventure_id, '', payload)
        # Only the owning runtime imports game-specific data to derive offers.
        candidates = []
        available = (status.get('game') or {}).get('map') not in LEAGUE
        for mon in offers(inv, True) if available else ():
            from ..broker.routine import EVOLVES
            from ..strategy_data import SPECIES
            candidates.append({**mon.as_side(), 'last_copy': inv.held[mon.species] == 1,
                               'arrived_dex': SPECIES[EVOLVES.get(mon.species, mon.species)]['dex']})
        return {**payload, 'adventure_id': self.bootstrap.adventure_id,
                'generation': self.bootstrap.generation, 'offers': candidates,
                'revision': digest(payload), 'holding': bool(self.store.get('trade_hold'))}

    def collection_demand(self, data):
        requests = data.get('requests', {})
        if not isinstance(requests, dict) or len(requests) > 151:
            raise ValueError('Collection requests must map Pokédex entries to demand counts')
        cleaned = {}
        for key, count in requests.items():
            if not str(key).isdigit() or not 1 <= int(key) <= 151 or type(count) is not int or not 1 <= count <= 10000:
                raise ValueError('Invalid collection request')
            cleaned[int(key)] = count
        collection = getattr(self.emu.policy, 'collection', None)
        if collection is not None:
            collection.set_demand(cleaned)
        return {'requests': cleaned}

    def prepare(self, data):
        tid = validate_id(data['id'])
        plan_digest = data['plan_digest']
        selected = data['selected_key']
        record = self.store.get(PREFIX + tid)
        if record:
            if record['plan_digest'] != plan_digest or record['selected_key'] != selected:
                raise ValueError('Interaction parameters changed')
            if record['phase'] != 'preparing':
                return record
        else:
            if selected not in {row.get('trade_key') for row in self.inventory()['offers']}:
                raise ValueError('The selected Pokémon is not an eligible boxed offer')
            if any(row['phase'] not in {'aborted', 'released'} for row in _records(self.store)):
                raise ValueError('Another interaction already reserves this adventure')
            record = _save(self.store, {'id': tid, 'phase': 'preparing', 'decision': None,
                'plan_digest': plan_digest, 'selected_key': selected,
                'was_paused': self.emu.paused, 'was_manual': self.emu.manual_mode})
        from .preparation import begin
        prepared = begin(self.emu, selected, tid)
        if prepared.get('phase') == 'failed':
            raise ValueError(prepared.get('error', 'Trade preparation failed'))
        if prepared.get('phase') != 'ready':
            return {**record, 'preparation': prepared}
        hold = self.store.get('trade_hold')
        if not hold or hold['id'] != tid or not hold.get('source'):
            raise ValueError('The prepared source checkpoint is missing')
        source = self.store.state_path(hold['source'])
        metadata = self.store.checkpoint_metadata(source)
        raw = source.read_bytes()
        directory = self.root / tid
        directory.mkdir(exist_ok=True)
        path = directory / 'source.state'
        CheckpointStore.atomic_write(path, raw)
        from ..interactions.cable_metadata import BUILDS
        from ..interactions.verification import party
        from ..trade.preferences import identity
        from ..ram import individual_data
        build = BUILDS[self.emu.rom_sha1]
        symbols = build['symbols']
        rows = party(self.emu.pb, symbols)
        slot = prepared['party_slot']
        row = rows[slot]
        if identity(individual_data(row['struct'])) != selected:
            raise ValueError('Prepared party member does not match the selected individual')
        from ..interactions.centers import safe_center
        from ..ram import read_snapshot
        snapshot = read_snapshot(self.emu.pb.memory, self.emu.frame)
        if not safe_center(snapshot, snapshot.map, self.emu.pb.memory):
            raise ValueError('Prepared adventure is not in a supported Center')
        record.update(phase='prepared', source_name=source.name, source_metadata=metadata,
                      source_center_map=snapshot.map,
                      source={'adventure_id': self.bootstrap.adventure_id,
                              'rom_path': self.runtime.settings.rom_path,
                              'checkpoint_path': str(path), 'cartridge_save_path': None,
                              'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                              'party_slot': slot, 'selected_key': selected},
                      outgoing={key: value.hex() for key, value in row.items()})
        from ..league_partners import export
        record['outgoing_league_record'] = export(self.store, selected)
        return _save(self.store, record)

    def stage(self, data):
        record = _record(self.store, data['id'])
        if record.get('decision'):
            if record.get('attempt_id') != data['attempt_id']:
                raise ValueError('Stale session attempt')
            return record
        if record['phase'] == 'staged':
            if record['attempt_id'] != data['attempt_id'] or record['staged']['checkpoint_sha256'] != data['result']['checkpoint_sha256']:
                raise ValueError('A different session result is already staged')
            return record
        if record['phase'] != 'prepared' or record['plan_digest'] != data['plan_digest']:
            raise ValueError('Adventure is not prepared for this plan')
        result = data['result']
        if (result['adventure_id'] != self.bootstrap.adventure_id
                or result['source']['checkpoint_sha256'] != record['source']['checkpoint_sha256']
                or result['selected_key'] != record['selected_key']):
            raise ValueError('Cable result does not match the held adventure')
        hold = self.store.get('trade_hold')
        if not hold or hold['id'] != record['id']:
            raise ValueError('Adventure reservation was lost')
        application = self.store.dir.parent.parent
        expected_root = (application / 'interactions' / record['id'] / 'attempts' / data['attempt_id'] / 'outputs').resolve()
        for name in ('state_path', 'cartridge_save_path'):
            path = Path(result[name]).resolve()
            if path.parent != expected_root:
                raise ValueError('Cable result is outside its transaction workspace')
        raw = _artifact(result['state_path'], result['checkpoint_sha256'])
        save = _artifact(result['cartridge_save_path'], result['cartridge_sha256'])
        self.verify_result(record, result, raw, save, data['incoming'])
        from ..league_partners import validate
        from ..trade.preferences import identity
        from ..ram import individual_data
        incoming_key = identity(individual_data(bytes.fromhex(data['incoming']['struct'])))
        record['incoming_league_record'] = validate(data.get('incoming_league_record'), incoming_key)
        directory = self.root / record['id']
        target, cartridge = directory / 'staged.state', directory / 'staged.sav'
        CheckpointStore.atomic_write(target, raw)
        CheckpointStore.atomic_write(cartridge, save)
        record.update(phase='staged', attempt_id=data['attempt_id'], staged={**result,
                      'state_path': str(target), 'cartridge_save_path': str(cartridge)},
                      incoming=dict(data['incoming']))
        return _save(self.store, record)

    def verify_result(self, record, result, state, save, incoming):
        from types import SimpleNamespace
        from pyboy import PyBoy
        from ..interactions.cable_metadata import BUILDS
        from ..interactions.verification import party, boxed_inventory, verify_exchange, verify_restarts
        symbols = BUILDS[self.emu.rom_sha1]['symbols']
        rom = Path(self.runtime.settings.rom_path).read_bytes()
        pb = PyBoy(io.BytesIO(rom), ram_file=io.BytesIO(bytes(32768)), window='null', sound_emulated=False, log_level='ERROR')
        pb.set_emulation_speed(0)
        try:
            pb.load_state(io.BytesIO(_artifact(record['source']['checkpoint_path'], record['source']['checkpoint_sha256'])))
            before, boxes = party(pb, symbols), boxed_inventory(pb, symbols)
            from ..ram import read_snapshot
            from ..interactions.centers import safe_center
            source = read_snapshot(pb.memory, 0)
            if not safe_center(source, source.map, pb.memory):
                raise ValueError('Prepared checkpoint is not in a supported Center')
            if record.get('source_center_map', source.map) != source.map:
                raise ValueError('Prepared checkpoint Center does not match its reservation')
            pb.load_state(io.BytesIO(state))
            side = SimpleNamespace(pb=pb, sym=symbols, frame=0, attached=False, rom_bytes=rom,
                source_center_map=source.map,
                counts=result['evidence']['transport'], get=lambda name: pb.memory[symbols[name][1]])
            expected, _ = verify_exchange(side, before,
                {key: bytes.fromhex(value) for key, value in incoming.items()}, record['source']['party_slot'], boxes)
            verify_restarts(side, state, save, expected)
        finally:
            pb.stop(save=False)

    def apply(self, data):
        record = _record(self.store, data['id'])
        if record.get('decision') == 'ABORT':
            raise ValueError('This interaction was aborted')
        if record.get('attempt_id') != data['attempt_id'] or record.get('staged', {}).get('checkpoint_sha256') != data['checkpoint_sha256']:
            raise ValueError('Commit does not match the staged result')
        if record['plan_digest'] != data['plan_digest']:
            raise ValueError('Commit does not match the plan')
        if record['phase'] == 'released':
            return record
        record.update(decision='COMMIT', phase='committed')
        _save(self.store, record)
        path = _promote(self.store, record)
        self.emu._load_state_file(path)
        self.emu.paused = True
        self.store.set('trade_hold', {'id': record['id'], 'source': record['source_name'], 'phase': 'loaded'})
        record['phase'] = 'applied'
        return _save(self.store, record)

    def release(self, data):
        record = _record(self.store, data['id'])
        if record['phase'] == 'released':
            return record
        if record['phase'] != 'applied' or record['decision'] != 'COMMIT':
            raise ValueError('Both committed results must be applied before release')
        self.store.set('interaction_preparation', None)
        self.store.set('trade_hold', None)
        record['phase'] = 'released'
        # Only an unreleased commit is ever promoted from this snapshot, and it dwarfs
        # the rest of the record, so a released exchange has no reason to carry it.
        record.pop('source_metadata', None)
        _save(self.store, record)
        self.emu.paused = False
        self.emu.policy.on_restore()
        self.emu.stuck_since = time.time()
        return record

    def abort(self, data):
        tid = validate_id(data['id'])
        record = self.store.get(PREFIX + tid)
        if record is None:
            return _save(self.store, {'id': tid, 'phase': 'aborted', 'decision': 'ABORT',
                                     'plan_digest': None, 'selected_key': None})
        if record.get('decision') == 'COMMIT':
            raise ValueError('A committed interaction cannot abort')
        if record['phase'] == 'aborted':
            return record
        record.update(decision='ABORT', phase='aborting')
        _save(self.store, record)
        from .preparation import cancel
        hold = self.store.get('trade_hold')
        if hold and hold['id'] == tid:
            if record.get('source_name'):
                self.emu._load_state_file(self.store.state_path(record['source_name']))
            self.store.set('trade_hold', None)
        preparation = self.store.get('interaction_preparation')
        if preparation and preparation.get('id') == tid:
            cancel(self.emu, tid)
            self.store.set('interaction_preparation', None)
        self.emu.preparation = None
        self.emu.paused = record.get('was_paused', False)
        self.emu.manual_mode = record.get('was_manual', False)
        self.emu.policy.on_restore()
        record['phase'] = 'aborted'
        return _save(self.store, record)


def install(app, runtime):
    participant = Participant(runtime, app.state.bootstrap)
    app.state.participant = participant

    @app.get('/internal/participant/inventory')
    def inventory():
        return runtime.call(participant.inventory)

    @app.get('/internal/participant/status/{tid}')
    def status(tid: str):
        try:
            return _record(runtime.store, tid)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @app.post('/internal/participant/{operation}')
    async def command(operation: str, request: Request):
        if operation not in {'prepare', 'stage', 'apply', 'release', 'abort', 'collection_demand'}:
            raise HTTPException(404)
        from ..app.manager import json_body
        data = await json_body(request, limit=262144)
        import asyncio
        try:
            return await asyncio.to_thread(runtime.call, lambda: getattr(participant, operation)(data), 45)
        except (ValueError, RuntimeError, KeyError, TimeoutError) as error:
            # TimeoutError is an OSError, not a RuntimeError, so it used to escape as a 500
            # with a traceback even though its own message asks the caller to retry.
            raise HTTPException(409, str(error)) from error
