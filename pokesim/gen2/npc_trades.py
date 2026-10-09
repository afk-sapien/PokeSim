"""In-game NPC trades for Gold, Silver and Crystal.

The table follows pret data/events/npc_trades.asm (pokegold and pokecrystal). Each row lists the
trade index, which is also its bit in wTradeFlags, the person's map object script, the requested
species and the species the person gives. engine/events/npc_trade.asm sets the flag bit before
the trade animation, so a set bit means the trade has happened on this cartridge.
"""
from dataclasses import dataclass

from .menus import ChangeBox, Storage, choose, tracked
from .ram import Memory
from .training import FIELD_MOVES


@dataclass(frozen=True)
class NpcTrade:
    index: int
    npc: str
    map_name: str
    script: str
    request: int
    give: int
    nickname: str
    item: str
    female: bool = False


_SHARED = {
    'KYLE': NpcTrade(1, 'Kyle', 'VIOLET_KYLES_HOUSE', 'Kyle', 69, 95, 'ROCKY', 'BITTER_BERRY'),
    'TIM': NpcTrade(2, 'Tim', 'OLIVINE_TIMS_HOUSE', 'Tim', 98, 100, 'VOLTY', 'PRZCUREBERRY'),
    'KIM': NpcTrade(5, 'Kim', 'ROUTE_14', 'Kim', 113, 142, 'AEROY', 'GOLD_BERRY'),
}
TRADES = {
    'gold': (
        NpcTrade(0, 'Mike', 'GOLDENROD_DEPT_STORE_5F', 'Mike', 96, 66, 'MUSCLE', 'GOLD_BERRY'),
        _SHARED['KYLE'], _SHARED['TIM'],
        NpcTrade(3, 'Emy', 'BLACKTHORN_EMYS_HOUSE', 'Emy', 148, 112, 'DON', 'BITTER_BERRY', female=True),
        NpcTrade(4, 'Chris', 'PEWTER_POKECENTER_1F', 'Chris', 44, 78, 'RUNNY', 'BURNT_BERRY'),
        _SHARED['KIM'],
    ),
    'crystal': (
        NpcTrade(0, 'Mike', 'GOLDENROD_DEPT_STORE_5F', 'Mike', 63, 66, 'MUSCLE', 'GOLD_BERRY'),
        _SHARED['KYLE'], _SHARED['TIM'],
        NpcTrade(3, 'Emy', 'BLACKTHORN_EMYS_HOUSE', 'Emy', 148, 85, 'DORIS', 'SMOKE_BALL', female=True),
        NpcTrade(4, 'Chris', 'PEWTER_POKECENTER_1F', 'Chris', 93, 178, 'PAUL', 'MYSTERYBERRY'),
        _SHARED['KIM'],
        NpcTrade(6, 'Forest', 'POWER_PLANT', 'Forest', 51, 82, 'MAGGIE', 'METAL_COAT'),
    ),
}
TRADES['silver'] = TRADES['gold']


def trades(game):
    return TRADES[game]


def flags(memory, data):
    return Memory(memory, data).byte('wTradeFlags')


def done(memory, data, trade):
    return bool(flags(memory, data) >> trade.index & 1)


def qualifies(mon, trade):
    return mon.species == trade.request and not mon.egg and (not trade.female or mon.gender == 'Female')


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
    if trade.give not in snapshot.owned:
        return True
    spare = held - policy.demand.get(trade.request, 0)
    return spare >= 2 or spare >= 1 and trade.request not in policy.collection.get('prerequisites', ())


def wild(data, species):
    return any(row['species'] == species for row in data.encounters)


def requests(policy, snapshot, memory):
    """Requested species worth catching because the trade would register a new species."""
    if memory is None or 'wTradeFlags' not in policy.data.symbols:
        return set()
    value = flags(memory, policy.data)
    return {trade.request for trade in trades(policy.data.game)
            if not value >> trade.index & 1 and trade.give not in snapshot.owned
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
        counts = {move: sum(move in row.moves for row in snapshot.party) for move in FIELD_MOVES}
        slot = min(range(1, 6), key=lambda i: (
            sum(counts[move] == 1 for move in snapshot.party[i].moves if move in FIELD_MOVES),
            snapshot.party[i].held_item == policy.data.items['EXP_SHARE'], snapshot.party[i].egg,
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
