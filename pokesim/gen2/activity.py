"""Gold, Silver and Crystal action receipts in the shared activity ledger.

The counts use the Red, Blue and Yellow table and increment path (activity_ledger.py), keyed by
National Pokédex number and Gen II item number. Each hook sits at a ROM label from the pinned pret
symbol files, and the opening bytes there are checked before it is placed:

- ``wild``: InitEnemyWildmon, once for every wild battle, after the species is chosen
- ``trainer``: LoadEnemyMonToSwitchTo, each time a trainer sends out a Pokémon, with its slot in B
- ``defeated``: FaintEnemyPokemon, as an opposing Pokémon faints
- ``used``: UseDisposableItem, the Poké Ball toss at the end of PokeBallEffect, and ConsumeTM
  after it has checked a TM is left
- ``vended``: Script_takemoney, where a map script charges for an item it has just given

Purchases from a BUY menu (marts, the Goldenrod Underground bargain shop, the rooftop sale) come
from the hook that store_stock.py already places after ReceiveItem, and catches from the capture
receipts tracking.py keeps. Link battles and the catching tutorial are
not this adventure's actions. Each receipt is the WRAM at the hook, so a reload that replays the
same moment counts nothing.
"""
import hashlib
import json
import logging
import time

from pokecore.gen2.ram import Memory

from ..activity_ledger import KEY, increment

log = logging.getLogger(__name__)
DEBUG, TUTORIAL = 2, 3


def _word(value):
    return bytes((value & 0xFF, value >> 8))


def _code(memory, bank, address, size):
    return bytes(memory[bank, address:address + size])


def hooks(memory, data):
    """(kind, bank, address) of each action hook, verified on the cartridge. ValueError on a mismatch."""
    symbols = data.symbols
    at = lambda name: tuple(symbols[name])
    address = lambda name: symbols[name][1]
    rows = []

    def expect(kind, name, offset, signature):
        bank, start = at(name)
        if _code(memory, bank, start, len(signature)) != signature:
            raise ValueError(f'Gen II activity tracking signature mismatch for {kind}')
        rows.append((kind, bank, start + offset))

    # ld a, WILD_BATTLE / ld [wBattleMode], a
    expect('wild', 'InitEnemyWildmon', 0, b'\x3e\x01\xea' + _word(address('wBattleMode')))
    # ld a, b / ld [wCurPartyMon], a
    expect('trainer', 'LoadEnemyMonToSwitchTo', 0, b'\x78\xea' + _word(address('wCurPartyMon')))
    # call WaitSFX
    expect('defeated', 'FaintEnemyPokemon', 0, b'\xcd' + _word(address('WaitSFX')))
    toss = (b'\x21' + _word(address('wNumItems')) + b'\x3e\x01\xea' + _word(address('wItemQuantityChange'))
            + b'\xc3' + _word(address('TossItem')))
    expect('used', 'UseDisposableItem', 0, toss)
    # ConsumeTM past ``and a / ret z``, where one TM is about to be taken: dec a / ld [hl], a.
    expect('used', 'ConsumeTM', 17, b'\xcd' + _word(address('ConvertCurItemIntoCurTMHM')) + b'\xfa'
           + _word(address('wTempTMHM')) + b'\x3d\x21' + _word(address('wTMsHMs')) + b'\x06\x00\x4f\x09\x7e\xa7\xc8\x3d\x77')
    # PokeBallEffect.toss: ld hl, wNumItems / inc a / ld [wItemQuantityChange], a / jp TossItem.
    bank, start = at('PokeBallEffect')
    body = _code(memory, bank, start, 0x400)
    ball = (b'\x21' + _word(address('wNumItems')) + b'\x3c\xea' + _word(address('wItemQuantityChange'))
            + b'\xc3' + _word(address('TossItem')))
    if body.count(ball) != 1:
        raise ValueError('Gen II activity tracking signature mismatch for used')
    rows.append(('used', bank, start + body.index(ball)))
    # Script_takemoney: call GetMoneyAccount / call LoadMoneyAmountToMem / farcall TakeMoney.
    take = symbols['TakeMoney']
    expect('vended', 'Script_takemoney', 0, b'\xcd' + _word(address('GetMoneyAccount')) + b'\xcd'
           + _word(address('LoadMoneyAmountToMem')) + bytes((0x3E, take[0], 0x21)) + _word(take[1]) + b'\xcf')
    return rows


GIVEITEM, IFFALSE, TAKEMONEY, YOUR_MONEY, ITEM_FROM_MEM = 0x1F, 0x08, 0x23, 0, 0xFF


def vended(memory, mem):
    """(item, quantity) a map script has just charged for, or None for any other payment.

    A script sale (the drink machines, Moomoo Milk, the RageCandyBar seller) runs ``giveitem``,
    ``iffalse`` for a full bag and then ``takemoney YOUR_MONEY``, with at most ``waitsfx`` and
    ``playsound`` between the last two. At Script_takemoney the script engine has read the
    command byte, so wScriptPos points at its account byte.
    """
    bank, position = mem.byte('wScriptBank'), int.from_bytes(mem.read('wScriptPos', 2), 'little')
    if not 0x4000 + 12 <= position < 0x8000:
        return None
    code = bytes(memory[bank, position - 12:position + 1])
    if code[-2:] != bytes((TAKEMONEY, YOUR_MONEY)):
        return None
    # waitsfx comes one command number after playsound in every one of these scripts' engines.
    for start, between in ((5, True), (1, code[7] == code[8] + 1)):
        give = code[start:start + 6]
        if between and give[0] == GIVEITEM and give[3] == IFFALSE:
            item = mem.byte('wCurItem') if give[1] == ITEM_FROM_MEM else give[1]
            return item, give[2]
    return None


def start(store, fresh):
    """Begin counting once, from now. Catches already kept as receipts are counted again from them."""
    with store.lock, store.db:
        db = store.db
        value = json.loads(db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
        value['available'] = True
        if value['started_at'] is None:
            value.update(started_at=time.time(), complete_history=fresh)
            # A store that predates the ledger may hold catches seeded from part of these receipts.
            db.execute("DELETE FROM activity_counts WHERE kind='caught'")
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='capture_receipts'").fetchone():
                for dex, total in db.execute("SELECT dex, COUNT(*) FROM capture_receipts WHERE fingerprint "
                                             "NOT LIKE 'gift-event:%' GROUP BY dex").fetchall():
                    increment(db, 'caught', dex, total)
            from ..trade_statistics import backfill_gen2
            backfill_gen2(db)
        from ..trade_statistics import tracking
        tracking(db)
        db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))


def unavailable(store):
    with store.lock, store.db:
        value = json.loads(store.db.execute('SELECT v FROM kv WHERE k=?', (KEY,)).fetchone()[0])
        value['available'] = False
        store.db.execute('UPDATE kv SET v=? WHERE k=?', (json.dumps(value), KEY))


class Ledger:
    def __init__(self, store, data, *, fresh):
        self.store, self.data, self.fresh = store, data, fresh

    def attach(self, pb):
        try:
            rows = hooks(pb.memory, self.data)
        except (KeyError, ValueError) as error:
            # A cartridge these sites do not match still plays. It just keeps no counts.
            log.warning('Gen II activity tracking is off: %s', error)
            unavailable(self.store)
            return
        for kind, bank, address in rows:
            pb.hook_register(bank, address, self.completed, (kind, pb))
        start(self.store, self.fresh)

    def _record(self, pb, kind, subject, amount=1):
        fingerprint = hashlib.sha256(bytes(pb.memory[0xC000:0xE000])).digest()
        with self.store.lock, self.store.db:
            if self.store.db.execute('INSERT OR IGNORE INTO activity_receipts VALUES (?,?)',
                                     (kind, fingerprint)).rowcount:
                increment(self.store.db, kind, subject, amount)

    def completed(self, context):
        kind, pb = context
        mem = Memory(pb.memory, self.data)
        if kind == 'vended':
            # Outside battle, where wBattleType still holds the last battle's value.
            sale = vended(pb.memory, mem)
            if sale and 1 <= sale[0] <= 249 and 1 <= sale[1] <= 99:
                self._record(pb, 'bought', *sale)
            return
        if mem.byte('wLinkMode') or mem.byte('wBattleType') in (DEBUG, TUTORIAL):
            return
        if kind == 'used':
            item = mem.byte('wCurItem')
            if 1 <= item <= 249 and consumable(self.data, item):
                self._record(pb, kind, item)
            return
        if kind == 'trainer':
            if mem.byte('wBattleMode') != 2:
                return
            slot = pb.register_file.B
            if not 0 <= slot < min(mem.byte('wOTPartyCount'), 6):
                return
            species = mem.byte('wOTPartySpecies', slot)
        else:
            # The species the battle began with, which Transform leaves alone.
            species = mem.byte('wTempEnemyMonSpecies')
            if kind == 'defeated' and mem.byte('wBattleMode') not in (1, 2):
                return
        if 1 <= species <= 251:
            self._record(pb, kind, species)

    def bought(self, pb):
        """A purchase has landed in the bag through the BUY menu."""
        mem = Memory(pb.memory, self.data)
        item, quantity = mem.byte('wCurItem'), mem.byte('wItemQuantityChange')
        if 1 <= item <= 249 and 1 <= quantity <= 99:
            self._record(pb, 'bought', item, quantity)


def gift(db, identifier, species):
    """Count a custom gift once inside the transaction that commits it."""
    if 1 <= species <= 251 and db.execute('INSERT OR IGNORE INTO activity_receipts VALUES (?,?)',
                                          ('gift', f'gen2-gift:{identifier}'.encode())).rowcount:
        increment(db, 'gift', species)


def npc_trade(store, trade):
    """Count a completed in-game trade. Each one has its own flag, so it can happen only once."""
    from ..trade_statistics import record_gen2
    with store.lock, store.db:
        record_gen2(store.db, f'gen2-npc:{trade.index}', trade.request, trade.give)


def real_items(data):
    """(item, name) for every item number the cartridge can hold, without its unused placeholders."""
    return [(item, name) for item, name in sorted(data.item_names.items())
            if 1 <= item <= 249 and name.upper() not in ('TERU-SAMA', '?', '')]


def consumable(data, item):
    """Bag items a use takes away: balls, other ITEM pocket items and TMs. Key items and HMs stay."""
    pocket = (getattr(data, 'item_attributes', None) or {}).get(item, {}).get('pocket')
    if pocket == 'TM_HM':
        return not data.item_names.get(item, '').upper().startswith('HM')
    return pocket != 'KEY_ITEM'
