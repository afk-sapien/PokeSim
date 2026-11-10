"""Action shortcuts for Red, Blue, Yellow, Gold, Silver and Crystal.

Each class is a :class:`Shortcut`: build it with the request, then call
``step(memory, ui)`` once per input, or pass it to ``run`` with a ControllerPort.
Party slots, move slots and box positions are zero based.
"""
from __future__ import annotations

from ..gen1 import (BIT_STRENGTH_ACTIVE, W_BADGES, W_CUR_MAP, W_CURRENT_BOX, W_STATUS_FLAGS1, W_WALK_BIKE_SURF_STATE,
                    W_WHICH_POKEMON)
from ..gen1_ui import read_battler, read_screen
from . import gen2ui
from .items import (GEN1_FIELD_MOVES, GEN1_HM_MOVES, GEN2_FIELD_MOVES, GEN2_HM_MOVES, gen2_pocket, generation,
                    item_kind, item_names, key_item, tm_number)
from .machine import NO_RESPONSE, Abort, Choose, Done, Shortcut, StopReason
from .screens import fly_destination, menu_rows, normalize

BICYCLE, POKE_FLUTE, ITEMFINDER, COIN_CASE = 0x06, 0x49, 0x47, 0x45
# Gen 2 item IDs with effects the shortcuts watch for.
GEN2_BICYCLE, GEN2_ITEMFINDER = 0x07, 0x37
GEN2_POCKET_NUMBER = {'items': 0, 'balls': 1, 'key': 2, 'tms_hms': 3}
# wPlayerState values while surfing (Gen 2).
GEN2_SURFING = (4, 8)
W_MAP_PAL_OFFSET = 0xD35D
W_PLAYER_SELECTED_MOVE = 0xCCDC
W_PLAYER_MON_NUMBER = 0xCC2F
W_ITEM_QUANTITY = 0xCF96
W_ITEM_LIST = 0xCF7B
W_PARTY_COUNT = 0xD163
W_BOX_COUNT = 0xDA80
W_IS_IN_BATTLE = 0xD057


def identity(mon):
    return mon['species'], mon['trainer_id'], tuple(mon['dvs']), mon['nick']


def _slot(value, name, high):
    if type(value) is not int or not 0 <= value < high:
        raise ValueError(f'{name} must be an integer from 0 through {high - 1}')
    return value


def _count(value, name='quantity', high=99):
    if type(value) is not int or not 1 <= value <= high:
        raise ValueError(f'{name} must be an integer from 1 through {high}')
    return value


BAG_SLOTS = 20
PC_ITEM_SLOTS = 50
# Gen 2 pocket capacities (items, balls, key items) and the item PC.
GEN2_POCKET_SLOTS = {'items': 20, 'balls': 12, 'key': 25, 'tms_hms': 57}
GEN2_PC_ITEM_SLOTS = 50


class GameShortcut(Shortcut):
    """Shared validation and the generation-neutral memory reads the actions use."""

    def validate(self, obs):
        self.check(obs)

    # Memory, by generation ----------------------------------------------------
    def battle_mode(self, obs=None):
        """0 outside battle, 1 in a wild battle, 2 in a trainer battle."""
        obs = obs or self.obs
        return obs.memory.byte('wBattleMode') if self.gen == 2 else obs.memory[W_IS_IN_BATTLE]

    def active_slot(self, obs=None):
        obs = obs or self.obs
        return obs.memory.byte('wCurBattleMon') if self.gen == 2 else obs.memory[W_PLAYER_MON_NUMBER]

    def quantity_counter(self, obs=None):
        obs = obs or self.obs
        return obs.memory.byte('wItemQuantityChange') if self.gen == 2 else obs.memory[W_ITEM_QUANTITY]

    def current_box_count(self, obs=None):
        obs = obs or self.obs
        if self.gen == 2:
            return min(gen2ui.box_count(obs.raw, self.version), 20)
        return min(obs.memory[W_BOX_COUNT], 20)

    def party_count(self, obs=None):
        obs = obs or self.obs
        if self.gen == 2:
            return min(obs.memory.byte('wPartyCount'), 6)
        return min(obs.memory[W_PARTY_COUNT], 6)

    def map_id(self, obs=None):
        obs = obs or self.obs
        if self.gen == 2:
            return obs.memory.byte('wMapGroup'), obs.memory.byte('wMapNumber')
        return obs.memory[W_CUR_MAP]

    def pockets(self, obs=None):
        return gen2ui.read_pockets((obs or self.obs).raw, self.version)

    def is_key_item(self, item):
        return key_item(item, self.version)

    def check_room(self):
        """Refuse when the bag cannot take ``self.amount`` more of ``self.item_id``."""
        if self.before + self.amount > 99:
            raise Abort('That would hold more than 99. No input sent.', cleanup=False)
        if self.before:
            return
        if self.gen == 2:
            pocket = gen2_pocket(self.item_id, self.version)
            if pocket == 'tms_hms':
                return
            if len(self.pockets()[pocket]) >= GEN2_POCKET_SLOTS[pocket]:
                raise Abort(f'The {pocket} pocket is full. No input sent.', cleanup=False)
        elif len(self.bag()) >= BAG_SLOTS:
            raise Abort('The bag is full. No input sent.', cleanup=False)

    def check(self, obs):
        """Subclass refusals before any input."""

    def guard_party(self, slot, target):
        party = self.party()
        if slot >= len(party) or identity(party[slot]) != target:
            raise Abort('Party changed before the requested selection. Stopped.')

    def text_has(self, *markers):
        words = normalize(self.obs.text)
        return any(marker in words for marker in markers)

    def need_screen(self, *screens, what):
        if self.obs.screen not in screens:
            raise Abort(f'{self.label} starts at {what}. No input sent.', cleanup=False)

    label = 'This shortcut'

    def no_effect(self):
        if self.refusal:
            raise Abort(f'The game refused: {self.refusal}', reason=StopReason.GAME_REFUSED)
        raise Abort('Requested selection returned without a confirmed effect. No second use attempted.',
                    reason=StopReason.NO_EFFECT)

    def commit_wait(self, stay, limit=120, patience=12):
        """After the committing press, pass text and prompts until the effect is seen.

        Leaving for a screen outside ``stay``, a refusal message, or ``patience``
        idle steps on a ``stay`` screen ends the flow without a second attempt.
        """
        self.committed = True
        idle = 0
        for _ in range(limit):
            screen = self.obs.screen
            if screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            elif screen in ('yes_no', 'switch_prompt'):
                answer = self.prompt_answer(self.obs)
                if answer is None and self.details.get('pending') == 'nickname':
                    # The game asks for a nickname only after a catch.
                    raise Abort(self.success_outcome() + ' Stopped at the nickname prompt for the caller to answer.',
                                cleanup=False, completed=True, reason=StopReason.PROMPT, **self.details)
                if answer is None:
                    raise Abort('Stopped at a game prompt the shortcut does not answer.', completed=False,
                                reason=StopReason.PROMPT)
                yield Choose(answer)
            elif screen == 'move_list' and isinstance(self.learn_choice(), int):
                yield from self.pick_move(self.learn_choice(), learn=True)
            elif screen in stay:
                idle += 1
                if self.refusal or idle > patience:
                    self.no_effect()
                # On the overworld an A press would talk, read a sign or offer SURF.
                yield 'a' if self.obs.ready and screen != 'overworld' else None
            else:
                self.no_effect()
        raise Abort(NO_RESPONSE)

    def open_bag(self, item=None):
        """Open the bag. In Gen 2, also turn to the pocket that holds ``item``."""
        if self.obs.battle:
            yield from self.to_battle_menu()
            yield from self.choose('ITEM', then=('bag',))
        elif self.obs.screen != 'bag':
            yield from self.open_pause()
            yield from self.choose('ITEM', then=('bag',))
        if self.gen == 2 and item is not None:
            yield from self.turn_pocket(item)

    def turn_pocket(self, item):
        """Gen 2: press left or right until the pack shows the pocket that holds ``item``."""
        target = GEN2_POCKET_NUMBER[gen2_pocket(item, self.version)]
        for _ in range(8):
            if not (yield from self.until_screen('bag', limit=20, press_text=False)):
                raise Abort('The pack did not open. Stopped.')
            here = self.obs.memory.byte('wCurPocket')
            if here == target:
                # Let the pocket finish drawing before moving the cursor.
                yield None
                return
            yield 'right' if (target - here) % 4 <= 2 else 'left'
            yield from self.until(lambda obs: obs.screen == 'bag' and obs.memory.byte('wCurPocket') != here,
                                  limit=10, press_text=False)
        raise Abort('The pack did not turn to the item pocket. Stopped.')

    def open_party(self):
        if self.obs.battle:
            # After a faint the party screen can open under "Which PKMN?" text. B there
            # only bounces back to that text, so wait for the screen to finish drawing.
            for _ in range(40):
                if self.obs.screen not in ('dialogue', 'transition'):
                    break
                if self.forced_switch(self.obs):
                    yield None
                else:
                    yield from self.text_or_wait()
            if self.obs.screen == 'party':
                return
            if self.obs.screen == 'switch_prompt':
                yield from self.choose('YES', then=('party',))
                return
            yield from self.to_battle_menu()
            yield from self.choose('PKMN', then=('party',))
            return
        if self.obs.screen == 'party':
            return
        yield from self.open_pause()
        yield from self.choose('POKéMON', then=('party',))

    def bag_index(self, item):
        if self.gen == 2:
            entries = self.pockets()[gen2_pocket(item, self.version)]
            for index, (entry, _) in enumerate(entries):
                if entry == item:
                    return index
            raise Abort('Requested item disappeared. Stopped.')
        for index, (entry, _) in enumerate(self.bag()):
            if entry == item:
                return index
        raise Abort('Requested item disappeared. Stopped.')

    def set_quantity(self, quantity, top=None):
        """In a quantity box, press up or down until the amount is ``quantity``, then A.

        ``top`` is the box maximum. The box wraps from 1 to ``top``, so a large amount
        is reached by pressing down when that is shorter.
        """
        stuck = 0
        for _ in range(240):
            if self.obs.screen != 'quantity':
                yield None
                stuck += 1
                if stuck > 10:
                    raise Abort('Quantity box did not open. Stopped.')
                continue
            here = self.quantity_counter()
            if here == quantity:
                yield 'a'
                return
            if top and here < quantity and quantity - here > here + top - quantity:
                yield 'down'
            else:
                yield 'up' if here < quantity else 'down'
        raise Abort(NO_RESPONSE)

    def resolve_item(self, item):
        if isinstance(item, int):
            return item
        wanted = normalize(item)
        labels = {key: value for key, value in self.labels.items()}
        names = {int(key): (value.get('name') if isinstance(value, dict) else value) for key, value in labels.items()
                 if str(key).isdigit()}
        if not names:
            try:
                names = item_names(self.obs.raw, self.version)
            except (TypeError, IndexError, KeyError, ValueError):
                names = {}
        matches = [key for key, name in names.items() if isinstance(name, str) and normalize(name) == wanted]
        if len(matches) != 1:
            raise Abort(f'Unknown item name {item!r}. Pass an item ID or labels. No input sent.', cleanup=False)
        return matches[0]


class UseItem(GameShortcut):
    """Use one item from the bag. See docs/shortcuts.md for every supported kind."""

    kind = 'use_item'
    label = 'use_item'

    def __init__(self, item, target=None, move=None, *, forget_move=None, **options):
        if isinstance(item, bool) or not isinstance(item, (int, str)) or (isinstance(item, int)
                                                                           and not 1 <= item <= 255):
            raise ValueError('item must be an item ID from 1 through 255 or an item name')
        if isinstance(item, str) and not normalize(item):
            raise ValueError('item name is empty')
        if target is not None:
            _slot(target, 'Party slot', 6)
        if move is not None:
            _slot(move, 'Move slot', 4)
        if forget_move is not None and forget_move != 'keep':
            _slot(forget_move, 'forget_move', 4)
        if isinstance(item, int):
            needs = item_kind(item, options.get('version')).target
            if needs in ('party', 'move') and target is None:
                raise ValueError('This item needs a party slot target')
            if needs == 'move' and move is None:
                raise ValueError('This item needs a move slot')
            if needs == 'none' and target is not None:
                raise ValueError('This item does not take a party slot')
        super().__init__(**options)
        self.item = item
        self.target = target
        self.move = move
        self.forget_move = forget_move
        self.before = None
        self.committed = False

    def learn_choice(self):
        return self.forget_move

    def result_fields(self):
        consumed = False
        if self.before is not None and self.obs is not None:
            consumed = self.quantity(self.item_id) < self.before
        return {'party_slot': None if self.target is None else self.target + 1,
                'item_id': self.item_id if isinstance(getattr(self, 'item_id', None), int) else self.item,
                'item_consumed': consumed}

    def check(self, obs):
        self.item_id = item = self.resolve_item(self.item)
        kind = self.item_info = item_kind(item, self.version)
        self.before = self.quantity(item)
        if not self.before:
            raise Abort('Requested item is not in the bag. No input sent.', cleanup=False)
        if kind.target in ('party', 'move') and self.target is None:
            raise Abort('This item needs a party slot target. No input sent.', cleanup=False)
        if kind.target == 'move' and self.move is None:
            raise Abort('This item needs a move slot. No input sent.', cleanup=False)
        if obs.battle and not kind.battle:
            raise Abort(f'This item ({kind.kind}) cannot be used in battle. No input sent.', cleanup=False)
        if not obs.battle and not kind.field:
            reason = kind.note or ('battle only' if kind.battle else 'not usable')
            raise Abort(f'This item ({kind.kind}) cannot be used here: {reason}. No input sent.', cleanup=False)
        if kind.wild_only and self.battle_mode(obs) != 1:
            raise Abort('This item works only in wild battles. No input sent.', cleanup=False)
        party = self.party()
        if kind.kind == 'ball' and self.current_box_count(obs) >= 20 and (self.gen == 1 or len(party) >= 6):
            raise Abort('The current PC box is full, so the game refuses balls. No input sent.', cleanup=False)
        if self.target is not None:
            if self.target >= len(party):
                raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
            self.target_id = identity(party[self.target])
            self.target_before = dict(party[self.target])
            mon = party[self.target]
            if mon.get('egg'):
                raise Abort('Items cannot be used on an Egg. No input sent.', cleanup=False)
            if kind.target == 'move' and (self.move >= 4 or not mon['moves'][self.move]):
                raise Abort('Move slot is empty. No input sent.', cleanup=False)
            if kind.kind in ('tm', 'hm'):
                moves = [move for move in mon['moves'] if move]
                if len(moves) == 4 and self.forget_move is None:
                    raise Abort('Target knows four moves. Pass forget_move (a move slot, or "keep"). '
                                'No input sent.', cleanup=False)
                hm_moves = GEN2_HM_MOVES if self.gen == 2 else GEN1_HM_MOVES
                if isinstance(self.forget_move, int) and mon['moves'][self.forget_move] in hm_moves:
                    raise Abort('HM moves cannot be forgotten. No input sent.', cleanup=False)
        self.state_before = {'bike': self.walk_state(obs), 'map': self.map_id(obs)}
        self.details['item_kind'] = kind.kind

    def effect(self, obs):
        if self.quantity(self.item_id, obs) < self.before:
            return True
        if not self.committed:
            return False
        kind = self.item_info.kind
        words = normalize(obs.text)
        if kind == 'ball' and ('WASCAUGHT' in words or 'GOTCHA' in words):
            # Gen 2 takes the ball from the pack only after the catch messages and the nickname prompt.
            self.details['caught'] = True
            return True
        if self.target is not None:
            party = self.party(obs)
            if self.target < len(party) and identity(party[self.target]) == self.target_id:
                mon = party[self.target]
                if kind == 'rare-candy' and mon['level'] > self.target_before['level']:
                    return True
                if kind in ('tm', 'hm') and tuple(mon['moves']) != tuple(self.target_before['moves']):
                    return True
        if self.item_id == (GEN2_BICYCLE if self.gen == 2 else BICYCLE):
            return self.walk_state(obs) != self.state_before['bike']
        if kind == 'fishing':
            return ('NIBBLE' in words or 'BITE' in words or 'NOTHINGHERE' in words
                    or (obs.battle and obs.screen != 'bag'))
        if self.gen == 2:
            if self.item_id == GEN2_ITEMFINDER:
                return 'ITEMFINDER' in words
            return (self.item_info.note == 'prints a message' and obs.screen == 'dialogue' and bool(words)
                    and not self.refusal)
        if self.item_id == POKE_FLUTE:
            return 'PLAYEDTHE' in words or 'WOKEUP' in words
        if self.item_id == ITEMFINDER:
            return 'ITEMFINDER' in words
        if self.item_id == COIN_CASE:
            return obs.screen == 'dialogue' and words.startswith('COINS')
        return False

    def success_outcome(self):
        if self.item_info.kind == 'fishing':
            words = normalize(' '.join(self.recent))
            if 'NOTEVENANIBBLE' in words or 'LOOKSLIKETHERE' in words:
                return 'Used the rod. Nothing bit.'
            return 'Used the rod. Something bit.'
        if self.details.get('caught'):
            return 'Threw the ball and caught the Pokemon.'
        return 'Used the requested item.'

    def no_effect(self):
        if self.forget_move == 'keep' and 'DIDNOTLEARN' in normalize(' '.join(self.recent)):
            raise Abort('Kept the old moves as requested. The machine was not used.', reason=StopReason.NO_EFFECT)
        super().no_effect()

    def cast_wait(self):
        """Screens a targetless item rests on before its effect shows, and how long it may rest.

        A rod closes the bag and casts on the overworld. Its message prints only after the cast,
        about two seconds later on Gen 2.
        """
        if self.item_info.kind == 'fishing':
            return {'stay': ('bag', 'item_action', 'overworld'), 'patience': 90}
        return {'stay': ('bag', 'item_action')}

    def walk_state(self, obs):
        if self.gen == 2:
            return obs.memory.byte('wPlayerState')
        return obs.memory[W_WALK_BIKE_SURF_STATE]

    def flow(self):
        if self.gen == 2:
            yield from self.flow2()
            return
        kind = self.item_info
        yield from self.open_bag()
        # Battle items and the Bicycle act on the bag's A press, with no USE/TOSS menu.
        self.committed = kind.target == 'none' and (self.obs.battle or self.item_id == BICYCLE)
        yield from self.pick_list(self.bag_index(self.item_id))
        if self.item_id != BICYCLE:
            # Outside battle the bag asks USE or TOSS. Battle goes straight on.
            yield from self.until_screen('item_action', 'item_target', 'party', 'dialogue', 'yes_no', limit=8,
                                         press_text=False)
            if self.obs.screen == 'item_action':
                self.committed = kind.target == 'none'
                yield from self.choose('USE')
        if kind.target == 'none':
            yield from self.commit_wait(**self.cast_wait())
            return
        if kind.kind in ('tm', 'hm'):
            for _ in range(40):
                if self.obs.screen in ('item_target', 'party'):
                    break
                if self.obs.screen == 'yes_no':
                    yield from self.choose('YES')
                elif self.obs.screen in ('dialogue', 'transition', 'unknown', 'item_action'):
                    yield from self.text_or_wait()
                else:
                    self.no_effect()
        elif not (yield from self.until_screen('item_target', 'party', limit=30)):
            self.no_effect()
        yield from self.pick_target()

    def pick_target(self):
        self.guard_party(self.target, self.target_id)
        self.committed = True
        yield from self.pick_party(self.target)
        if self.item_info.target == 'move':
            if not (yield from self.until_screen('move_list', limit=20, press_text=False)):
                self.no_effect()
            yield from self.pick_move(self.move)
        yield from self.commit_wait(stay=('item_target', 'party', 'move_list'))

    def flow2(self):
        """Gen 2: every pack item opens a USE menu, in battle too. TMs ask to teach first."""
        kind = self.item_info
        yield from self.open_bag(self.item_id)
        yield from self.pick_list(self.bag_index(self.item_id))
        if not (yield from self.until_screen('item_action', limit=10, press_text=False)):
            self.no_effect()
        self.committed = kind.target == 'none'
        yield from self.choose('USE')
        if kind.target == 'none':
            yield from self.commit_wait(**self.cast_wait())
            return
        for _ in range(40):
            screen = self.obs.screen
            if screen in ('item_target', 'party'):
                break
            if screen == 'yes_no' and kind.kind in ('tm', 'hm'):
                yield from self.choose('YES')
            elif screen in ('dialogue', 'transition', 'unknown', 'item_action', 'bag'):
                if self.refusal:
                    self.no_effect()
                yield from self.text_or_wait()
            else:
                self.no_effect()
        else:
            self.no_effect()
        yield from self.pick_target()


class SwitchPokemon(GameShortcut):
    """In battle, send out a party member. Outside battle, move it to the party lead."""

    kind = 'switch_pokemon'
    label = 'switch_pokemon'

    def __init__(self, slot, **options):
        _slot(slot, 'Party slot', 6)
        super().__init__(**options)
        self.slot = slot

    def result_fields(self):
        return {'party_slot': self.slot + 1, 'item_id': None, 'item_consumed': False}

    def check(self, obs):
        party = self.party()
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        self.target_id = identity(party[self.slot])
        if party[self.slot].get('egg') and obs.battle:
            raise Abort('An Egg cannot battle. No input sent.', cleanup=False)
        if obs.battle and (not party[self.slot]['hp'] or self.active_slot(obs) == self.slot):
            raise Abort('Requested Pokemon is fainted or already active. No input sent.', cleanup=False)
        if not obs.battle and self.slot == 0:
            raise Abort('Requested Pokemon is already the lead. No input sent.', cleanup=False)
        self._forced = obs.battle and obs.screen == 'party'

    def effect(self, obs):
        if obs.battle:
            return self.active_slot(obs) == self.slot
        party = self.party(obs)
        return bool(party) and identity(party[0]) == self.target_id

    def success_outcome(self):
        return 'Switched to the requested Pokemon.'

    def flow(self):
        battle = self.obs.battle
        yield from self.open_party()
        self.guard_party(self.slot, self.target_id)
        yield from self.pick_party(self.slot)
        if not (yield from self.until_screen('party_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('SWITCH')
        if battle:
            yield from self.commit_wait(stay=('party', 'party_action'))
            return
        if not (yield from self.until_screen('party', limit=10, press_text=False)):
            self.no_effect()
        yield from self.pick_party(0)
        yield from self.commit_wait(stay=('party',))


class ReorderParty(GameShortcut):
    """Swap two party members outside battle with the party menu's SWITCH."""

    kind = 'reorder_party'
    label = 'reorder_party'

    def __init__(self, first, second, **options):
        _slot(first, 'first', 6)
        _slot(second, 'second', 6)
        if first == second:
            raise ValueError('Slots must differ')
        super().__init__(**options)
        self.first, self.second = first, second

    def result_fields(self):
        return {'slots': [self.first + 1, self.second + 1]}

    def check(self, obs):
        if obs.battle:
            raise Abort('Party order changes only outside battle. Use switch_pokemon in battle. No input sent.',
                        cleanup=False)
        party = self.party()
        if max(self.first, self.second) >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        self.ids = identity(party[self.first]), identity(party[self.second])

    def effect(self, obs):
        party = self.party(obs)
        return (max(self.first, self.second) < len(party) and identity(party[self.first]) == self.ids[1]
                and identity(party[self.second]) == self.ids[0])

    def success_outcome(self):
        return 'Swapped the two party members.'

    def flow(self):
        yield from self.open_party()
        self.guard_party(self.first, self.ids[0])
        yield from self.pick_party(self.first)
        if not (yield from self.until_screen('party_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('SWITCH', then=('party',))
        yield from self.pick_party(self.second)
        yield from self.commit_wait(stay=('party',))


class ChooseMove(GameShortcut):
    """Pick a move from FIGHT in battle. Done when the turn starts.

    FIGHT can start the turn without the move list: when no move has PP (Struggle),
    and when the battler is locked into its turn (asleep, frozen, trapped, charging,
    thrashing or biding). Then the result is completed with ``forced`` set to
    ``'struggle'`` or ``'locked'``, since the turn the caller asked for started.
    """

    kind = 'choose_move'
    label = 'choose_move'
    # Observations off the battle menus that mark a turn FIGHT started by itself.
    FORCED_AFTER = 4

    def __init__(self, slot, **options):
        _slot(slot, 'Move slot', 4)
        super().__init__(**options)
        self.slot = slot
        self.committed = False

    def result_fields(self):
        return {'move_slot': self.slot + 1}

    def check(self, obs):
        if not obs.battle:
            raise Abort('Not in battle. No input sent.', cleanup=False)
        if obs.screen not in ('battle_menu', 'move_menu'):
            raise Abort('choose_move starts at the battle menu or the move menu. No input sent.', cleanup=False)
        battler = self.battler(obs)
        self.move_id = battler['moves'][self.slot]
        if not self.move_id:
            raise Abort('Move slot is empty. No input sent.', cleanup=False)
        self.no_pp = not any(battler['pp'][i] for i, move in enumerate(battler['moves']) if move)
        if not battler['pp'][self.slot] and not self.no_pp:
            raise Abort('That move has no PP left. No input sent.', cleanup=False)
        if (self.gen == 2 and obs.memory.byte('wPlayerDisableCount')
                and obs.memory.byte('wDisabledMove') == self.move_id):
            raise Abort('That move is disabled. No input sent.', cleanup=False)
        self.details['move_id'] = self.move_id

    def battler(self, obs):
        if self.gen == 2:
            return {'moves': list(obs.memory.read('wBattleMonMoves', 4)),
                    'pp': [value & 63 for value in obs.memory.read('wBattleMonPP', 4)]}
        return read_battler(obs.memory)

    def selected(self, obs):
        if self.gen == 2:
            return (obs.memory.byte('wCurPlayerMove') == self.move_id
                    and obs.memory.byte('wCurMoveNum') == self.slot)
        return obs.memory[W_PLAYER_SELECTED_MOVE] == self.move_id

    def effect(self, obs):
        if self.details.get('forced'):
            return False
        return self.committed and obs.screen not in ('move_menu', 'battle_menu') and self.selected(obs)

    def success_outcome(self):
        forced = self.details.get('forced')
        if forced == 'struggle':
            return 'No move has PP, so FIGHT used Struggle.'
        if forced == 'locked':
            return 'FIGHT started the turn without the move list (the battler is locked into its turn).'
        return 'Chose the requested move.'

    def flow(self):
        if self.obs.screen == 'battle_menu':
            before_battler = self.battler(self.obs) if self.gen == 1 else None
            yield from self.choose('FIGHT')
            away = 0
            saw_turn_text = False
            for _ in range(40):
                if self.obs.screen == 'move_menu':
                    break
                # Battle text off the battle menu means FIGHT started the turn by itself.
                away = away + 1 if self.obs.screen != 'battle_menu' and self.obs.text.strip() else 0
                saw_turn_text = saw_turn_text or away > 0
                # A short automatic turn may return before four observations.
                # A blocking label selector may consume the entire brief turn.
                battler_changed = before_battler is not None and self.battler(self.obs) != before_battler
                returned_from_turn = (saw_turn_text or battler_changed) and self.obs.screen == 'battle_menu'
                if away >= self.FORCED_AFTER or returned_from_turn:
                    self.committed = True
                    self.details['forced'] = 'struggle' if self.no_pp else 'locked'
                    settled = yield from self.settle()
                    if self.obs.screen != 'move_menu':
                        return self.success(settled)
                    # The move list opened late after all.
                    self.committed = False
                    del self.details['forced']
                    break
                yield None
        if self.obs.screen != 'move_menu':
            raise Abort('FIGHT did not open the move menu. Stopped.')
        yield from self.move_index(self.slot + 1, self.menu_y)
        self.committed = True
        yield 'a'
        yield from self.commit_wait(stay=('move_menu',), limit=20)


class RunAway(GameShortcut):
    """Choose RUN in a wild battle. Done when the battle ends or the game says you can't escape."""

    kind = 'run_away'
    label = 'run_away'

    def result_fields(self):
        return {'escaped': self.obs is not None and not self.obs.battle and self.effect_seen}

    def check(self, obs):
        if not obs.battle:
            raise Abort('Not in battle. No input sent.', cleanup=False)
        if self.battle_mode(obs) == 2:
            raise Abort('There is no running from a trainer battle. No input sent.', cleanup=False)
        self.committed = False

    def effect(self, obs):
        return self.committed and (not obs.battle or 'CANTESCAPE' in normalize(obs.text))

    def success_outcome(self):
        if self.obs is not None and not self.obs.battle:
            return 'Got away safely.'
        return 'Could not escape. The battle continues.'

    def flow(self):
        yield from self.to_battle_menu()
        self.committed = True
        yield from self.choose('RUN')
        yield from self.commit_wait(stay=('battle_menu',), limit=40)


# Text that shows a Gen 2 field move took effect.
GEN2_FIELD_MARKERS = {'CUT': 'USEDCUT', 'FLASH': 'BLINDINGFLASH', 'WHIRLPOOL': 'USEDWHIRLPOOL',
                      'WATERFALL': 'USEDWATERFALL', 'ROCKSMASH': 'USEDROCKSMASH', 'HEADBUTT': 'DIDAHEADBUTT'}


class FieldMove(GameShortcut):
    """Use a field move from the party menu outside battle.

    Gen 1: CUT, SURF, STRENGTH, FLASH and FLY. Gen 2 adds WHIRLPOOL, WATERFALL,
    ROCK SMASH and HEADBUTT.
    """

    kind = 'use_field_move'
    label = 'use_field_move'

    def __init__(self, move, slot, destination=None, **options):
        moves = GEN2_FIELD_MOVES if generation(options.get('version')) == 2 else GEN1_FIELD_MOVES
        if not isinstance(move, str) or normalize(move) not in moves:
            raise ValueError('move must be one of ' + ', '.join(moves))
        _slot(slot, 'Party slot', 6)
        self.move = normalize(move)
        if self.move == 'FLY' and (not isinstance(destination, str) or not normalize(destination)):
            raise ValueError('FLY needs a destination town name')
        super().__init__(**options)
        self.slot = slot
        self.destination = destination
        self.committed = False

    def result_fields(self):
        return {'move': self.move, 'party_slot': self.slot + 1}

    def check(self, obs):
        if obs.battle:
            raise Abort('Field moves work only outside battle. No input sent.', cleanup=False)
        party = self.party()
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        move_id, badge = (GEN2_FIELD_MOVES if self.gen == 2 else GEN1_FIELD_MOVES)[self.move]
        if party[self.slot].get('egg') or move_id not in party[self.slot]['moves']:
            raise Abort('That Pokemon does not know the move. No input sent.', cleanup=False)
        badges = obs.memory.byte('wJohtoBadges') if self.gen == 2 else obs.memory[W_BADGES]
        if badge is not None and not badges >> badge & 1:
            raise Abort('The badge for this move is missing. No input sent.', cleanup=False)
        self.target_id = identity(party[self.slot])
        if self.gen == 2:
            self.before = {'state': obs.memory.byte('wPlayerState'), 'bike': obs.memory.byte('wBikeFlags'),
                           'map': self.map_id(obs)}
            return
        self.before = {'surf': obs.memory[W_WALK_BIKE_SURF_STATE], 'strength': obs.memory[W_STATUS_FLAGS1] & 1 << BIT_STRENGTH_ACTIVE,
                       'map': obs.memory[W_CUR_MAP], 'pal': obs.memory[W_MAP_PAL_OFFSET]}

    def effect(self, obs):
        if not self.committed:
            return False
        words = normalize(obs.text)
        memory = obs.memory
        if self.gen == 2:
            if self.move == 'SURF':
                return memory.byte('wPlayerState') in GEN2_SURFING and self.before['state'] not in GEN2_SURFING
            if self.move == 'STRENGTH':
                return bool(memory.byte('wBikeFlags') & 1) and not self.before['bike'] & 1
            if self.move == 'FLY':
                return self.map_id(obs) != self.before['map'] and obs.screen == 'overworld'
            return GEN2_FIELD_MARKERS[self.move] in words
        if self.move == 'CUT':
            return 'HACKEDAWAY' in words
        if self.move == 'SURF':
            return memory[W_WALK_BIKE_SURF_STATE] == 2 and self.before['surf'] != 2
        if self.move == 'STRENGTH':
            return bool(memory[W_STATUS_FLAGS1] & 1 << BIT_STRENGTH_ACTIVE) and not self.before['strength']
        if self.move == 'FLASH':
            return 'BLINDINGFLASH' in words
        return memory[W_CUR_MAP] != self.before['map'] and obs.screen == 'overworld'

    def success_outcome(self):
        return f'Used {self.move}.'

    def flow(self):
        yield from self.open_party()
        self.guard_party(self.slot, self.target_id)
        yield from self.pick_party(self.slot)
        if not (yield from self.until_screen('party_action', limit=10, press_text=False)):
            self.no_effect()
        if self.move != 'FLY':
            self.committed = True
            yield from self.choose(self.move)
            yield from self.commit_wait(stay=('party', 'party_action'))
            return
        yield from self.choose('FLY')
        if not (yield from self.until_screen('fly_map', limit=20)):
            self.no_effect()
        seen = []
        for _ in range(16):
            if self.gen == 2:
                name = gen2ui.fly_destination(self.obs.memory)
            else:
                name = fly_destination(read_screen(self.obs.memory))
            if normalize(name) == normalize(self.destination):
                self.committed = True
                yield 'a'
                yield from self.commit_wait(stay=('fly_map', 'overworld'), limit=90, patience=40)
                return
            if name in seen:
                break
            seen.append(name)
            yield 'up'
            yield from self.until(lambda obs: obs.screen == 'fly_map', limit=4, press_text=False)
        where = 'a visited town in this region' if self.gen == 2 else 'a visited town'
        raise Abort(f'Destination is not {where}. Choices: ' + ', '.join(seen) + '.')


class TossItem(GameShortcut):
    """Toss ``quantity`` of an item from the bag outside battle."""

    kind = 'toss_item'
    label = 'toss_item'

    def __init__(self, item, quantity=1, **options):
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError('item must be an item ID or name')
        _count(quantity)
        super().__init__(**options)
        self.item, self.amount = item, quantity

    def result_fields(self):
        return {'item_id': getattr(self, 'item_id', self.item), 'quantity': self.amount}

    def check(self, obs):
        if obs.battle:
            raise Abort('Items can be tossed only outside battle. No input sent.', cleanup=False)
        self.item_id = self.resolve_item(self.item)
        self.before = self.quantity(self.item_id)
        if not self.before:
            raise Abort('Requested item is not in the bag. No input sent.', cleanup=False)
        if self.is_key_item(self.item_id):
            raise Abort('That item is too important to toss. No input sent.', cleanup=False)
        if self.amount > self.before:
            raise Abort(f'Only {self.before} in the bag. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.quantity(self.item_id, obs) <= self.before - self.amount

    def success_outcome(self):
        return f'Tossed {self.amount}.'

    def flow(self):
        yield from self.open_bag(self.item_id)
        yield from self.pick_list(self.bag_index(self.item_id))
        yield from self.until_screen('item_action', limit=8, press_text=False)
        yield from self.choose('TOSS')
        yield from self.set_quantity(self.amount, top=self.before)
        if not (yield from self.until_screen('yes_no', limit=20)):
            self.no_effect()
        yield from self.choose('YES')
        yield from self.commit_wait(stay=('bag', 'item_action'))


class MartTrade(GameShortcut):
    """Buy or sell at a Poke Mart. Starts and ends at the BUY/SELL/QUIT menu."""

    default_steps = 900

    def __init__(self, item, quantity=1, **options):
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError('item must be an item ID or name')
        _count(quantity)
        super().__init__(**options)
        self.item, self.amount = item, quantity

    def result_fields(self):
        return {'item_id': getattr(self, 'item_id', self.item), 'quantity': self.amount}

    def check(self, obs):
        self.need_screen('mart', what='the mart BUY/SELL/QUIT menu (talk to the clerk first)')
        self.item_id = self.resolve_item(self.item)
        self.before = self.quantity(self.item_id)


class BuyItem(MartTrade):
    kind = 'buy_item'
    label = 'buy_item'

    def check(self, obs):
        super().check(obs)
        self.check_room()

    def effect(self, obs):
        return self.quantity(self.item_id, obs) >= self.before + self.amount

    def success_outcome(self):
        return f'Bought {self.amount}.'

    def stock(self):
        memory = self.obs.memory
        if self.gen == 2:
            count = min(memory.byte('wCurMartCount'), 20)
            return [item for item in memory.read('wCurMartItems', count) if item != 0xFF]
        stock = []
        for index in range(1, 20):
            entry = memory[W_ITEM_LIST + index]
            if entry == 0xFF:
                break
            stock.append(entry)
        return stock

    def flow(self):
        yield from self.choose('BUY')
        if not (yield from self.until_screen('mart_list', limit=40)):
            raise Abort('BUY did not open the shop list. Stopped.')
        stock = self.stock()
        if self.item_id not in stock:
            raise Abort('This mart does not sell that item.')
        yield from self.pick_list(stock.index(self.item_id))
        yield from self.set_quantity(self.amount, top=99)
        if not (yield from self.until_screen('yes_no', limit=20)):
            self.no_effect()
        yield from self.choose('YES')
        yield from self.commit_wait(stay=('mart_list',))


class SellItem(MartTrade):
    kind = 'sell_item'
    label = 'sell_item'

    def check(self, obs):
        super().check(obs)
        if not self.before:
            raise Abort('Requested item is not in the bag. No input sent.', cleanup=False)
        if self.amount > self.before:
            raise Abort(f'Only {self.before} in the bag. No input sent.', cleanup=False)
        if self.is_key_item(self.item_id):
            raise Abort('Key items and HMs cannot be sold. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.quantity(self.item_id, obs) <= self.before - self.amount

    def success_outcome(self):
        return f'Sold {self.amount}.'

    def flow(self):
        yield from self.choose('SELL')
        if not (yield from self.until_screen('bag', limit=40)):
            raise Abort('SELL did not open the bag. Stopped.')
        if self.gen == 2:
            yield from self.turn_pocket(self.item_id)
        yield from self.pick_list(self.bag_index(self.item_id))
        yield from self.set_quantity(self.amount, top=self.before)
        if not (yield from self.until_screen('yes_no', limit=20)):
            self.no_effect()
        yield from self.choose('YES')
        yield from self.commit_wait(stay=('bag',))


class PCShortcut(GameShortcut):
    """Start at the PC menu (BILL's PC, your PC, LOG OFF) or the matching PC submenu."""

    submenu = 'bills_pc'
    submenu_row = 0

    def open_submenu(self):
        if self.obs.screen == self.submenu:
            return
        if self.gen == 2:
            labels = [label for label, _ in self.obs.extra.get('choices', [])]
        else:
            labels = [row['text'] for row in menu_rows(self.obs.memory, read_screen(self.obs.memory)) if row['text']]
        if len(labels) <= self.submenu_row:
            raise Abort('PC menu is not readable. No input sent.', cleanup=False)
        yield Choose(labels[self.submenu_row])
        for _ in range(40):
            if self.obs.screen == self.submenu:
                return
            # Gen 1 leaves the PC menu visible behind this acknowledgment.
            # A port without stack readiness therefore still classifies it as PC.
            # BILL's PC waits after each of its two lines.
            if (self.gen == 1 and self.obs.screen == 'pc'
                    and normalize(self.obs.text).endswith(('ACCESSEDMYPC', 'ACCESSEDITEMSTORAGESYSTEM',
                                                           'ACCESSEDBILLSPC', 'ACCESSEDSOMEONESPC',
                                                           'ACCESSEDPOKEMONSTORAGESYSTEM'))):
                yield 'a'
            else:
                yield from self.text_or_wait()
        if self.obs.screen != self.submenu:
            raise Abort('The PC did not open. Stopped.')

    def check(self, obs):
        what = "BILL's PC" if self.submenu == 'bills_pc' else "your PC's item menu"
        self.need_screen('pc', self.submenu, what=f'the PC menu or {what}')
        self.check_pc(obs)

    def check_pc(self, obs):
        pass

    def box_count(self, obs=None):
        return self.current_box_count(obs)


class DepositPokemon(PCShortcut):
    kind = 'deposit_pokemon'
    label = 'deposit_pokemon'

    def __init__(self, slot, **options):
        _slot(slot, 'Party slot', 6)
        super().__init__(**options)
        self.slot = slot

    def result_fields(self):
        return {'party_slot': self.slot + 1}

    def check_pc(self, obs):
        party = self.party()
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        if len(party) == 1:
            raise Abort("You can't deposit the last Pokemon. No input sent.", cleanup=False)
        if self.gen == 2 and not any(mon['hp'] and not mon.get('egg') for i, mon in enumerate(party) if i != self.slot):
            raise Abort('No other Pokemon could battle after this deposit, so the game refuses. No input sent.',
                        cleanup=False)
        if self.gen == 2 and gen2ui.holds_mail(party[self.slot]):
            raise Abort('The Pokemon holds mail. Remove it first. No input sent.', cleanup=False)
        if self.box_count() >= 20:
            raise Abort('The current box is full. No input sent.', cleanup=False)
        self.target_id = identity(party[self.slot])
        self.before = (self.party_count(), self.box_count())

    def effect(self, obs):
        return self.party_count(obs) == self.before[0] - 1 and self.box_count(obs) == self.before[1] + 1

    def success_outcome(self):
        return 'Deposited the Pokemon in the current box.'

    def flow(self):
        yield from self.open_submenu()
        yield from self.choose('DEPOSIT PKMN')
        if not (yield from self.until_screen('pc_party', limit=40)):
            self.no_effect()
        self.guard_party(self.slot, self.target_id)
        yield from self.pick_list(self.slot)
        if not (yield from self.until_screen('pc_mon_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('DEPOSIT')
        yield from self.commit_wait(stay=('pc_party', 'pc_mon_action'))


class BoxShortcut(PCShortcut):
    def __init__(self, position, **options):
        _slot(position, 'Box position', 20)
        super().__init__(**options)
        self.position = position

    def result_fields(self):
        return {'box_position': self.position + 1}

    def check_pc(self, obs):
        if self.position >= self.box_count():
            raise Abort('No Pokemon at that box position (only the current box is reachable). No input sent.',
                        cleanup=False)
        self.before = (self.party_count(), self.box_count())


class WithdrawPokemon(BoxShortcut):
    kind = 'withdraw_pokemon'
    label = 'withdraw_pokemon'

    def check_pc(self, obs):
        super().check_pc(obs)
        if self.party_count() >= 6:
            raise Abort('The party is full. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.party_count(obs) == self.before[0] + 1 and self.box_count(obs) == self.before[1] - 1

    def success_outcome(self):
        return 'Withdrew the Pokemon to the party.'

    def flow(self):
        yield from self.open_submenu()
        yield from self.choose('WITHDRAW PKMN')
        if not (yield from self.until_screen('pc_box', limit=40)):
            self.no_effect()
        yield from self.pick_list(self.position)
        if not (yield from self.until_screen('pc_mon_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('WITHDRAW')
        yield from self.commit_wait(stay=('pc_box', 'pc_mon_action'))


class ReleasePokemon(BoxShortcut):
    kind = 'release_pokemon'
    label = 'release_pokemon'

    def __init__(self, position, *, allow_release=False, **options):
        if allow_release is not True:
            raise ValueError('Releasing is permanent. Pass allow_release=True to release a Pokemon.')
        super().__init__(position, **options)

    def effect(self, obs):
        return self.box_count(obs) == self.before[1] - 1

    def success_outcome(self):
        return 'Released the Pokemon.'

    def prompt_answer(self, obs):
        words = normalize(' '.join(self.recent[-2:] + [obs.text]))
        if 'ONCERELEASED' in words or 'GONEFOREVER' in words:
            return 'YES'
        return super().prompt_answer(obs)

    def check_pc(self, obs):
        super().check_pc(obs)
        if self.gen == 2:
            mons = gen2ui.box_mons(obs.raw, self.version)
            if self.position < len(mons) and mons[self.position]['egg']:
                raise Abort('Eggs cannot be released. No input sent.', cleanup=False)
            if self.position < len(mons) and gen2ui.holds_mail(mons[self.position]):
                raise Abort('The Pokemon holds mail. Remove it first. No input sent.', cleanup=False)

    def flow(self):
        yield from self.open_submenu()
        if self.gen == 2:
            yield from self.choose('WITHDRAW PKMN')
            if not (yield from self.until_screen('pc_box', limit=40)):
                self.no_effect()
            yield from self.pick_list(self.position)
            if not (yield from self.until_screen('pc_mon_action', limit=10, press_text=False)):
                self.no_effect()
            yield from self.choose('RELEASE')
            if not (yield from self.until_screen('yes_no', limit=10, press_text=False)):
                self.no_effect()
            if 'RELEASE' not in normalize(self.obs.text):
                raise Abort('Unexpected prompt before release. Stopped.')
            self.committed = True
            yield from self.choose('YES')
            yield from self.commit_wait(stay=('pc_box',))
            return
        yield from self.choose('RELEASE PKMN')
        if not (yield from self.until_screen('pc_box', limit=40)):
            self.no_effect()
        yield from self.pick_list(self.position)
        yield from self.commit_wait(stay=('pc_box',))


class ItemPCShortcut(PCShortcut):
    submenu = 'players_pc'
    submenu_row = 1

    def __init__(self, item, quantity=1, **options):
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError('item must be an item ID or name')
        _count(quantity)
        super().__init__(**options)
        self.item, self.amount = item, quantity

    def result_fields(self):
        return {'item_id': getattr(self, 'item_id', self.item), 'quantity': self.amount}

    def pc_items(self, obs=None):
        if self.gen == 2:
            return self.pockets(obs)['pc']
        memory = (obs or self.obs).memory
        count = min(memory[0xD53A], 50)
        raw = [memory[0xD53B + i] for i in range(count * 2)]
        return [(raw[i], raw[i + 1]) for i in range(0, len(raw), 2) if raw[i] not in (0, 0xFF)]

    def pc_quantity(self, item, obs=None):
        return sum(qty for entry, qty in self.pc_items(obs) if entry == item)

    def pick_quantity(self):
        if self.is_key_item(self.item_id):
            return
        yield from self.set_quantity(self.amount, top=self.top)


class DepositItem(ItemPCShortcut):
    kind = 'deposit_item'
    label = 'deposit_item'

    def check_pc(self, obs):
        self.item_id = self.resolve_item(self.item)
        self.before = self.quantity(self.item_id)
        self.top = self.before
        if not self.before:
            raise Abort('Requested item is not in the bag. No input sent.', cleanup=False)
        if self.amount > self.before or (self.is_key_item(self.item_id) and self.amount != 1):
            raise Abort(f'Only {self.before} in the bag. No input sent.', cleanup=False)
        if self.gen == 2 and tm_number(self.item_id, self.version):
            raise Abort('TMs and HMs stay in the pack. No input sent.', cleanup=False)
        stored = self.pc_quantity(self.item_id)
        if stored + self.amount > 99:
            raise Abort('The PC would hold more than 99. No input sent.', cleanup=False)
        if not stored and len(self.pc_items()) >= (GEN2_PC_ITEM_SLOTS if self.gen == 2 else PC_ITEM_SLOTS):
            raise Abort('The item PC is full. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.quantity(self.item_id, obs) <= self.before - self.amount

    def success_outcome(self):
        return f'Stored {self.amount} in the PC.'

    def flow(self):
        yield from self.open_submenu()
        yield from self.choose('DEPOSIT ITEM')
        if not (yield from self.until_screen('bag', limit=40)):
            self.no_effect()
        if self.gen == 2:
            yield from self.turn_pocket(self.item_id)
        yield from self.pick_list(self.bag_index(self.item_id))
        yield from self.pick_quantity()
        yield from self.commit_wait(stay=('bag',))


class WithdrawItem(ItemPCShortcut):
    kind = 'withdraw_item'
    label = 'withdraw_item'

    def check_pc(self, obs):
        self.item_id = self.resolve_item(self.item)
        stored = self.top = self.pc_quantity(self.item_id)
        self.before = self.quantity(self.item_id)
        if not stored:
            raise Abort('That item is not stored in the PC. No input sent.', cleanup=False)
        if self.amount > stored or (self.is_key_item(self.item_id) and self.amount != 1):
            raise Abort(f'Only {stored} stored in the PC. No input sent.', cleanup=False)
        self.check_room()

    def effect(self, obs):
        return self.quantity(self.item_id, obs) >= self.before + self.amount

    def success_outcome(self):
        return f'Withdrew {self.amount} from the PC.'

    def flow(self):
        yield from self.open_submenu()
        yield from self.choose('WITHDRAW ITEM')
        if not (yield from self.until_screen('pc_items', limit=40)):
            self.no_effect()
        index = next((i for i, (entry, _) in enumerate(self.pc_items()) if entry == self.item_id), None)
        if index is None:
            raise Abort('Requested item disappeared. Stopped.')
        yield from self.pick_list(index)
        yield from self.pick_quantity()
        yield from self.commit_wait(stay=('pc_items',))


class HeldItemShortcut(GameShortcut):
    """Gen 2 held items, outside battle."""

    def __init__(self, slot, **options):
        _slot(slot, 'Party slot', 6)
        super().__init__(**options)
        self.slot = slot
        self.committed = False

    def check_mon(self, obs):
        if self.gen != 2:
            raise Abort('Held items exist only in Gold, Silver and Crystal. No input sent.', cleanup=False)
        if obs.battle:
            raise Abort('Held items change only outside battle. No input sent.', cleanup=False)
        party = self.party()
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        mon = party[self.slot]
        if mon.get('egg'):
            raise Abort('An Egg cannot hold an item. No input sent.', cleanup=False)
        if gen2ui.holds_mail(mon):
            raise Abort('The Pokemon holds mail, which the shortcuts do not handle. No input sent.', cleanup=False)
        self.target_id = identity(mon)
        self.held_before = mon.get('held_item') or 0
        return mon

    def held(self, obs):
        party = self.party(obs)
        if self.slot < len(party) and identity(party[self.slot]) == self.target_id:
            return party[self.slot].get('held_item') or 0
        return None


class GiveItem(HeldItemShortcut):
    """Gen 2: give a bag item to a party member to hold, from the pack's GIVE.

    When the Pokemon already holds an item, pass ``swap=True`` to trade it back
    into the bag. Otherwise the shortcut refuses before any input.
    """

    kind = 'give_item'
    label = 'give_item'

    def __init__(self, item, slot, *, swap=False, **options):
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise ValueError('item must be an item ID or name')
        super().__init__(slot, **options)
        self.item, self.swap = item, swap is True

    def result_fields(self):
        return {'item_id': getattr(self, 'item_id', self.item), 'party_slot': self.slot + 1,
                'returned_item': getattr(self, 'held_before', 0) or None}

    def check(self, obs):
        self.check_mon(obs)
        self.item_id = self.resolve_item(self.item)
        self.before = self.quantity(self.item_id)
        if not self.before:
            raise Abort('Requested item is not in the bag. No input sent.', cleanup=False)
        kind = item_kind(self.item_id, self.version).kind
        if self.is_key_item(self.item_id) or kind in ('tm', 'hm'):
            raise Abort('This item cannot be held. No input sent.', cleanup=False)
        if kind == 'mail':
            raise Abort('Mail needs a message, which the shortcuts do not write. No input sent.', cleanup=False)
        if self.held_before:
            if not self.swap:
                raise Abort('The Pokemon already holds an item. Pass swap=True to trade it back to the bag. '
                            'No input sent.', cleanup=False)
            if self.held_before == self.item_id:
                raise Abort('The Pokemon already holds that item. No input sent.', cleanup=False)
            saved = self.item_id, self.before, getattr(self, 'amount', None)
            self.item_id, self.before, self.amount = self.held_before, self.quantity(self.held_before), 1
            try:
                self.check_room()
            finally:
                self.item_id, self.before, self.amount = saved

    def effect(self, obs):
        return self.committed and self.held(obs) == self.item_id

    def success_outcome(self):
        if self.held_before:
            return 'Gave the item and put the old one in the bag.'
        return 'Gave the item to hold.'

    def prompt_answer(self, obs):
        words = normalize(' '.join(self.recent[-2:] + [obs.text]))
        if 'ALREADYHOLDING' in words or 'SWITCHITEMS' in words:
            return 'YES' if self.swap else 'NO'
        return super().prompt_answer(obs)

    def flow(self):
        yield from self.open_bag(self.item_id)
        yield from self.pick_list(self.bag_index(self.item_id))
        if not (yield from self.until_screen('item_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('GIVE')
        if not (yield from self.until_screen('item_target', 'party', limit=40, press_text=False)):
            self.no_effect()
        self.guard_party(self.slot, self.target_id)
        self.committed = True
        yield from self.pick_party(self.slot)
        yield from self.commit_wait(stay=('item_target', 'party'))


class TakeItem(HeldItemShortcut):
    """Gen 2: take a party member's held item back into the bag, from the party menu's ITEM."""

    kind = 'take_item'
    label = 'take_item'

    def result_fields(self):
        return {'party_slot': self.slot + 1, 'item_id': getattr(self, 'held_before', None) or None}

    def check(self, obs):
        self.check_mon(obs)
        if not self.held_before:
            raise Abort('The Pokemon is not holding anything. No input sent.', cleanup=False)
        self.item_id, self.amount = self.held_before, 1
        self.before = self.quantity(self.item_id)
        self.check_room()

    def effect(self, obs):
        return self.committed and self.held(obs) == 0 and self.quantity(self.item_id, obs) > self.before

    def success_outcome(self):
        return 'Took the held item into the bag.'

    def flow(self):
        yield from self.open_party()
        self.guard_party(self.slot, self.target_id)
        yield from self.pick_party(self.slot)
        if not (yield from self.until_screen('party_action', limit=10, press_text=False)):
            self.no_effect()
        yield from self.choose('ITEM')
        if not (yield from self.until(lambda obs: 'TAKE' in {normalize(label) for label, _ in
                                                              obs.extra.get('choices', [])},
                                      limit=20, press_text=False)):
            self.no_effect()
        self.committed = True
        yield from self.choose('TAKE')
        yield from self.commit_wait(stay=('party', 'party_action', 'menu'))


# Markers of the level-up and TM learn prompts.
LEARN_MARKERS = ('TRYINGTOLEARN', 'DELETEANOLDER', 'ANOLDERMOVE', 'MAKEROOMFOR', 'CANTLEARNMORE',
                 'ABANDONLEARNING', 'STOPLEARNING', 'WHICHMOVESHOULD', 'SHOULDBEFORGOTTEN')


class LearnMove(GameShortcut):
    """Answer a learn-a-new-move prompt that is already on screen.

    ``forget`` is the move slot (0 to 3) to replace, or ``'keep'`` to keep the
    current moves. Start at the "trying to learn" text, the delete-an-older-move
    YES/NO or the move list. The learner is the party Pokemon the game is
    teaching (Gen 1 wWhichPokemon, Gen 2 wCurPartyMon). HM moves cannot be
    replaced, so asking for an HM slot is refused before any input.
    """

    kind = 'learn_move'
    label = 'learn_move'

    def __init__(self, forget, **options):
        if forget != 'keep':
            _slot(forget, 'forget', 4)
        super().__init__(**options)
        self.forget = forget
        self.committed = False

    def result_fields(self):
        return {'forget': self.forget if self.forget == 'keep' else self.forget + 1}

    def learner(self, obs):
        index = obs.memory.byte('wCurPartyMon') if self.gen == 2 else obs.memory[W_WHICH_POKEMON]
        party = self.party(obs)
        return (index, party[index]) if index < len(party) else (index, None)

    def check(self, obs):
        if obs.screen not in ('dialogue', 'yes_no', 'move_list'):
            raise Abort('learn_move starts at a learn-a-new-move prompt. No input sent.', cleanup=False)
        words = normalize(obs.text)
        if obs.screen != 'move_list' and not any(marker in words for marker in LEARN_MARKERS):
            raise Abort('No learn-a-new-move prompt is on screen. No input sent.', cleanup=False)
        index, member = self.learner(obs)
        self.details['party_slot'] = index + 1
        if member is None or self.forget == 'keep':
            self.before = None
            return
        moves = list(member['moves'])
        if not moves[self.forget]:
            raise Abort('Move slot is empty. No input sent.', cleanup=False)
        if moves[self.forget] in (GEN2_HM_MOVES if self.gen == 2 else GEN1_HM_MOVES):
            raise Abort('HM moves cannot be forgotten here. No input sent.', cleanup=False)
        self.details['forgotten_move_id'] = moves[self.forget]
        self.before = (index, moves)

    def learn_choice(self):
        # A second learn prompt after this one goes back to the caller.
        return None if self.effect_seen else self.forget

    def effect(self, obs):
        if not self.committed:
            return False
        words = normalize(obs.text)
        if self.forget == 'keep':
            return 'DIDNOTLEARN' in words
        if 'LEARNED' in words:
            return True
        if self.before is None:
            return False
        index, moves = self.before
        party = self.party(obs)
        return index < len(party) and list(party[index]['moves']) != moves

    def success_outcome(self):
        if self.forget == 'keep':
            return 'Kept the current moves.'
        return 'Forgot the requested move and learned the new one.'

    def flow(self):
        idle = 0
        for _ in range(240):
            screen = self.obs.screen
            if self.refusal:
                self.no_effect()
            if screen in ('yes_no', 'switch_prompt'):
                answer = self.prompt_answer(self.obs)
                if answer is None:
                    raise Abort('Stopped at a game prompt the shortcut does not answer.', completed=False)
                words = normalize(' '.join(self.recent[-2:] + [self.obs.text]))
                if self.forget == 'keep' and answer == 'YES' and ('ABANDON' in words or 'STOPLEARNING' in words):
                    self.committed = True
                yield Choose(answer)
            elif screen == 'move_list':
                if self.forget == 'keep':
                    yield 'b'
                    continue
                self.committed = True
                yield from self.pick_move(self.forget, learn=True)
            elif screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            else:
                idle += 1
                if idle > 12:
                    self.no_effect()
                yield None
        raise Abort(NO_RESPONSE)


class ChangeBox(PCShortcut):
    """Make ``box`` (0 based) the current box through BILL's PC. Changing a box saves the game.

    Start at the PC menu or BILL's PC. Gen 1 has 12 boxes, Gen 2 has 14.
    """

    kind = 'change_box'
    label = 'change_box'

    def __init__(self, box, **options):
        _slot(box, 'Box', 14)
        super().__init__(**options)
        if self.gen == 1:
            _slot(box, 'Box', 12)
        self.box = box
        self.committed = False

    def result_fields(self):
        return {'box': self.box + 1}

    def current_box(self, obs=None):
        obs = obs or self.obs
        if self.gen == 2:
            return obs.memory.byte('wCurBox') & 0x7F
        return obs.memory[W_CURRENT_BOX] & 0x7F

    def check_pc(self, obs):
        if self.current_box(obs) == self.box:
            raise Abort('That box is already the current box. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.committed and self.current_box(obs) == self.box

    def success_outcome(self):
        return f'Changed to box {self.box + 1}.'

    def prompt_answer(self, obs):
        text = normalize(' '.join(self.recent[-2:] + [obs.text]))
        if any(word in text for word in ('SAVE', 'CHANGEABOX', 'DATAWILLBE')):
            return 'YES'
        return super().prompt_answer(obs)

    def box_cursor(self, obs):
        if self.gen == 2:
            # The box list keeps the highlighted box number (1 based) in wMenuSelection.
            return obs.memory.byte('wMenuSelection') - 1
        return obs.memory[0xCC26]

    def labels_of(self, obs):
        if self.gen == 2:
            return {normalize(label) for label, _ in obs.extra.get('choices', [])}
        return set()

    def flow(self):
        yield from self.open_submenu()
        yield from self.choose('CHANGE BOX')
        picked = False
        idle = 0
        for _ in range(200):
            obs = self.obs
            screen = obs.screen
            if self.refusal:
                self.no_effect()
            if screen in ('yes_no', 'switch_prompt'):
                answer = self.prompt_answer(obs)
                if answer is None:
                    raise Abort('Stopped at a game prompt the shortcut does not answer.', completed=False)
                if self.gen == 2 and picked:
                    self.committed = True
                yield Choose(answer)
            elif screen == 'menu' and 'SWITCH' in self.labels_of(obs):
                yield Choose('SWITCH')
            elif screen == 'menu' and not picked:
                yield from self.move_index(self.box, self.box_cursor)
                picked = True
                if self.gen == 1:
                    self.committed = True
                yield 'a'
            elif screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            else:
                idle += 1
                if idle > 16:
                    self.no_effect()
                yield None
        raise Abort(NO_RESPONSE)


class DeleteMove(GameShortcut):
    """Gen 2: have the Move Deleter make party ``slot`` forget move ``move_slot`` (both 0 based).

    Start at the Move Deleter's greeting or the first YES/NO, after talking to him.
    The Move Deleter also deletes HM moves.
    """

    kind = 'delete_move'
    label = 'delete_move'

    def __init__(self, slot, move_slot, **options):
        _slot(slot, 'Party slot', 6)
        _slot(move_slot, 'Move slot', 4)
        super().__init__(**options)
        if self.gen != 2:
            raise ValueError('delete_move is a Gen 2 shortcut (the Move Deleter)')
        self.slot, self.move_slot = slot, move_slot
        self.committed = False

    def result_fields(self):
        return {'party_slot': self.slot + 1, 'move_slot': self.move_slot + 1}

    def check(self, obs):
        if obs.battle:
            raise Abort('Not available in battle. No input sent.', cleanup=False)
        if obs.screen not in ('dialogue', 'yes_no'):
            raise Abort("delete_move starts at the Move Deleter's greeting. No input sent.", cleanup=False)
        if 'FORGET' not in normalize(obs.text) and 'MOVEDELETER' not in normalize(obs.text):
            raise Abort("The Move Deleter's greeting is not on screen. No input sent.", cleanup=False)
        party = self.party(obs)
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        member = party[self.slot]
        if member.get('egg'):
            raise Abort('An Egg knows no moves. No input sent.', cleanup=False)
        moves = [move for move in member['moves'] if move]
        if self.move_slot >= len(moves):
            raise Abort('Move slot is empty. No input sent.', cleanup=False)
        if len(moves) == 1:
            raise Abort('That Pokemon knows only one move. No input sent.', cleanup=False)
        self.target_id = identity(member)
        self.move_id = member['moves'][self.move_slot]
        self.details['move_id'] = self.move_id

    def effect(self, obs):
        if not self.committed:
            return False
        party = self.party(obs)
        return (self.slot < len(party) and identity(party[self.slot]) == self.target_id
                and self.move_id not in party[self.slot]['moves'])

    def success_outcome(self):
        return 'The Move Deleter made the Pokemon forget the move.'

    def prompt_answer(self, obs):
        words = normalize(obs.text)
        if 'FORGET' in words:
            if 'MAKEITFORGET' in words:
                self.committed = True
            return 'YES'
        return super().prompt_answer(obs)

    def flow(self):
        idle = 0
        for _ in range(240):
            screen = self.obs.screen
            if self.refusal:
                self.no_effect()
            if screen == 'yes_no':
                answer = self.prompt_answer(self.obs)
                if answer is None:
                    raise Abort('Stopped at a game prompt the shortcut does not answer.', completed=False)
                yield Choose(answer)
            elif screen == 'party':
                self.guard_party(self.slot, self.target_id)
                yield from self.pick_party(self.slot)
            elif screen == 'move_list':
                yield from self.pick_move(self.move_slot)
            elif screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            elif screen == 'overworld' and not self.committed:
                # The Move Deleter said goodbye without a deletion.
                self.no_effect()
            else:
                idle += 1
                if idle > 12:
                    self.no_effect()
                yield None
        raise Abort(NO_RESPONSE)

# wPokegearFlags bits (Gen 2).
POKEGEAR_RADIO_CARD = 0x02
POKEGEAR_OBTAINED = 0x80
# The Poké Flute channel: wRadioTuningKnob position and the wMapMusic it plays.
POKE_FLUTE_STATION, POKE_FLUTE_MUSIC = 78, 0x40
RADIO_CARD = 3


class Radio(GameShortcut):
    """Gen 2: tune the Pokégear radio to ``station`` (a wRadioTuningKnob position) and listen.

    Starts in the overworld or the start menu and returns to the overworld. The default is
    the Poké Flute channel, which wakes a sleeping Pokémon next to the player. ``music`` is
    the wMapMusic value that proves the station plays, or None to accept the tuned knob.
    """

    kind = 'tune_radio'
    label = 'tune_radio'
    default_steps = 300

    def __init__(self, station=POKE_FLUTE_STATION, music=POKE_FLUTE_MUSIC, **options):
        if type(station) is not int or not 0 <= station <= 255:
            raise ValueError('station must be a tuning knob position from 0 through 255')
        if music is not None and (type(music) is not int or not 0 <= music <= 255):
            raise ValueError('music must be a music ID from 0 through 255 or None')
        super().__init__(**options)
        if self.gen != 2:
            raise ValueError('tune_radio is a Gen 2 shortcut (the Pokégear radio)')
        self.station, self.music = station, music
        self.tuned = False

    def result_fields(self):
        return {'station': self.station}

    def check(self, obs):
        if obs.battle:
            raise Abort('Not available in battle. No input sent.', cleanup=False)
        self.need_screen('overworld', 'pause', what='the overworld or the start menu')
        flags = obs.memory.byte('wPokegearFlags')
        if flags & (POKEGEAR_OBTAINED | POKEGEAR_RADIO_CARD) != POKEGEAR_OBTAINED | POKEGEAR_RADIO_CARD:
            raise Abort('The Pokégear has no radio card. No input sent.', cleanup=False)

    def effect(self, obs):
        return self.tuned and (self.music is None or obs.memory.byte('wMapMusic') == self.music)

    def success_outcome(self):
        return 'The radio played the requested station.'

    def after_effect(self):
        # The Pokégear is no menu the settle loop knows, so B backs out to the overworld.
        for _ in range(12):
            if self.obs.screen == 'overworld':
                settled = yield from self.settle(limit=40)
                return self.success(settled)
            yield 'b' if self.obs.screen != 'dialogue' else 'a'
        return self.success(False)

    def flow(self):
        yield from self.open_pause()
        yield Choose('POKéGEAR')
        # wPokegearCard shares its address with other menus, so it is read only once the start menu is gone.
        if not (yield from self.until(lambda obs: obs.screen != 'pause', limit=20, press_text=False)):
            raise Abort('The Pokégear did not open. Stopped.')
        for _ in range(8):
            if self.obs.memory.byte('wPokegearCard') == RADIO_CARD:
                break
            yield 'right'
            yield None
        else:
            raise Abort('The radio card did not open. Stopped.')
        for _ in range(260):
            knob = self.obs.memory.byte('wRadioTuningKnob')
            if knob == self.station:
                break
            yield 'up' if knob < self.station else 'down'
        else:
            raise Abort(NO_RESPONSE)
        self.tuned = True
        # Listen. The music changes once the station's opening plays.
        for _ in range(60):
            yield None
        self.no_effect()


class DayCare(GameShortcut):
    """Gen 2: leave party ``slot`` (0 based) at the Day Care, or take ``parent`` back with ``slot=None``.

    ``parent`` is 0 for the wBreedMon1 place (the Day-Care Man) and 1 for wBreedMon2 (the
    Day-Care Lady). Start at that person's greeting or first YES/NO, after talking to them.
    Every YES/NO is answered YES. Both directions are confirmed by species, trainer ID, DVs
    and nickname, so a look-alike from the same trainer never counts.
    """

    kind = 'day_care'
    label = 'day_care'

    def __init__(self, parent, slot=None, **options):
        _slot(parent, 'Day Care parent', 2)
        if slot is not None:
            _slot(slot, 'Party slot', 6)
        super().__init__(**options)
        if self.gen != 2:
            raise ValueError('day_care is a Gen 2 shortcut')
        self.parent, self.slot = parent, slot
        self.target_id, self.party_size = None, 0

    def result_fields(self):
        fields = {'parent': self.parent, 'action': 'withdraw' if self.slot is None else 'deposit'}
        if self.slot is not None:
            fields['party_slot'] = self.slot + 1
        return fields

    def held(self, obs):
        from ..gen2.state import read_daycare
        held = read_daycare(obs.raw, self.version)['parents'][self.parent]
        return None if held is None else (held['species'], held['trainer_id'], tuple(held['dvs']), held['nickname'])

    def check(self, obs):
        if obs.battle:
            raise Abort('Not available in battle. No input sent.', cleanup=False)
        if obs.screen not in ('dialogue', 'yes_no'):
            raise Abort("day_care starts at the Day Care person's greeting. No input sent.", cleanup=False)
        held = self.held(obs)
        party = self.party(obs)
        if self.slot is None:
            if held is None:
                raise Abort('That Day Care place is empty. No input sent.', cleanup=False)
            if len(party) >= 6:
                raise Abort('The party is full. No input sent.', cleanup=False)
            self.target_id, self.party_size = held, len(party)
            return
        if held is not None:
            raise Abort('That Day Care place is taken. No input sent.', cleanup=False)
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        if party[self.slot].get('egg'):
            raise Abort('An Egg cannot stay at the Day Care. No input sent.', cleanup=False)
        self.target_id = identity(party[self.slot])

    def effect(self, obs):
        held = self.held(obs)
        if self.slot is None:
            party = self.party(obs)
            return (held is None and len(party) > self.party_size
                    and sum(identity(mon) == self.target_id for mon in party[self.party_size:]) == 1)
        return held == self.target_id

    def success_outcome(self):
        if self.slot is None:
            return 'The Day Care returned the Pokemon.'
        return 'The Day Care took the Pokemon.'

    def prompt_answer(self, obs):
        return 'YES'

    def flow(self):
        idle = 0
        for _ in range(240):
            screen = self.obs.screen
            if self.refusal:
                self.no_effect()
            if screen == 'yes_no':
                yield Choose('YES')
            elif screen == 'party' and self.slot is not None:
                self.guard_party(self.slot, self.target_id)
                yield from self.pick_party(self.slot)
            elif screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            elif screen == 'overworld':
                # The person said goodbye without the requested change.
                self.no_effect()
            else:
                idle += 1
                if idle > 12:
                    self.no_effect()
                yield None
        raise Abort(NO_RESPONSE)


class ShowPartner(GameShortcut):
    """Gen 2: show party ``slot`` (0 based) to a person who asks to see a Pokémon.

    Start at the person's greeting or first YES/NO, after talking to them. Success is the
    event flag ``event`` (an index into wEventFlags) turning on. Every YES/NO is answered YES.
    """

    kind = 'show_partner'
    label = 'show_partner'

    def __init__(self, slot, event, **options):
        _slot(slot, 'Party slot', 6)
        if type(event) is not int or not 0 <= event < 2048:
            raise ValueError('event must be an event flag index from 0 through 2047')
        super().__init__(**options)
        if self.gen != 2:
            raise ValueError('show_partner is a Gen 2 shortcut')
        self.slot, self.event = slot, event
        self.target_id = None

    def result_fields(self):
        return {'party_slot': self.slot + 1, 'event': self.event}

    def flag(self, obs):
        return bool(obs.memory.byte('wEventFlags', self.event // 8) >> (self.event % 8) & 1)

    def check(self, obs):
        if obs.battle:
            raise Abort('Not available in battle. No input sent.', cleanup=False)
        if obs.screen not in ('dialogue', 'yes_no'):
            raise Abort("show_partner starts at the person's greeting. No input sent.", cleanup=False)
        if self.flag(obs):
            raise Abort('That event flag is already set. No input sent.', cleanup=False)
        party = self.party(obs)
        if self.slot >= len(party):
            raise Abort('Party slot is unavailable. No input sent.', cleanup=False)
        self.target_id = identity(party[self.slot])

    def effect(self, obs):
        return self.flag(obs)

    def success_outcome(self):
        return 'The person saw the Pokemon.'

    def prompt_answer(self, obs):
        return 'YES'

    def flow(self):
        idle = 0
        for _ in range(240):
            screen = self.obs.screen
            if screen == 'yes_no':
                yield Choose('YES')
            elif screen == 'party':
                self.guard_party(self.slot, self.target_id)
                yield from self.pick_party(self.slot)
            elif screen in ('dialogue', 'transition', 'unknown'):
                yield from self.text_or_wait()
            elif screen == 'overworld':
                self.no_effect()
            else:
                idle += 1
                if idle > 12:
                    self.no_effect()
                yield None
        raise Abort(NO_RESPONSE)


__all__ = ['UseItem', 'SwitchPokemon', 'ReorderParty', 'ChooseMove', 'RunAway', 'FieldMove', 'TossItem',
           'BuyItem', 'SellItem', 'DepositPokemon', 'WithdrawPokemon', 'ReleasePokemon', 'DepositItem',
           'WithdrawItem', 'GiveItem', 'TakeItem', 'LearnMove', 'ChangeBox', 'DeleteMove', 'Radio', 'DayCare',
           'ShowPartner', 'Done', 'tm_number']
