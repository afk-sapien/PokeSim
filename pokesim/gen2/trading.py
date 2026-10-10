"""Generation II participants in durable managed Cable Club exchanges."""
from collections import Counter
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

from .core import boot

from .. import config
from ..app.registry import digest, validate_id
from ..checkpoints import CheckpointStore
from ..runtime.participant import Participant as BaseParticipant, PREFIX, _records, _save, _artifact, manual_rows
from ..trade.preferences import apply
from .cable_verification import available_trade_item, checkpoint_clock, continue_save, evolved_species, individual_key, party, verify_exchange
from .preparation import begin
from .ram import Memory, read_snapshot
from .web import live_status
from .timecapsule import compatible, unlocked
from .timecapsule_conversion import convert


def status(emu, payload, adventure_id):
    return {'connected': bool(adventure_id), 'instance': adventure_id or emu.data.game,
            'version': emu.data.game, 'generation': 2, 'managed': bool(adventure_id),
            'viewer_only': config.VIEWER_ONLY, 'holding': bool(emu.store.get('trade_hold')),
            'offers': listings(emu, payload), 'opportunities': [], 'history': emu.store.events(types=['trade'], limit=50),
            'peers': [], 'trading': {'enabled': bool(adventure_id), 'managed': bool(adventure_id)},
            'message': 'Useful exchanges happen automatically with compatible adventures in this library.'}


def _paused(emu, snapshot):
    """Why no boxed Pokémon can be offered right now, or '' when trading is open."""
    collection = emu.policy.collection
    if snapshot is None:
        return 'Waiting for the game to start'
    if emu.policy.in_league(snapshot):
        return 'Trading pauses during the Pokémon League'
    if collection.get('tower') or collection.get('contest'):
        return 'Trading pauses during the current event'
    if collection.get('time_capsule_restore'):
        return 'Trading pauses while the team is restored'
    return ''


def _kept(mon, stock):
    """Why one boxed Pokémon stays out of automatic offers, or '' when it is eligible."""
    preference = mon.get('trade_preference', 'auto')
    if mon.get('egg'):
        return 'Eggs are not traded'
    if not mon.get('trade_key') or mon.get('trade_ambiguous'):
        return 'Individual identity is ambiguous'
    if preference == 'locked':
        return 'Locked against trading and automatic release'
    if preference == 'withdrawn':
        return 'Withdrawn by you'
    if tuple(mon.get('dvs', ())) == (15,) * 5:
        return 'Perfect DV partner preserved for the collection'
    if preference == 'offered':
        return ''
    if mon['species'] in stock:
        # The Day Care breeds a spare to send instead, so the parent itself stays.
        return 'Kept as a Day Care parent; a bred spare is sent instead'
    if mon.get('shiny'):
        return 'Shiny partner preserved for the collection'
    if sum(mon.get('stat_exp', ())) >= 20000:
        return 'Trained partner kept by automatic selection'
    return ''


def _stock(emu, rows):
    from .breeding import breeding_stock
    return breeding_stock(emu.data, [mon['species'] for mon in rows if not mon.get('egg')])


def offers(emu, payload):
    snapshot = emu.snapshot
    if _paused(emu, snapshot):
        return []
    party = payload.get('party') or []
    stored = (payload.get('storage') or {}).get('pokemon') or []
    held = Counter(mon['species'] for mon in party + stored)
    stock = _stock(emu, party + stored)
    result = []
    for mon in stored:
        if _kept(mon, stock):
            continue
        equip = available_trade_item(emu.data, mon['species'], mon.get('held_item', 0), dict(snapshot.items))
        raw = bytes([mon['species'], equip or mon.get('held_item', 0)])
        actual = next(member for member in snapshot.stored if member.box + 1 == mon['box'] and member.position + 1 == mon['position'])
        result.append({**mon, 'time_capsule_compatible': compatible(actual, emu.data), 'last_copy': held[mon['species']] == 1,
                       'arrived_dex': evolved_species(raw, emu.data), 'equip_item': equip, 'cartridge_generation': 2})
    return result


def listings(emu, payload):
    """Every party and boxed Pokémon with its trade state, so the PC can explain any of them.

    offers() stays the eligibility list the coordinator trades from; this view adds the
    Pokémon it leaves out, each with the reason, in the shape the Gen I listings use.
    """
    party = payload.get('party') or []
    stored = (payload.get('storage') or {}).get('pokemon') or []
    eligible = {mon['trade_key']: mon for mon in offers(emu, payload)}
    paused = _paused(emu, emu.snapshot)
    stock = _stock(emu, party + stored)
    rows = []
    for mon in stored:
        preference = mon.get('trade_preference', 'auto')
        shiny, perfect = bool(mon.get('shiny')), tuple(mon.get('dvs', ())) == (15,) * 5
        editable = bool(mon.get('trade_key')) and not mon.get('trade_ambiguous') and not mon.get('egg')
        listed = mon.get('trade_key') in eligible
        rows.append({**eligible.get(mon.get('trade_key'), mon), 'shiny': shiny, 'perfect_dvs': perfect,
                     'preference': preference, 'locked': preference == 'locked', 'listed': listed,
                     'reason': '' if listed else paused or _kept(mon, stock) or 'Kept by automatic selection',
                     'can_offer': editable and not shiny and not perfect and preference != 'locked',
                     'editable': editable,
                     'source': 'Selected by you' if preference == 'offered' else 'Automatic'})
    for mon in party:
        preference = mon.get('trade_preference', 'auto')
        rows.append({**mon, 'box': 0, 'position': mon.get('slot'), 'listed': False,
                     'shiny': bool(mon.get('shiny')), 'perfect_dvs': tuple(mon.get('dvs', ())) == (15,) * 5,
                     'locked': preference == 'locked', 'preference': preference, 'source': 'Selected by you',
                     'reason': 'Locked against trading and automatic release' if preference == 'locked' else 'Active party is protected',
                     'can_offer': False,
                     'editable': bool(mon.get('trade_key')) and not mon.get('trade_ambiguous') and not mon.get('egg')})
    return rows


def capsule_reason(mon, data):
    """Why one Gen II Pokémon cannot go through the Time Capsule to a Gen I game."""
    if mon is None or mon.egg:
        return 'Eggs cannot go through the Time Capsule'
    if not 1 <= mon.species <= 151:
        return 'Red, Blue and Yellow only know the first 151 species'
    if any(move > 165 for move in mon.moves):
        return 'It knows a move that does not exist in Red, Blue and Yellow'
    if 'MAIL' in data.item_names.get(mon.held_item, '').upper():
        return 'It holds Mail, which the Time Capsule cannot carry'
    return 'It cannot go through the Time Capsule'


def display(row, data):
    raw = row['struct']
    return {'species': raw[0], 'dex': raw[0], 'name': data.species[raw[0]]['name'],
            'nick': data.text(row['nickname']), 'level': raw[31], 'trainer': data.text(row['trainer'])}


class Participant(BaseParticipant):
    def inventory(self):
        state = self.emu.status()
        payload = apply(live_status(state.get('game'), (state.get('strategy') or {}).get('collection')),
                        self.store.trade_preferences())
        return {**payload, 'adventure_id': self.bootstrap.adventure_id,
                'generation': self.bootstrap.generation, 'cartridge_generation': 2,
                'offers': offers(self.emu, payload), 'revision': digest(payload),
                'time_capsule_ready': unlocked(self.emu.snapshot, Memory(self.emu.pb.memory, self.emu.data)),
                'holding': bool(self.store.get('trade_hold'))}

    def manual_inventory(self):
        """The whole party and PC for a manual trade, with only hard limits marked."""
        state = self.emu.status()
        payload = apply(live_status(state.get('game'), (state.get('strategy') or {}).get('collection')), {})
        snapshot = self.emu.snapshot
        holding = bool(self.store.get('trade_hold'))
        paused = _paused(self.emu, snapshot)
        if paused == 'Trading pauses during the Pokémon League':
            # Preparation finishes the League run first, so it only delays a manual trade.
            paused = ''
        reason = ('This adventure is already held for another exchange' if holding else
                  'Resume autonomous play in this adventure before trading' if self.emu.paused or self.emu.manual_mode else
                  paused)
        rows = manual_rows(payload, 2, last_party_blocked=True)
        if snapshot is not None:
            members = list(snapshot.party) + list(snapshot.stored)
            located = [('party', index + 1, None) for index in range(len(snapshot.party))]
            located += [('box', member.position + 1, member.box + 1) for member in snapshot.stored]
            actual = {place: member for place, member in zip(located, members)}
            for row in rows:
                member = actual.get((row['location'], row['slot'], row['box']))
                row['time_capsule_compatible'] = bool(member is not None and not row['egg'] and compatible(member, self.emu.data))
                row['time_capsule_reason'] = '' if row['time_capsule_compatible'] else capsule_reason(member, self.emu.data)
        return {'adventure_id': self.bootstrap.adventure_id, 'cartridge_generation': 2, 'holding': holding,
                'time_capsule_ready': bool(snapshot is not None and unlocked(snapshot, Memory(self.emu.pb.memory, self.emu.data))),
                'reason': reason, 'pokemon': rows}

    def collection_demand(self, data):
        requests = data.get('requests', {})
        if not isinstance(requests, dict) or len(requests) > 251:
            raise ValueError('Invalid collection requests')
        if any(not str(k).isdigit() or not 1 <= int(k) <= 251 or type(v) is not int or not 1 <= v <= 10000
               for k, v in requests.items()):
            raise ValueError('Invalid collection request')
        self.emu.policy.demand = {int(k): v for k, v in requests.items()}
        return {'requests': self.emu.policy.demand}

    def prepare(self, data):
        tid = validate_id(data['id'])
        selected, plan_digest = data['selected_key'], data['plan_digest']
        record = self.store.get(PREFIX + tid)
        if record:
            if record['plan_digest'] != plan_digest or record['selected_key'] != selected:
                raise ValueError('Interaction parameters changed')
            if record['phase'] != 'preparing':
                return record
        else:
            if data.get('manual'):
                self.manual_choice(selected)
            elif selected not in {row.get('trade_key') for row in self.inventory()['offers']}:
                raise ValueError('The selected Pokémon is not an eligible boxed offer')
            if any(row['phase'] not in {'aborted', 'released'} for row in _records(self.store)):
                raise ValueError('Another interaction already reserves this adventure')
            record = _save(self.store, {'id': tid, 'phase': 'preparing', 'decision': None,
                'plan_digest': plan_digest, 'selected_key': selected, 'cartridge_generation': 2,
                'was_paused': self.emu.paused, 'was_manual': self.emu.manual_mode,
                'time_capsule': bool(data.get('time_capsule')), 'manual': bool(data.get('manual'))})
        prepared = begin(self.emu, selected, tid, time_capsule=record.get('time_capsule', False),
                         manual=record.get('manual', False))
        if prepared['phase'] == 'failed':
            raise ValueError(prepared.get('error', 'Trade preparation failed'))
        if prepared['phase'] != 'ready':
            return {**record, 'preparation': prepared}
        hold = self.store.get('trade_hold')
        if not hold or hold['id'] != tid or not hold.get('source'):
            raise ValueError('The prepared source checkpoint is missing')
        source = self.store.state_path(hold['source'])
        raw = source.read_bytes()
        directory = self.root / tid
        directory.mkdir(exist_ok=True)
        path = directory / 'source.state'
        CheckpointStore.atomic_write(path, raw)
        row = party(self.emu.pb, self.emu.data)[prepared['party_slot']]
        if individual_key(row) != selected:
            raise ValueError('Prepared party member does not match the selected individual')
        snapshot = read_snapshot(self.emu.pb.memory, self.emu.data, self.emu.frame)
        if snapshot.map != self.emu.data.map_ids['POKECENTER_2F'] or snapshot.in_battle:
            raise ValueError('Prepared adventure is not in a Pokémon Center')
        if prepared.get('original_party'):
            record['time_capsule_original'] = prepared['original_party']
        record.update(phase='prepared', source_name=source.name, source_metadata=self.store.checkpoint_metadata(source),
                      source_center_map=snapshot.map, outgoing_display=display(row, self.emu.data),
                      source={'adventure_id': self.bootstrap.adventure_id, 'rom_path': self.runtime.settings.rom_path,
                              'game_data_dir': self.runtime.settings.game_data_dir,
                              'checkpoint_path': str(path), 'cartridge_save_path': None,
                              'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                              'party_slot': prepared['party_slot'], 'selected_key': selected},
                      outgoing={key: value.hex() for key, value in row.items()})
        from .league import export
        record['outgoing_league_record'] = export(self.store, self.emu.data, snapshot.party[prepared['party_slot']].to_dict())
        return _save(self.store, record)

    def incoming_record(self, record, data):
        incoming = {key: bytes.fromhex(value) for key, value in data['incoming'].items()}
        incoming = convert(incoming, 2, self.emu.data)
        record['incoming_display'] = display(incoming, self.emu.data)
        from .league import validate
        from .ram import decode_mon
        mon = decode_mon(incoming['struct'], incoming['nickname'], self.emu.data)
        league = data.get('incoming_league_record')
        if record.get('time_capsule'):
            from .timecapsule_records import to_gen2
            league = to_gen2(league, data['incoming'], self.emu.data)
        record['incoming_league_record'] = validate(league, self.emu.data, mon.to_dict())

    def verify_result(self, record, result, state, save, incoming):
        data = self.emu.data
        rom = Path(self.runtime.settings.rom_path).read_bytes()
        pb = boot(io.BytesIO(rom), sound=False)
        try:
            pb.load_state(io.BytesIO(_artifact(record['source']['checkpoint_path'], record['source']['checkpoint_sha256'])))
            before, snapshot = party(pb, data), read_snapshot(pb.memory, data)
            if snapshot.map != data.map_ids['POKECENTER_2F'] or snapshot.in_battle:
                raise ValueError('Prepared source is outside the Pokémon Center')
            received = {key: bytes.fromhex(value) for key, value in incoming.items()}
            received = convert(received, 2, data)
            pb.load_state(io.BytesIO(state))
            side = SimpleNamespace(pb=pb, data=data, frame=0)
            expected, _ = verify_exchange(side, before, received, record['source']['party_slot'], snapshot, time_capsule=record.get('time_capsule', False))
            if Memory(pb.memory, data).byte('wLinkMode') != 0:
                raise ValueError('The returned checkpoint is still in link mode')
            restarted = continue_save(rom, save, data, rtc=checkpoint_clock(rom, state))
            try:
                if party(restarted, data) != expected:
                    raise ValueError('Cartridge save differs from the staged checkpoint')
                verify_exchange(SimpleNamespace(pb=restarted, data=data, frame=0), before, received,
                                record['source']['party_slot'], snapshot, time_capsule=record.get('time_capsule', False))
            finally:
                restarted.stop(save=False)
        finally:
            pb.stop(save=False)

    def restore_team(self, record):
        original = record.get('time_capsule_original')
        if original and not record.get('team_restore_scheduled'):
            self.emu.policy.collection['time_capsule_restore'] = original
            record['team_restore_scheduled'] = True
            self.emu._autosave()
            _save(self.store, record)
        self.emu.preparation = None
        return record

    def release(self, data):
        return self.restore_team(super().release(data))

    def abort(self, data):
        preparation = self.store.get('interaction_preparation') or {}
        record = super().abort(data)
        if preparation.get('original_party'):
            record['time_capsule_original'] = preparation['original_party']
        return self.restore_team(record)


def install(app, runtime):
    from ..runtime.participant import install as install_participant
    install_participant(app, runtime, Participant)
