"""Obtain prize partners with earned money and native Game Corner menus."""
from dataclasses import dataclass
import re

from .menus import choose
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


@dataclass
class Coins:
    target: int
    exiting: bool = False

    def step(self, snapshot, mem):
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

    def step(self, snapshot, mem):
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
    target: int
    exiting: bool = False

    def step(self, snapshot, mem):
        self.exiting |= snapshot.coins >= self.target or snapshot.coins < 9900
        if self.exiting:
            if 'YES' in snapshot.text and 'NO' in snapshot.text:
                again = 'Play again' in snapshot.text
                return choose(snapshot.tiles, 'NO' if again else 'YES', exact=True) or 'a'
            if not mem.byte('wScriptRunning') and '┌' not in snapshot.tiles[12]:
                return None
            return 'b'
        return 'a'
