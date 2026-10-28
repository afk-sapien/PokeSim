"""In-game NPC trades for Gold, Silver and Crystal.

Core owns the trade table (pret data/events/npc_trades.asm) and the rule for which Pokémon a
person accepts. Each trade's index is also its bit in wTradeFlags, and engine/events/npc_trade.asm
sets that bit before the trade animation, so a set bit means the trade has happened on this cartridge.
"""
from dataclasses import dataclass

from .menus import ChangeBox, Storage, choose, tracked
from pokecore.gen2.ram import Memory
from pokecore.gen2.state import npc_trade_qualifies as qualifies
from pokecore.gen2.tables import NPC_TRADES as TRADES, NpcTrade, npc_trades as trades  # noqa: F401  (re-exported)
from .training import FIELD_MOVES


def flags(memory, data):
    return Memory(memory, data).byte('wTradeFlags')


def candidate(snapshot, trade):
    """The copy to hand over: an untouched party member or box copy that no plan depends on."""
    party = snapshot.party
    counts = {move: sum(move in mon.moves for mon in party if not mon.egg) for move in FIELD_MOVES}
    choices = []
    for mon in party + snapshot.stored:
        if not qualifies(mon, trade) or mon.held_item:
            continue
        if mon.box is None and any(counts[move] == 1 for move in mon.moves if move in FIELD_MOVES):
            continue
        choices.append((mon.box is not None, mon.level, mon.box or 0, mon.position or 0, mon))
    return min(choices, key=lambda row: row[:4])[-1] if choices else None


def worth_trading(policy, snapshot, trade):
    held = sum(qualifies(mon, trade) for mon in snapshot.party + snapshot.stored)
    if trade.give not in snapshot.owned or trade.give in getattr(policy, 'returned', ()):
        # A walking return reopened this trade because its Pokémon has no other source.
        return held - policy.demand.get(trade.request, 0) >= 1 if trade.give in snapshot.owned else True
    spare = held - policy.demand.get(trade.request, 0)
    return spare >= 2 or spare >= 1 and trade.request not in policy.collection.get('prerequisites', ())


_WILD = [None, frozenset()]
_REQUESTS = [None, frozenset()]


def wild(data, species):
    encounters = data.encounters
    if _WILD[0] is not encounters:
        _WILD[:] = [encounters, frozenset(row['species'] for row in encounters)]
    return species in _WILD[1]


def requests(policy, snapshot, memory):
    """Requested species worth catching because the trade would register a new species or a returned one.

    Runs every step, so the set is kept until the trade flags, the dex or a held copy changes.
    """
    if memory is None or 'wTradeFlags' not in policy.data.symbols:
        return set()
    value = flags(memory, policy.data)
    returned = frozenset(getattr(policy, 'returned', ()))
    key = (policy.data, policy.data.encounters, value, snapshot.owned, snapshot.party, snapshot.stored, returned)
    cached = _REQUESTS[0]
    if (cached is not None and cached[0] is key[0] and cached[1] is key[1]
            and cached[2:] == key[2:]):
        return set(_REQUESTS[1])
    found = _requests(policy, snapshot, value, returned)
    _REQUESTS[:] = [key, frozenset(found)]
    return found


def _requests(policy, snapshot, value, returned=frozenset()):
    return {trade.request for trade in trades(policy.data.game)
            if not value >> trade.index & 1 and (trade.give not in snapshot.owned or trade.give in returned)
            and not any(qualifies(mon, trade) for mon in snapshot.party + snapshot.stored)
            and wild(policy.data, trade.request)}


def completed(memory, data, history):
    """Trades whose flag is newly set, appending each index to the persisted history list."""
    if 'wTradeFlags' not in data.symbols:
        return []
    value = flags(memory, data)
    rows = [trade for trade in trades(data.game) if value >> trade.index & 1 and trade.index not in history]
    history.extend(trade.index for trade in rows)
    return rows


def record(policy, snapshot, memory):
    """Note trades the cartridge has completed in the persisted collection state."""
    value = flags(memory, policy.data)
    log = policy.collection.setdefault('npc_trades', [])
    known = {row['index'] for row in log}
    for trade in trades(policy.data.game):
        if value >> trade.index & 1 and trade.index not in known:
            log.append({'index': trade.index, 'npc': trade.npc, 'request': trade.request, 'give': trade.give,
                        'decision': policy.decisions})
    return value


def journey(policy, snapshot, mem, Goal):
    from pokecore.gen2.breeding import free_slots
    if 'wTradeFlags' not in policy.data.symbols or getattr(mem, 'memory', None) is None:
        return None
    value = record(policy, snapshot, mem.memory)
    data = policy.data
    for trade in trades(data.game):
        if value >> trade.index & 1 or not worth_trading(policy, snapshot, trade):
            continue
        mon = candidate(snapshot, trade)
        if mon is None:
            continue
        if mon.box is not None and len(snapshot.party) == 6 and free_slots(snapshot) < 1:
            # With the party and every box full the PC cannot swap the partner out, so the errand would
            # press B at the PC forever. The trade waits until there is room.
            continue
        request, give = data.species[trade.request]['name'], data.species[trade.give]['name']
        policy.collection['npc_trade'] = trade.index
        policy.collection['phase'] = 'trading'
        if mon.box is not None:
            goal = policy.storage_goal(snapshot)
            return Goal('collection_npc_trade_pc', f'Bring {request} from storage for {trade.npc}’s trade',
                        goal.map_name, goal.x, goal.y, goal.face)
        return policy.person(snapshot, 'collection_npc_trade', f'Trade {request} to {trade.npc} for {give}',
                             trade.map_name, trade.script)
    policy.collection.pop('npc_trade', None)
    return None


def arrive(policy, snapshot):
    key = policy.goal.key
    if key not in {'collection_npc_trade', 'collection_npc_trade_pc'}:
        return None
    index = policy.collection.get('npc_trade')
    trade = next((row for row in trades(policy.data.game) if row.index == index), None)
    if trade is None:
        return 'b'
    mon = candidate(snapshot, trade)
    if mon is None:
        return 'b'
    if key == 'collection_npc_trade':
        if mon.box is not None:
            return 'b'
        policy.menu = Trade(next(i for i, row in enumerate(snapshot.party) if row is mon), trade.index)
        return 'a'
    if mon.box is None:
        return 'b'
    if len(snapshot.party) == 6:
        from .breeding import carried
        counts = {move: sum(move in row.moves for row in snapshot.party) for move in FIELD_MOVES}
        slot = min(range(1, 6), key=lambda i: (
            carried(policy, snapshot, snapshot.party[i]), sum(counts[move] == 1 for move in snapshot.party[i].moves if move in FIELD_MOVES), snapshot.party[i].egg,
            snapshot.party[i].held_item == policy.data.items['EXP_SHARE'],
            snapshot.party[i].level))
        if snapshot.box_counts[snapshot.active_box] >= 20:
            box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
            if box is None:
                return 'b'
            policy.menu = ChangeBox(box)
        else:
            policy.menu = Storage('DEPOSIT', slot, len(snapshot.party))
        return 'a'
    policy.menu = ChangeBox(mon.box) if mon.box != snapshot.active_box else Storage('WITHDRAW', mon.position, len(snapshot.party))
    return 'a'


@dataclass
class Trade:
    """Answer the trader YES, pick the requested partner and let the exchange finish.

    The task ends when the cartridge sets the trade's wTradeFlags bit, which happens before the
    animation, or when the chosen partner leaves its slot. Conversation handling finishes the
    remaining text.
    """
    slot: int
    index: int
    steps: int = 0
    exit_steps: int = 0
    member: list | None = None

    def step(self, snapshot, mem):
        self.steps += 1
        if mem.byte('wTradeFlags') >> self.index & 1 or tracked(self, snapshot) is None:
            return None
        if self.exit_steps or self.steps > 300:
            self.exit_steps += 1
            return 'b' if self.exit_steps < 8 else None
        # The trade party menu shows each gender where other menus show HP, so it has no slash.
        if 'CANCEL' in snapshot.text and ('/' in snapshot.text or 'Choose a' in snapshot.text):
            cursor = mem.byte('wMenuCursorY') - 1
            return 'a' if cursor == self.slot else 'down' if cursor < self.slot else 'up'
        return choose(snapshot.tiles, 'YES', exact=True) or 'a'
