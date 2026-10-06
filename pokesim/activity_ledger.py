"""Per-species and per-item action receipts, independent of sampled observations."""
from collections import Counter
import hashlib
import json
import re
import time

from .ram import DEX_NAMES, ITEM_NAMES
from .strategy_data import SPECIES

KEY = 'activity-ledger-v1'
# Consume only at successful item-removal paths, never at inventory transfers.
CONSUMABLES = (set(range(1, 5)) | {8, 10, 29, 30, 32, 33, 34, 46, 47, 51}
               | set(range(11, 21)) | set(range(35, 41)) | set(range(52, 59))
               | set(range(60, 63)) | set(range(65, 69)) | set(range(79, 84)) | set(range(201, 251)))
ITEMS = {key: name for key, name in ITEM_NAMES.items()
         if 1 <= key <= 83 and key not in {7, 9, *range(21, 29), 44, 50, 59}
         or 196 <= key <= 250}
# Verified English Red/Blue instructions from pret/pokered. Wildcard bytes are
# call or branch destinations. Each sequence must occur exactly the expected number of times.
HOOKS = (
    ('wild', 15, rb'\x3e\x01\xea\x57\xd0\xcd..\xcd..\xfa\x59\xd0', 8, 1),
    ('trainer', 15, bytes.fromhex('21f1cf227011f3cffa27d112'), 12, 1),
    ('defeated', 15, rb'\xaf\xea\xf0\xcc\xcd..\xcd..\x7a\xa7\xca..\x21\x15\xd0', 0, 1),
    ('used', 3, rb'\x21\x1d\xd3\x3e\x01\xea\x96\xcf\xc3..', 0, 2),
    ('ball', 3, bytes.fromhex('fa5ad0a7c0211dd33cea96cf'), 8, 1),
    ('safari', 3, rb'\x21\x47\xda\x35\xcd..\x3e\x43\xea\x1e\xd1', 3, 1),
    ('bought', 1, rb'\x21\x1d\xd3\xcd..\x30.\xcd..\xfa\x0a\xcf\xa7\x20.\x3e\x01', 8, 1),
    ('vending', 29, rb'\xf0\xdb\x47\x0e\x01\xcd..\x30.\x06\x3c\x0e\x02', 10, 1),
)


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS activity_counts ('
               'kind TEXT NOT NULL, subject INTEGER NOT NULL, total INTEGER NOT NULL, '
               'PRIMARY KEY(kind,subject))')
    db.execute('CREATE TABLE IF NOT EXISTS activity_receipts ('
               'kind TEXT NOT NULL, fingerprint BLOB NOT NULL, PRIMARY KEY(kind,fingerprint))')
    if db.execute('SELECT 1 FROM kv WHERE k=?', (KEY,)).fetchone():
        return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='capture_receipts'").fetchone():
        # Receipts distinguish caught partners from custom gifts without journal parsing.
        for kind, dex, total in db.execute(
                "SELECT CASE WHEN fingerprint LIKE 'gift-event:%' THEN 'gift' ELSE 'caught' END, "
                'dex, COUNT(*) FROM capture_receipts GROUP BY 1,2'):
            increment(db, kind, dex, total)
    db.execute('INSERT INTO kv VALUES (?,?)', (KEY, json.dumps({'started_at': None, 'available': False})))


def increment(db, kind, subject, amount=1):
    db.execute('INSERT INTO activity_counts VALUES (?,?,?) '
               'ON CONFLICT(kind,subject) DO UPDATE SET total=total+excluded.total',
               (kind, subject, amount))


class ActivityLedger:
    def __init__(self, store, rom_sha1):
        from .catches import SUPPORTED
        self.store = store
        self.supported = rom_sha1 in SUPPORTED

    def attach(self, pb):
        # Attach before the shiny and catch hooks. Our hook sites sit outside
        # their signature bytes even where the routines share an instruction block.
        matches = []
        if self.supported:
            for kind, bank, pattern, offset, expected in HOOKS:
                data = bytes(pb.memory[bank, 0x4000:0x7fff])
                found = list(re.finditer(pattern, data, re.DOTALL))
                if len(found) != expected:
                    raise ValueError(f'Activity tracking signature mismatch for {kind}')
                matches.extend((kind, bank, 0x4000 + match.start() + offset) for match in found)
            for kind, bank, address in matches:
                pb.hook_register(bank, address, self.completed, (kind, pb))
        with self.store.lock, self.store.db:
            value = json.loads(self.store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
            value['available'] = self.supported
            if self.supported:
                value['started_at'] = value['started_at'] or time.time()
            self.store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))

    def completed(self, context):
        kind, pb = context
        mem = pb.memory
        # Cable battles and the old man's tutorial are not this adventure's actions.
        if mem[0xd12b] or mem[0xd057] and mem[0xd05a] == 1:
            return
        amount = 1
        if kind in {'wild', 'trainer', 'defeated'}:
            if mem[0xd057] not in (1, 2):
                return
            if kind == 'wild' and mem[0xd057] != 1:
                return
            if kind == 'trainer' and (mem[0xd057] != 2 or mem[0xd069] & 8):
                return
            # Species2 remains the original species when Ditto uses Transform.
            species = mem[0xcfd8]
            if species not in SPECIES:
                return
            subject = SPECIES[species]['dex']
            if kind == 'defeated' and (mem[0xcfe6] or mem[0xcfe7]):
                return
        else:
            subject = mem[0xcf91]
            if kind in {'ball', 'used'}:
                # wCurItem aliases wCurPartySpecies and is overwritten on capture.
                # Read the exact bag slot the cartridge is about to consume.
                slot = mem[0xcf92]
                if not 0 <= slot < mem[0xd31d] <= 20:
                    return
                subject = mem[0xd31e + slot * 2]
                if not mem[0xd31f + slot * 2]:
                    return
            if kind == 'safari':
                subject = 8
            if kind in {'ball', 'safari', 'used'}:
                if subject not in CONSUMABLES:
                    return
                kind = 'used'
            elif kind == 'vending':
                subject = mem[0xffdb]
                if subject not in (60, 61, 62):
                    return
                kind = 'bought'
            else:
                amount = mem[0xcf96]
            if subject not in ITEMS or not 1 <= amount <= 99:
                return
        fingerprint = hashlib.sha256(bytes(mem[0xc000:0xe000])).digest()
        with self.store.lock, self.store.db:
            if self.store.db.execute('INSERT OR IGNORE INTO activity_receipts VALUES (?,?)',
                                     (kind, fingerprint)).rowcount:
                increment(self.store.db, kind, subject, amount)


def status(store, game=None):
    from .catches import status as catches
    game = game or {}
    with store.lock:
        metadata = json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
        counts = {(row[0], row[1]): row[2] for row in store.db.execute('SELECT * FROM activity_counts')}
    captures = catches(store)
    held = Counter()
    for mon in [*game.get('party', []), *(game.get('storage') or {}).get('pokemon', [])]:
        dex = SPECIES.get(mon.get('species'), {}).get('dex')
        if dex:
            held[dex] += 1
    bag = Counter()
    for item in game.get('items', []):
        bag[item['id']] += item['qty']
    def count(kind, subject):
        return counts.get((kind, subject), 0) if metadata['started_at'] is not None else None
    return {**metadata, 'captures_since': captures['started_at'],
            'captures_available': captures['available'],
            'pokemon': [{'id': dex, 'name': name, 'wild': count('wild', dex),
                         'trainer': count('trainer', dex), 'defeated': count('defeated', dex),
                         'caught': counts.get(('caught', dex), 0) if captures['available'] else None,
                         'gift': counts.get(('gift', dex), 0), 'held': held[dex] if game else None}
                        for dex, name in sorted(DEX_NAMES.items()) if 1 <= dex <= 151],
            'items': [{'id': item, 'name': name, 'bought': count('bought', item),
                       'used': count('used', item) if item in CONSUMABLES else None,
                       'bag': bag[item] if game else None} for item, name in sorted(ITEMS.items())]}
