"""Obtain prize partners with earned money and native Game Corner menus."""
from dataclasses import dataclass
import re

from .menus import MAX_STEPS, SLOT_MAX_STEPS, choose
from .quests import room_for_gift


def prizes(game):
    if game == 'crystal':
        return [(63, 100, 'GOLDENROD'), (104, 800, 'GOLDENROD'), (202, 1500, 'GOLDENROD'),
                (25, 2222, 'CELADON'), (137, 5555, 'CELADON'), (246, 8888, 'CELADON')]
    return [(63, 200, 'GOLDENROD'), (27 if game == 'gold' else 23, 700, 'GOLDENROD'),
            (147, 2100, 'GOLDENROD'), (122, 3333, 'CELADON'), (133, 6666, 'CELADON'),
            (137, 9999, 'CELADON')]


def journey(policy, snapshot, Goal):
    choices = [row for row in prizes(policy.data.game) if row[0] not in snapshot.owned]
    if not choices:
        return None
    species, price, city = choices[0]
    policy.collection['prize'] = [species, price, city]
    if policy.data.items['COIN_CASE'] not in dict(snapshot.items):
        return policy.person(snapshot, 'collection_coin_case', 'Collect the Coin Case',
                             'GOLDENROD_UNDERGROUND', 'GoldenrodUndergroundCoinCase')
    if snapshot.coins < price:
        if snapshot.coins > 9949:
            return Goal('collection_slots', 'Finish earning coins for the prize partner',
                        'CELADON_GAME_CORNER', 11, 6, 'right')
        required = min(9950, (price + 49) // 50 * 50) - snapshot.coins
        if snapshot.money < required * 20 + 5000:
            policy.collection.setdefault('funding', snapshot.hall_of_fame_count + 1)
            return None
        return policy.person(snapshot, 'collection_coins', 'Buy coins for the prize partner',
                             'GOLDENROD_GAME_CORNER', 'GoldenrodGameCornerCoinVendorScript')
    room = room_for_gift(policy, snapshot, Goal)
    if room:
        return room
    if city == 'CELADON':
        return Goal('collection_prize', 'Receive the Game Corner prize partner',
                    'CELADON_GAME_CORNER_PRIZE_ROOM', 4, 2, 'up')
    return policy.person(snapshot, 'collection_prize', 'Receive the Game Corner prize partner',
                         'GOLDENROD_GAME_CORNER', 'GoldenrodGameCornerPrizeMonVendorScript')


def arrive(policy, snapshot):
    key = policy.goal.key
    if key not in {'collection_coins', 'collection_prize', 'collection_slots'}:
        return None
    species, price, _ = policy.collection['prize']
    if key == 'collection_coins':
        policy.menu = Coins(price)
    elif key == 'collection_prize':
        policy.menu = Prize(species)
    else:
        policy.menu = Slots(price)
    return 'a'


# A Game Corner task that makes no visible progress is lost. It ends with `failure` set so the
# policy can hand it to the stuck path instead of pressing the same button for hours.
IDLE_STEPS = 120
SLOT_IDLE_STEPS = 240
SLOT_STEPS = SLOT_MAX_STEPS
VENDOR_STEPS = MAX_STEPS
COIN_CASE_FULL = 9999
SLOT_FLOOR = 9900


def watch(menu, key, idle_limit, limit):
    """Count one decision. True means the task has stopped making progress and has been failed."""
    menu.steps += 1
    key = str(key)
    menu.idle = 0 if key != menu.mark else menu.idle + 1
    menu.mark = key
    if not menu.failure and (menu.idle > idle_limit or menu.steps > limit):
        reason = 'no change for %d steps' % menu.idle if menu.idle > idle_limit else 'over %d steps' % limit
        menu.failure = 'The %s task made no progress (%s)' % (type(menu).__name__, reason)
    return bool(menu.failure)


def text_box(snapshot):
    return ' '.join(' '.join(row.strip('┌┐└┘─│ ') for row in snapshot.tiles[12:]).split())


@dataclass
class Coins:
    target: int
    exiting: bool = False
    steps: int = 0
    idle: int = 0
    mark: str = ''
    failure: str = ''

    def step(self, snapshot, mem):
        if watch(self, (snapshot.coins, snapshot.money, snapshot.text), IDLE_STEPS, VENDOR_STEPS):
            return None
        self.exiting |= snapshot.coins >= self.target or snapshot.coins > 9949 or snapshot.money < 1000
        if self.exiting:
            return 'b' if '┌' in snapshot.tiles[12] or 'CANCEL' in snapshot.text else None
        if 'CANCEL' in snapshot.text and '1000' in snapshot.text:
            amount = 500 if self.target - snapshot.coins >= 500 and snapshot.coins <= 9499 and snapshot.money >= 10000 else 50
            rows = snapshot.tiles
            target = next((i for i, row in enumerate(rows) if re.search(rf'(?<!\d){amount}\s*:', row)), None)
            cursor = next((i for i, row in enumerate(rows) if '▶' in row), None)
            if target is not None and cursor is not None:
                return 'a' if target == cursor else 'down' if target > cursor else 'up'
        return 'a'


@dataclass
class Prize:
    species: int
    exiting: bool = False
    steps: int = 0
    idle: int = 0
    mark: str = ''
    failure: str = ''

    def step(self, snapshot, mem):
        if watch(self, (len(snapshot.owned), snapshot.text), IDLE_STEPS, VENDOR_STEPS):
            return None
        self.exiting |= self.species in snapshot.owned
        if self.exiting:
            return 'b' if '┌' in snapshot.tiles[12] or 'CANCEL' in snapshot.text else None
        if 'YES' in snapshot.text and 'NO' in snapshot.text:
            return choose(snapshot.tiles, 'YES', exact=True) or 'a'
        if 'CANCEL' in snapshot.text:
            return choose(snapshot.tiles, snapshot.data.species[self.species]['name'].upper()) or 'b'
        return 'a'


@dataclass
class Slots:
    """Play one slot machine until the prize budget is reached or the credits fall too low.

    Every machine in the Game Corner runs the same state machine, whatever reel layout it draws:
    bet menu (B backs out), "Start!" while the reels spin (each A stops one reel and B does
    nothing), a result box that needs A to advance, then "Play again?" (B means NO). Leaving
    therefore means stopping the reels, not pressing B, and the task fails if the credits and the
    box text stop changing.
    """
    target: int
    exiting: bool = False
    steps: int = 0
    idle: int = 0
    mark: str = ''
    failure: str = ''

    def step(self, snapshot, mem):
        box = text_box(snapshot)
        if watch(self, (snapshot.coins, box), SLOT_IDLE_STEPS, SLOT_STEPS):
            return None
        self.exiting |= snapshot.coins >= min(self.target, COIN_CASE_FULL) or snapshot.coins < SLOT_FLOOR
        question = 'YES' in snapshot.text and 'NO' in snapshot.text
        if question:
            if self.exiting:
                # "Play again?" is the only question a machine asks. Anything else is declined too.
                return choose(snapshot.tiles, 'NO', exact=True) or 'b'
            return choose(snapshot.tiles, 'YES', exact=True) or 'a'
        if not self.exiting:
            return 'a'
        if 'Bet how many' in box:
            return 'b'
        if 'Start!' in box:
            # The reels are spinning and wait for A. B does nothing here.
            return 'a'
        if not (mem and mem.byte('wScriptRunning')) and '┌' not in snapshot.tiles[12]:
            return None
        return 'b'
