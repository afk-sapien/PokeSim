"""Resumable shortcut machines: one controller input per ``step``.

A shortcut is a small state machine. ``step(memory, ui)`` looks at the current
memory and returns exactly one of

* a button name (``'a'``, ``'b'``, ``'start'``, ``'select'``, ``'up'``, ...) to tap once,
* ``None`` to let the game run without input for a moment, or
* a :class:`Done` with the outcome, once the shortcut has finished.

The caller presses the button, advances the emulator, and calls ``step`` again
with fresh memory. Nothing is written to memory. ``run`` is the blocking wrapper
that drives a machine through a ``ControllerPort``.

Every machine refuses before its first input when the request cannot work, and
after its effect it keeps going until the game rests: the overworld (or the
menu it started from) outside battle, or the battle menu, the move menu, a
YES/NO switch prompt or the forced-switch party screen in battle. If the game
never settles within the step budget, the result is ``completed=True`` and
``settled=False``. A machine never reports success it did not observe.

Every :class:`Done` also carries a :class:`StopReason` and ``can_continue``.
The reason says why the machine stopped. ``can_continue`` says whether the game
rests at a known screen, so the caller may start another command at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from .. import gen1
from ..gen1_ui import read_screen
from ..yellow import red_layout
from . import gen2ui
from .items import generation
from .screens import (_BATTLE_MENU, continue_ready as rom_continue_ready, current_screen, menu_rows,
                      normalize, text_lines)

BUTTONS = ('a', 'b', 'start', 'select', 'up', 'down', 'left', 'right')
LISTS = ('bag', 'pc_items', 'pc_party', 'pc_box', 'mart_list')
# Menus that B closes without side effects, outside battle.
BACKABLE = ('bag', 'pause', 'party', 'party_action', 'item_action', 'item_target', 'move_list', 'menu',
            'pc_items', 'pc_party', 'pc_box', 'pc_mon_action', 'mart_list', 'quantity', 'bills_pc', 'players_pc',
            'fly_map')
STOP_OUTCOME = 'Shortcut stopped at its controller or run budget. Inspect current state before continuing.'
NO_RESPONSE = 'Menu did not respond. Stopped without repeating the requested effect.'
# Normalized text the game prints when it refuses an action.
REFUSALS = ('ISNTTHETIME', 'NOCYCLING', 'WONTHAVEANYEFFECT', 'NOTCOMPATIBLE', 'BOXISFULL', 'BLOCKEDTHEBALL',
            'DONTBEATHIEF', 'ISNTANYTHINGTO', 'NOSURFING', 'NEWBADGEREQUIRED', 'MAXEDOUT', 'CANTUSETHAT',
            'NORUNNING', 'CANTPUTAPRICE', 'TOOIMPORTANT', 'ENOUGHMONEY', 'NOROOMFOR', 'CANTCARRY',
            'NOTHINGTOSTORE', 'CANTUSEITHERE', 'NOWILLTOFIGHT', 'CANTFLYHERE',
            'NOPPLEFT', 'ALREADYOUT', 'CANTSWITCH', 'CANTTAKEANY', 'CANTSTOREANY', 'CANTCARRYANY',
            'LASTPOKMON', 'YOUCANTDEPOSIT', 'BOXISFULL', 'CANTESCAPE',
            # Gen 2 refusals.
            'ALREADYKNOWS', 'YOURLAST', 'THERESNOROOM', 'PARTYSFULL', 'NORELEASINGEGGS', 'REMOVEMAIL',
            'REMOVETHEMAIL', 'NOMOREUSABLE', 'NOTHINGTOCUT', 'CANTSURF', 'ALREADYSURFING', 'CANTBUYTHAT',
            'CANTBEHELD', 'EGGCANTHOLD', 'STORAGESPACEFULL', 'ISNTHOLDING',
            # Forgetting an HM.
            'CANTBEDELETED', 'CANTBEFORGOTTEN', 'NOTTHATMOVE')
NICKNAME_ANSWERS = ('no', 'caller')


class StopReason(str, Enum):
    """Why a shortcut stopped. The value is the string that goes into result dicts.

    Shared by every machine, so a consumer can branch on one field.
    """
    COMPLETED = 'completed'        # the requested effect happened and the game rests
    PROMPT = 'prompt'              # stopped at a game prompt left for the caller
    UNSETTLED = 'unsettled'        # the effect happened, but the screen never came to rest
    REFUSED = 'refused'            # refused before any input: bad state or arguments
    GAME_REFUSED = 'game_refused'  # the game printed a refusal
    NO_EFFECT = 'no_effect'        # inputs went out but no effect was observed
    NO_RESPONSE = 'no_response'    # a menu stopped reacting to input
    BUDGET = 'budget'              # the step budget or the controller ran out
    STOPPED = 'stopped'            # stopped for another observed reason, see the outcome
    CHOICE = 'choice'              # dialogue reached a menu or a YES/NO choice
    TEXT_END = 'text_end'          # dialogue closed and control returned to the player
    BLOCKED = 'blocked'            # the player could not step further
    BATTLE = 'battle'              # a battle started
    MAP_CHANGE = 'map_change'      # the player left the map
    DIALOGUE = 'dialogue'          # text or a menu opened while walking


STOP_REASONS = tuple(reason.value for reason in StopReason)


@dataclass(frozen=True)
class Done:
    """Final result of a shortcut. ``completed`` means the requested effect was observed.

    ``reason`` is a :class:`StopReason`. When it is left out, ``stop_reason`` derives one
    from the other fields. ``can_continue`` is True when the game rests at a known
    screen, so another command can safely start.
    """
    outcome: str
    completed: bool = False
    settled: bool = True
    details: dict = field(default_factory=dict)
    reason: StopReason | None = None

    @property
    def stop_reason(self):
        if self.reason is not None:
            return StopReason(self.reason)
        if self.completed:
            if not self.settled:
                return StopReason.UNSETTLED
            return StopReason.PROMPT if self.details.get('pending') else StopReason.COMPLETED
        if self.outcome == STOP_OUTCOME:
            return StopReason.BUDGET
        if self.outcome == NO_RESPONSE:
            return StopReason.NO_RESPONSE
        return StopReason.STOPPED

    @property
    def can_continue(self):
        return bool(self.settled)

    def as_result(self, kind, **extra):
        shortcut = {'kind': kind, 'completed': self.completed, 'settled': self.settled, **extra, **self.details,
                    'stop_reason': self.stop_reason.value, 'can_continue': self.can_continue}
        return {'outcome': self.outcome, 'shortcut': shortcut}


@dataclass(frozen=True)
class Choose:
    """Select a visible menu label. ``step`` turns this into cursor moves and one A press."""
    label: str


class Abort(Exception):
    """Stop the flow with an outcome. ``cleanup`` backs out of menus first."""

    def __init__(self, outcome, cleanup=True, completed=False, *, reason=None, **details):
        super().__init__(outcome)
        if reason is None and outcome == NO_RESPONSE:
            reason = StopReason.NO_RESPONSE
        self.done = Done(outcome, completed, True, details, reason)
        self.cleanup = cleanup


@dataclass
class Observation:
    raw: object
    memory: object
    ui: dict
    screen: str
    rows: list
    cursor: tuple | None
    battle: bool
    ready: bool | None
    words: str
    text: str
    extra: dict = field(default_factory=dict)


class Shortcut:
    """Base class. Subclasses implement ``flow`` and may override ``effect`` and ``after_effect``."""

    kind = 'shortcut'
    gen2 = False
    default_steps = 600

    def __init__(self, *, version=None, read_party=None, read_bag=None, max_steps=None, labels=None, nickname='no'):
        if nickname not in NICKNAME_ANSWERS:
            raise ValueError('nickname must be "no" (answer NO) or "caller" (stop at the prompt)')
        self.nickname = nickname
        self.version = getattr(version, 'version', version)
        self.gen = generation(self.version)
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError('max_steps must be a positive integer')
        self.max_steps = max_steps or self.default_steps
        self._read_party = read_party
        self._read_bag = read_bag
        self.labels = labels or {}
        self.steps = 0
        self.inputs = 0
        self.result = None
        self.effect_seen = False
        self.obs = None
        self.origin = None
        self.refusal = None
        self.details = {}
        self._flow = None
        self._choosing = None
        self._choose_tries = 0
        self._last_text = None
        self._stable_text = 0
        self._held = None
        self._held_waits = 0
        self._held_screen = None
        self._seen_tiles = None
        self.recent = []

    # Readers ---------------------------------------------------------------
    def party(self, obs=None):
        obs = obs or self.obs
        if self._read_party is not None:
            return list(self._read_party(obs.raw))
        if self.gen == 2:
            return gen2ui.read_party(obs.raw, self.version)
        return gen1.read_party(obs.memory)

    def bag(self, obs=None):
        obs = obs or self.obs
        if self._read_bag is not None:
            return list(self._read_bag(obs.raw))
        if self.gen == 2:
            return gen2ui.read_bag(obs.raw, self.version)
        return list(gen1.read_bag(obs.memory))

    def quantity(self, item, obs=None):
        return sum(qty for entry, qty in self.bag(obs) if entry == item)

    # Hooks -----------------------------------------------------------------
    def validate(self, obs):
        """Refuse before any input by raising Abort(..., cleanup=False)."""

    def flow(self):
        raise NotImplementedError
        yield  # pragma: no cover

    def effect(self, obs):
        """True once the requested effect is visible in memory."""
        return False

    def after_effect(self):
        settled = yield from self.settle()
        return self.success(settled)

    def success_outcome(self):
        return 'Done.'

    def result_fields(self):
        """Extra keys for the blocking result's ``shortcut`` dict."""
        return {}

    def success(self, settled=True):
        details = dict(self.details)
        if settled is True:
            return Done(self.success_outcome(), True, True, details, StopReason.COMPLETED)
        if settled == 'prompt':
            details['pending'] = self.details.get('pending', 'prompt')
            return Done(self.success_outcome() + ' Stopped at a game prompt for the caller to answer.',
                        True, True, details, StopReason.PROMPT)
        return Done(self.success_outcome() + ' The effect happened, but the screen did not settle. '
                    'Inspect current state before continuing.', True, False, details, StopReason.UNSETTLED)

    # Observation -----------------------------------------------------------
    def observe(self, memory, ui=None):
        ui = dict(ui or {})
        if self.gen == 2:
            return self._observe2(memory, ui)
        view = red_layout(memory, self.version) if generation(self.version) == 1 else memory
        screen = ui.get('screen') or current_screen(memory, version=self.version)
        ready = ui.get('continue_ready')
        if ready is None and ui.get('sp') is not None:
            ready = rom_continue_ready(memory, ui['sp'])
        tilemap = read_screen(view)
        rows = tilemap['rows']
        text = text_lines(view)
        return Observation(memory, view, ui, screen, rows, tilemap['cursor'],
                           view[0xD057] in (1, 2), ready, normalize(' '.join(rows)), text)

    def _observe2(self, memory, ui):
        view = gen2ui.View(memory, self.version)
        rows = gen2ui.rows_of(view)
        screen, extra = gen2ui.classify(view, rows)
        screen = ui.get('screen') or screen
        ready = ui.get('continue_ready')
        if not ready and ui.get('sp') is not None and gen2ui.cont_wait(memory, ui['sp']):
            ready = True
        if ready is None:
            ready = gen2ui.ready(view)
        return Observation(memory, view, ui, screen, rows, extra['cursor'], extra['battle'], ready,
                           normalize(' '.join(rows)), gen2ui.text_box(view), extra)

    # Generation-neutral reads ------------------------------------------------
    def menu_y(self, obs=None):
        """The menu cursor row (Gen 1 wCurrentMenuItem, Gen 2 wMenuCursorY)."""
        obs = obs or self.obs
        return obs.memory.byte('wMenuCursorY') if self.gen == 2 else obs.memory[0xCC26]

    def list_position(self, obs=None):
        """The highlighted entry of the list on screen, 0 based with scrolling."""
        obs = obs or self.obs
        if self.gen == 2:
            return gen2ui.list_index(obs.memory, obs.screen)
        return obs.memory[0xCC26] + obs.memory[0xCC36]

    def ready(self):
        """Whether A only continues printed text.

        A known readiness is trusted on any screen, since text can print over a menu
        that still shows its cursor. Unknown readiness presses only on a dialogue
        screen, after the text stops changing.
        """
        obs = self.obs
        if obs.ready is not None:
            return bool(obs.ready)
        return obs.screen == 'dialogue' and self._stable_text >= 2

    # Stepping --------------------------------------------------------------
    def step(self, memory, ui=None):
        """Return one button, None (wait) or a Done. See the module docstring.

        Gen 2 menus drop a press that lands while they still draw or print, so on
        Gold, Silver and Crystal a button waits until two observations in a row show
        the same tilemap (at most four waits).
        """
        if self._held is not None and self.result is None:
            self.obs = self.observe(memory, ui)
            self._track_text(self.obs)
            self.steps += 1
            if not self._settled_tiles() and self._held_waits < 4:
                self._held_waits += 1
                return None
            action, self._held = self._held, None
            if action == 'a' and self._held_screen == 'dialogue' and self.obs.screen != 'dialogue':
                # The A was for text that has since closed. On the menu that replaced it,
                # it would pick an entry.
                return None
            self.inputs += 1
            return action
        action = self._advance(memory, ui)
        if isinstance(action, Choose):
            if self._choosing is not action:
                self._choosing = action
                self._choose_tries = 0
            action = self._resolve_choose()
        if self.gen == 2 and self.obs is not None:
            settled = self._settled_tiles()
            if not settled and action in BUTTONS:
                self._held, self._held_waits, self._held_screen = action, 0, self.obs.screen
                return None
        if action in BUTTONS:
            self.inputs += 1
        return action

    def _settled_tiles(self):
        """Gen 2: whether the tilemap matches the previous observation, ignoring the blinking text arrow."""
        tiles = bytearray(self.obs.memory.tiles)
        tiles[17 * 20 + 18] = 0
        settled, self._seen_tiles = tiles == self._seen_tiles, tiles
        return settled

    def _advance(self, memory, ui):
        if self.result is not None:
            return self.result
        self.obs = obs = self.observe(memory, ui)
        self._track_text(obs)
        self.steps += 1
        if self._flow is None:
            self.origin = obs.screen
            try:
                self.validate(obs)
            except Abort as abort:
                done = abort.done
                return self._finish(done if done.reason else replace(done, reason=StopReason.REFUSED))
            self._flow = self.flow()
        if self.steps > self.max_steps:
            if self.effect_seen:
                return self._finish(self.success(False))
            return self._finish(Done(STOP_OUTCOME, False, False, dict(self.details), StopReason.BUDGET))
        if obs.screen not in ('overworld', 'transition'):
            self._note_refusal(obs)
        if not self.effect_seen and self.effect(obs):
            self.effect_seen = True
            self._choosing = None
            self._flow = self.after_effect()
        if self._choosing is not None:
            return self._choosing
        return self._next()

    def _next(self):
        while True:
            try:
                action = next(self._flow)
            except StopIteration as stop:
                done = stop.value
                if not isinstance(done, Done):
                    done = self.success(True) if self.effect_seen else Done(
                        'Requested selection returned without a confirmed effect. No second use attempted.',
                        reason=StopReason.NO_EFFECT)
                return self._finish(done)
            except Abort as abort:
                if abort.cleanup and self.inputs:
                    self._flow = self._cleanup(abort.done)
                    continue
                if self.inputs and abort.done.reason is not StopReason.PROMPT:
                    # Inputs went out and nothing backed out, so the screen is not known to rest.
                    return self._finish(replace(abort.done, settled=False))
                return self._finish(abort.done)
            return action

    def _cleanup(self, done):
        settled = yield from self.settle(limit=80, answer_prompts=False)
        if settled == 'prompt' and done.reason is None:
            # Cleanup cannot back out of a YES/NO, so report the prompt the caller now faces.
            return replace(done, reason=StopReason.PROMPT)
        return replace(done, settled=settled is not False)

    def _finish(self, done):
        if self.effect_seen and not done.completed:
            done = replace(done, completed=True)
        if done.reason is None and not done.completed and not self.inputs:
            done = replace(done, reason=StopReason.REFUSED)
        if done.reason is None:
            done = replace(done, reason=done.stop_reason)
        self.result = done
        return done

    def _track_text(self, obs):
        if obs.text and obs.screen not in ('overworld', 'transition') and (not self.recent
                                                                          or self.recent[-1] != obs.text):
            self.recent = (self.recent + [obs.text])[-4:]
        text = tuple(obs.rows[12:18])
        if obs.screen == 'dialogue' and text == self._last_text:
            self._stable_text += 1
        else:
            self._stable_text = 0
        self._last_text = text if obs.screen == 'dialogue' else None

    def _note_refusal(self, obs):
        words = normalize(obs.text)
        if any(marker in words for marker in REFUSALS) and not self.effect_seen:
            self.refusal = obs.text

    def _resolve_choose(self):
        """Turn the pending Choose into one cursor move or the confirming A press."""
        obs, label = self.obs, self._choosing.label
        self._choose_tries += 1
        if self._choose_tries > 24:
            self._choosing = None
            return self._finish(Done(f'Could not select {label}. Stopped.', False, False, dict(self.details),
                                     StopReason.NO_RESPONSE))
        cursor = tuple(obs.cursor) if obs.cursor else None
        wanted = normalize(label)
        if self.gen == 2:
            aliases = ({'POKEMON', 'PKMN'} if wanted in ('POKEMON', 'PKMN') else
                       {'ITEM', 'PACK'} if wanted in ('ITEM', 'PACK') else {wanted})
            menu = gen2ui.BATTLE_MENU.items() if obs.screen == 'battle_menu' else [
                (tile, name) for name, tile in obs.extra.get('choices', [])]
            targets = [tuple(tile) for tile, name in menu if normalize(name) in aliases]
        elif obs.screen == 'battle_menu':
            targets = [tile for tile, name in _BATTLE_MENU.items() if normalize(name) == normalize(label)]
        else:
            rows = menu_rows(obs.memory, read_screen(obs.memory))
            targets = [tuple(row['cursor']) for row in rows if normalize(row['text']) == normalize(label)
                       or (normalize(label) in ('POKEMON', 'PKMN') and normalize(row['text']) in ('POKEMON', 'PKMN'))]
        if cursor is None or len(targets) != 1:
            return None
        target = targets[0]
        if cursor == target:
            self._choosing = None
            return 'a'
        if cursor[1] != target[1]:
            return 'down' if cursor[1] < target[1] else 'up'
        return 'right' if cursor[0] < target[0] else 'left'

    # Flow helpers (generators) -------------------------------------------
    def wait(self, count=1):
        for _ in range(count):
            yield None

    def text_or_wait(self):
        yield 'a' if self.ready() else None

    def until(self, predicate, limit=40, press_text=True):
        """Wait (pressing A on continue-only text) until predicate(obs). Returns whether it held."""
        for _ in range(limit):
            if predicate(self.obs):
                return True
            if press_text:
                yield from self.text_or_wait()
            else:
                yield None
        return predicate(self.obs)

    def until_screen(self, *screens, limit=40, press_text=True):
        return (yield from self.until(lambda obs: obs.screen in screens, limit, press_text))

    def choose(self, label, then=None, limit=20):
        """Select a visible label, then wait for one of ``then`` screens."""
        yield Choose(label)
        if then:
            if not (yield from self.until_screen(*then, limit=limit, press_text=False)):
                raise Abort(f'{label} did not open the expected menu. Stopped.')

    def move_index(self, index, current, spacing_ok=True, tries=None):
        """Move a list cursor to ``index`` with up/down. ``current`` reads the cursor index."""
        stuck = 0
        for _ in range(tries or 120):
            if self.list_wait():
                yield 'a'
                continue
            here = current(self.obs)
            if here == index:
                return True
            yield 'down' if here < index else 'up'
            if current(self.obs) == here:
                stuck += 1
                if stuck >= 8:
                    raise Abort(NO_RESPONSE)
            else:
                stuck = 0
        return False

    def list_wait(self):
        """Whether a list stopped mid-draw at a nickname holding <CONT> (0x55) until A or B.

        Gen 1 trusts the stack when the caller passes ``sp``. Yellow draws the list off
        screen during the wait, so without ``sp`` only a wait read as dialogue counts.
        Gen 2 keeps the box list on screen, so it reads the stack when the caller
        passes ``sp`` and otherwise the blinking ▼ on a PC list.
        """
        obs = self.obs
        if self.gen == 1:
            return obs.screen == 'dialogue' and self.ready() if obs.ready is None else bool(obs.ready)
        if obs.ui.get('sp') is not None:
            return gen2ui.cont_wait(obs.raw, obs.ui['sp'])
        return obs.screen in ('pc_box', 'pc_party') and bool(obs.ready)

    def pick_list(self, index):
        """Highlight list entry ``index`` (0 based, including scroll) and press A."""
        yield from self.move_index(index, self.list_position)
        yield 'a'

    def pick_party(self, slot):
        offset = 1 if self.gen == 2 else 0
        yield from self.move_index(slot + offset, self.menu_y)
        yield 'a'

    def pick_move(self, slot, learn=False):
        """On a move list, highlight move ``slot`` (0 based) and press A.

        Gen 1 counts the forget-a-move list from 0 and the others from 1. Gen 2 counts every list from 1.
        """
        offset = 0 if learn and self.gen == 1 else 1
        yield from self.move_index(slot + offset, self.menu_y)
        yield 'a'

    def open_pause(self):
        """From the overworld or a field menu, reach the start menu."""
        for _ in range(30):
            screen = self.obs.screen
            if screen == 'pause':
                return
            if screen == 'overworld':
                yield 'start'
                yield from self.until_screen('pause', 'overworld', limit=6, press_text=False)
                if self.obs.screen == 'overworld':
                    continue
            elif screen in ('dialogue', 'transition'):
                yield from self.text_or_wait()
            elif screen in BACKABLE:
                yield 'b'
            else:
                raise Abort('Unsupported starting menu. No further input sent.', cleanup=False)
        raise Abort(NO_RESPONSE)

    def to_battle_menu(self):
        for _ in range(30):
            screen = self.obs.screen
            if screen == 'battle_menu':
                return
            if screen in ('move_menu', 'bag', 'party', 'party_action', 'item_action', 'item_target', 'menu'):
                yield 'b'
            elif screen in ('dialogue', 'transition'):
                yield from self.text_or_wait()
            else:
                raise Abort('Unsupported starting menu. No further input sent.', cleanup=False)
        raise Abort(NO_RESPONSE)

    # Settling ------------------------------------------------------------
    def resting(self, obs, seen):
        if obs.battle:
            if obs.screen in ('battle_menu', 'move_menu', 'switch_prompt'):
                return True
            return obs.screen == 'party' and self.forced_switch(obs)
        if obs.screen == 'overworld':
            return True
        return obs.screen == self.origin and self.origin in ('pause', 'mart', 'pc', 'bills_pc', 'players_pc')

    def forced_switch(self, obs):
        """In battle, the party screen rests only when the active battler fainted."""
        if self.gen == 2:
            return obs.memory.read('wBattleMonHP', 2) == b'\x00\x00'
        from ..gen1_ui import read_battler
        return read_battler(obs.memory)['hp'] == 0

    def settle(self, limit=None, answer_prompts=True):
        """Drive the game to a resting screen. Returns True, 'prompt' or False."""
        seen = set()
        stable = party_waits = 0
        budget = limit if limit is not None else max(40, self.max_steps - self.steps)
        for _ in range(budget):
            obs = self.obs
            if self.resting(obs, seen):
                stable += 1
                if stable >= 2:
                    return True
                yield None
                continue
            stable = 0
            screen = obs.screen
            if screen == 'dialogue':
                yield from self.text_or_wait()
            elif screen in ('yes_no', 'switch_prompt'):
                answer = self.prompt_answer(obs) if answer_prompts else None
                if answer is None:
                    return 'prompt'
                yield from self.choose(answer)
            elif screen == 'move_list' and answer_prompts and isinstance(self.learn_choice(), int):
                yield from self.pick_move(self.learn_choice(), learn=True)
            elif obs.battle and screen in ('party', 'item_target'):
                # Text printed over the party screen after an item or a switch.
                party_waits += 1
                if obs.ready:
                    yield 'a'
                elif obs.ready is None and party_waits % 6 == 0:
                    yield 'b'
                else:
                    yield None
            elif screen in BACKABLE:
                yield 'b'
            elif screen in ('naming',):
                return 'prompt'
            else:
                yield None
        return False

    def learn_choice(self):
        return None

    def prompt_answer(self, obs):
        """Answer YES/NO prompts that follow an effect. None stops for the caller."""
        words = normalize(' '.join(self.recent[-3:] + [obs.text]))
        if 'NICKNAME' in words:
            if self.nickname == 'caller':
                self.details['pending'] = 'nickname'
                return None
            return 'NO'
        choice = self.learn_choice()
        if 'ABANDONLEARNING' in words or 'STOPLEARNING' in words:
            return 'YES' if choice == 'keep' else None
        if 'MAKEROOMFOR' in words or 'DELETEANOLDER' in words or 'ANOLDERMOVE' in words:
            if choice == 'keep':
                return 'NO'
            if isinstance(choice, int):
                return 'YES'
            self.details['pending'] = 'learn_move'
            return None
        return None


def runner_ui(port, memory):
    """Observation dict for a ControllerPort: the port's panel and continue_ready when it has its own."""
    from ..controls import _never_ready, panel as default_panel
    ui = port.observe() or {}
    ui = dict(ui) if isinstance(ui, dict) else {}
    version = getattr(port, 'version', None)
    if generation(version) == 2:
        # Gen 2 screens always come from Core's classifier, since port panels read Gen 1 menus.
        ui.pop('screen', None)
        ui['continue_ready'] = None if port.continue_ready is _never_ready else bool(port.continue_ready())
        return ui
    if port.panel is not default_panel:
        screen = port.panel(memory, ui, port.item_labels)
        if screen in ('dialogue', 'unknown', 'transition', 'menu', 'overworld'):
            try:
                core = current_screen(memory, version=version)
            except (TypeError, IndexError, KeyError, ValueError):
                core = 'unknown'
            if core in ('quantity', 'yes_no', 'move_list', 'mart', 'mart_list', 'pc', 'bills_pc',
                        'players_pc', 'pc_items', 'pc_party', 'pc_box', 'pc_mon_action', 'fly_map',
                        'item_target') or screen == 'unknown':
                screen = core
    else:
        screen = current_screen(memory, version=version)
    ui['screen'] = screen
    ui['continue_ready'] = None if port.continue_ready is _never_ready else bool(port.continue_ready())
    return ui


def run(port, machine, **extra):
    """Drive ``machine`` to completion through ``port`` and return the blocking result dict."""
    memory = port.memory
    start = port.frame()
    while True:
        if port.stopped():
            done = machine._finish(Done(STOP_OUTCOME, False, False, dict(machine.details), StopReason.BUDGET))
            break
        ui = runner_ui(port, memory)
        # Gen 2 menus are resolved to single buttons here, since a port's choose reads Gen 1 menus.
        action = machine.step(memory, ui) if machine.gen == 2 else machine._advance(memory, ui)
        if isinstance(action, Done):
            done = action
            break
        if isinstance(action, Choose):
            machine.inputs += 1
            if not port.choose(action.label):
                done = machine._finish(Done('Controller stopped before confirming the requested effect.',
                                            False, False, dict(machine.details), StopReason.BUDGET))
                break
            continue
        if action is None:
            ok = port.send(None, 30, 0)
        else:
            if machine.gen != 2:
                machine.inputs += 1
            ok = port.send(action, 8, 24) and port.send(None, 12, 0)
        if not ok:
            done = machine._finish(Done(STOP_OUTCOME, False, False, dict(machine.details), StopReason.BUDGET))
            break
    from ..control_results import control_status
    result = done.as_result(machine.kind, **{**machine.result_fields(), **extra})
    reason = ('stopped' if port.stopped() else 'budget' if done.outcome == STOP_OUTCOME
              else 'complete' if done.completed and done.settled
              else 'unsettled' if done.completed else 'refused')
    result['control'] = control_status(machine.kind, reason, completed=done.completed,
                                       settled=done.settled, frames=port.frame() - start, inputs=machine.inputs)
    return result


def drive(machine, emulator, *, max_inputs=None, hold=8, gap=24, wait=30):
    """Run ``machine`` directly on a Core ``Emulator`` (or anything with press/release/tick/memory).

    For scripts and tests. Applications with their own input budget should call
    ``step`` themselves or use ``run`` with a ``ControllerPort``.
    """
    memory = emulator.memory
    while True:
        sp = getattr(getattr(emulator, 'register_file', None), 'SP', None)
        action = machine.step(memory, {'sp': sp} if sp is not None else None)
        if isinstance(action, Done):
            return action
        if action is None:
            emulator.tick(wait, render=False, sound=False)
        else:
            emulator.press(action)
            emulator.tick(hold, render=False, sound=False)
            emulator.release(action)
            emulator.tick(gap + 12, render=False, sound=False)
