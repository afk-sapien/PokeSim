"""Shop interaction state, independent of the strategic policy's PC and battle state."""
from dataclasses import dataclass

from .battle import BALLS, HEALING, shopping_item
from .progression import Goal
from .collection import legendary_project
from .menus import MenuDecision, select, tap
from ..strategy_data import DATA, ITEMS, MAPS, PRICES, WORLD

# Red and Blue refuse Safari Zone entry below this amount, and the story needs two visits' worth of
# prizes (Surf and the Gold Teeth), so an unaffordable fee is a permanent roadblock, not a delay.
SAFARI_FEE = 500
CASH_RESERVE = 300
SAFARI_GOALS = ('surf', 'teeth')
SAFARI_INTERIOR = {m for m, w in WORLD.items() if w['name'].startswith('SafariZone') and w['name'] != 'SafariZoneGate'}
SPARE = {ITEMS[name] for name in ('NUGGET', 'X_ACCURACY', 'GUARD_SPEC', 'DIRE_HIT', 'X_ATTACK', 'X_DEFEND',
                                  'X_SPEED', 'X_SPECIAL')}
LUXURIES = {ITEMS[name] for name in ('HP_UP', 'PROTEIN', 'IRON', 'CARBOS', 'CALCIUM', 'PP_UP', 'RARE_CANDY')}


def entry_fee(snapshot, goal_key):
    """Cash the current objective needs at a gate before it can make any progress."""
    return SAFARI_FEE if goal_key in SAFARI_GOALS and snapshot.map not in SAFARI_INTERIOR else 0


def cash_reserve(snapshot):
    """Keep the Safari fee untouched from the fourth badge until both Safari prizes are collected."""
    counts = dict(snapshot.items)
    knows = {move for mon in snapshot.party for move in mon.moves}
    surf = counts.get(ITEMS['HM03']) or 57 in knows
    strength = counts.get(ITEMS['HM04']) or 70 in knows or counts.get(ITEMS['GOLD_TEETH'])
    return CASH_RESERVE + (SAFARI_FEE if snapshot.badges & 8 and not (surf and strength) else 0)


@dataclass
class SupplyPlan:
    goal: Goal
    prepared: bool = False
    abandon: str | None = None


@dataclass
class ShoppingController:
    buying: bool = False
    selling: bool = False
    item: int | None = None
    restocking: bool = False
    fund_target: int = 0

    def leave_menu(self):
        self.buying = self.selling = False
        self.item = None

    @staticmethod
    def item_for(snapshot, stock, goal_key, project):
        if goal_key == 'collect_stone' and project and snapshot.map == MAPS['CELADON_MART_4F']:
            item = ITEMS[project['evolution']['requirement']]
            return item if item in stock and not dict(snapshot.items).get(item) and snapshot.money >= 2500 and len(snapshot.items) < 20 else None
        return shopping_item(snapshot.items, stock, snapshot.money,
                             snapshot.map == MAPS['INDIGO_PLATEAU_LOBBY'], collecting=True,
                             legendary=legendary_project(project), reserve=cash_reserve(snapshot))

    @staticmethod
    def fund_index(snapshot):
        """Bag slot to sell for cash: spares first, then luxuries, then the priciest remaining supply."""
        def rank(row):
            item = row[1]
            tier = 0 if item in SPARE or 201 <= item <= 250 else 1 if item in LUXURIES else 3 if item in BALLS else 2
            return tier, -PRICES.get(item, 0)
        rows = [(i, item) for i, (item, qty) in enumerate(snapshot.items) if qty and PRICES.get(item, 0) > 0]
        return min(rows, key=rank)[0] if rows else None

    def raising_funds(self, snapshot):
        return bool(self.fund_target) and snapshot.money < self.fund_target

    def _sale_choice(self, snapshot):
        if self.raising_funds(snapshot):
            return self.fund_index(snapshot)
        return self.sale_index(snapshot) if len(snapshot.items) > 15 else None

    @staticmethod
    def sale_index(snapshot):
        return next((i for i, (item, qty) in enumerate(snapshot.items)
                     if qty and (item == ITEMS['NUGGET'] or 201 <= item <= 250
                                 or len(snapshot.items) >= 18 and item in {
                                     ITEMS[name] for name in ('X_ACCURACY', 'GUARD_SPEC', 'DIRE_HIT',
                                                             'X_ATTACK', 'X_DEFEND', 'X_SPEED', 'X_SPECIAL')})), None)

    def plan(self, snapshot, goal, project, *, requested_goal, healing, in_league, has_pokedex, completed_champion=False):
        fee = entry_fee(snapshot, goal.key)
        self.fund_target = fee + CASH_RESERVE if fee and snapshot.money < fee else 0
        if self.fund_target and not healing and not in_league and has_pokedex and self.fund_index(snapshot) is not None:
            clerks = [(map_id, 2, clerk[1]) for map_id, world in WORLD.items() if world['name'] in DATA['marts']
                      for clerk in world['objects'] if clerk[2] == 'SPRITE_CLERK' and clerk[0] == 0]
            if clerks:
                return SupplyPlan(Goal('restock', 'Raise the Safari Zone entry fee',
                                       'Sell spare valuables at a shop because the Safari Zone turns away anyone short of the fee',
                                       tuple(clerks), 'left', True))
        ball_reserve = 5 if completed_champion else 2
        balls = sum(qty for item, qty in snapshot.items if item in BALLS)
        medicine = sum(qty for item, qty in snapshot.items if item in HEALING)
        bag_full = len(snapshot.items) >= 18 and self.sale_index(snapshot) is not None
        if balls < ball_reserve or (medicine == 0 and (snapshot.map in (2, 56)
                or WORLD.get(snapshot.map, {}).get('name', '').endswith('Gym'))) or bag_full:
            self.restocking = True
        elif balls >= ball_reserve and medicine and not bag_full:
            self.restocking = False
        if snapshot.map == MAPS['INDIGO_PLATEAU_LOBBY']:
            counts = dict(snapshot.items)
            self.restocking = (balls < ball_reserve or medicine < 10 or counts.get(ITEMS['REVIVE'], 0) < 5
                               or counts.get(ITEMS['FULL_HEAL'], 0) < 3)
        legendary = legendary_project(project)
        if legendary and not dict(snapshot.items).get(ITEMS['MASTER_BALL']):
            self.restocking = (not project.get('supplies_prepared')
                               or dict(snapshot.items).get(ITEMS['ULTRA_BALL'], 0) < 5 or bag_full)
        if not (self.restocking and not healing and not in_league and goal.key != 'party_box' and has_pokedex):
            return SupplyPlan(goal)
        targets = []
        for map_id, world in WORLD.items():
            if snapshot.map == MAPS['INDIGO_PLATEAU_LOBBY'] and map_id != snapshot.map:
                continue
            stock = DATA['marts'].get(world['name'], [])
            if map_id != snapshot.map and not legendary:
                stock = [item for item in stock if item in BALLS or item in HEALING or item == ITEMS['REVIVE']]
            if bag_full or self.item_for(snapshot, stock, requested_goal, project) is not None:
                clerk = next((obj for obj in world['objects'] if obj[2] == 'SPRITE_CLERK'), None)
                if clerk and clerk[0] == 0:
                    targets.append((map_id, 2, clerk[1]))
        if targets:
            return SupplyPlan(Goal('restock', 'Restock supplies',
                                   'Buy useful balls and medicine with a cash reserve', tuple(targets), 'left', True))
        self.restocking = False
        if legendary and dict(snapshot.items).get(ITEMS['ULTRA_BALL'], 0) < 5 and not dict(snapshot.items).get(ITEMS['MASTER_BALL']):
            return SupplyPlan(Goal('collect_plan', 'Plan another expedition',
                                   'Earn supplies before another legendary attempt'), True,
                              'Need money or bag space for legendary capture supplies')
        return SupplyPlan(goal, bool(legendary))

    def step(self, snapshot, screen, kind, goal_key, project):
        stock = DATA['marts'].get(WORLD.get(snapshot.map, {}).get('name'), [])
        if kind == 'shop':
            self.selling = ((self.selling and len(snapshot.items) > 15) or len(snapshot.items) >= 18
                            or self.raising_funds(snapshot))
            if self.selling and (self.fund_index(snapshot) if self.raising_funds(snapshot)
                                 else self.sale_index(snapshot)) is not None:
                return MenuDecision(select(screen, 1), 'Sell spare valuables to cover the Safari Zone entry fee'
                                    if self.raising_funds(snapshot) else
                                    'Sell spare TMs and Nuggets to make room for story items')
            self.selling = False
            self.item = self.item_for(snapshot, stock, goal_key, project)
            self.buying = self.item is not None
            prepared = not self.buying and legendary_project(project) and ITEMS['ULTRA_BALL'] in stock
            return MenuDecision(select(screen, 0) if self.buying else tap('b'),
                                'Restock balls and medicine while keeping a cash reserve', bool(prepared))
        if kind == 'quantity':
            return MenuDecision(tap('a') if self.buying or self.selling else tap('b'))
        if kind == 'list':
            if self.selling:
                index = self._sale_choice(snapshot)
                if index is None:
                    self.selling = False
                    return MenuDecision(tap('b'))
                return MenuDecision(select(screen, index, scroll=True))
            if self.buying:
                self.item = self.item_for(snapshot, stock, goal_key, project)
                if self.item is None:
                    self.buying = False
                    return MenuDecision(tap('b'))
                return MenuDecision(select(screen, stock.index(self.item), scroll=True))
            return MenuDecision(tap('b'))
        raise ValueError(f'Unsupported shop menu: {kind}')
