"""Recover individual victory records from saved Hall of Fame evidence."""
import io
import logging
import re
from collections import Counter
from dataclasses import asdict

from . import league_partners as league
from .checkpoints import open_state
from .ram import read_snapshot

log = logging.getLogger(__name__)


def recover(store, rom, *, factory=None):
    """Use a separate emulator without ticking or writing cartridge saves."""
    with store.lock:
        if league.read(store.db).get('history_recovered'):
            return
        rows = list(store.db.execute("SELECT id,title,state,body FROM events WHERE type='champion' ORDER BY id"))
    failed = []
    named = []
    pb = None
    try:
        try:
            latest = store.latest_state()
            if latest is not None:
                if factory is None:
                    from pokesim_core.emulator import Emulator as CoreEmulator
                    factory = CoreEmulator
                pb = factory(str(rom), ram_file=io.BytesIO(bytes(32768)),
                             window='null', sound_emulated=False, log_level='ERROR')
                with open_state(latest) as stream:
                    pb.load_state(stream)
                current = read_snapshot(pb.memory, 0)
                if current.valid:
                    with store.lock, store.db:
                        value = league.read(store.db)
                        league.resolve(value, [asdict(mon) for mon in current.party] + current.storage_entries(),
                                       allow_rename=False)
                        league.save(store.db, value)
        except Exception:
            log.warning('Could not read current party for League history recovery', exc_info=True)
            if pb is not None:
                pb.stop(save=False)
                pb = None
        for row in rows:
            path = store.state_path(row['state']) if row['state'] else None
            if path is None:
                named.append(row)
                continue
            try:
                if pb is None:
                    if factory is None:
                        from pokesim_core.emulator import Emulator as CoreEmulator
                        factory = CoreEmulator
                    pb = factory(str(rom), ram_file=io.BytesIO(bytes(32768)),
                                 window='null', sound_emulated=False, log_level='ERROR')
                with open_state(path) as stream:
                    pb.load_state(stream)
                snapshot = read_snapshot(pb.memory, 0)
                if not snapshot.valid or snapshot.map != league.HALL_OF_FAME_MAP:
                    raise ValueError('Saved event is not a Hall of Fame party')
                with store.lock, store.db:
                    league.record(store.db, snapshot, row['title'], row['id'], allow_rename=False)
            except Exception:
                failed.append(row['id'])
                log.warning('Could not recover Hall of Fame event %s', row['id'], exc_info=True)
    finally:
        if pb is not None:
            pb.stop(save=False)
    with store.lock, store.db:
        value = league.read(store.db)
        legacy = league._read(store.db, league.LEGACY_KEY) or {}
        for row in named:
            if not recover_named(value, row, legacy):
                failed.append(row['id'])
        missing = sorted(set(legacy.get('victories', ())) - set(value['victories']))
        value.update(history_recovered=True, history_complete=not failed and not missing,
                     missing_events=failed, missing_victories=missing)
        league.save(store.db, value)
    log.info('Recovered individual League history: %s events, %s missing', len(rows), len(failed))


def recover_named(value, row, legacy=None):
    """A saved party list can identify a uniquely named known partner."""
    match = re.fullmatch(r'Champion! League victory #(\d+)', row['title'])
    token = 'league:' + match[1] if match else f"event:{row['id']}"
    if token in value['victories']:
        return True
    body = row['body']
    if not body.startswith('Party: ') or not body.endswith('.'):
        return False
    names = []
    for part in body[7:-1].split(', '):
        match = re.fullmatch(r'(.+) L([0-9]{1,3})', part)
        if not match or not 1 <= int(match[2]) <= 100:
            return False
        names.append(match[1].upper())
    if not 1 <= len(names) <= 6:
        return False
    counts = Counter(names)
    complete = True
    for name in names:
        matches = [entry for entry in value['partners'].values()
                   if name in entry['names'] or ('' in entry['names'] and name in
                       league.default_names(int(entry['signature'].split(':')[1])))]
        if legacy is not None:
            matches = [entry for entry in matches if entry.get('first_event', float('inf')) <= row['id'] and (
                legacy.get('partners', {}).get(entry['signature'].split(':')[0], {}).get('ambiguous')
                or legacy.get('partners', {}).get(entry['signature'].split(':')[0], {}).get('counts', {}).get(value['origin'], 0))]
        if counts[name] != 1 or len(matches) != 1 or matches[0]['ambiguous']:
            complete = False
            continue
        entry = matches[0]
        origin = value['origin']
        if legacy is not None:
            old_key = entry['signature'].split(':')[0]
            old = legacy.get('partners', {}).get(old_key, {})
            verified = sum(e['counts'].get(origin, 0) for e in value['partners'].values()
                           if e['signature'].split(':')[0] == old_key)
            if not old.get('ambiguous') and verified >= old.get('counts', {}).get(origin, 0):
                continue
        entry['counts'][origin] = entry['counts'].get(origin, 0) + 1
    value['victories'].append(token)
    return complete
