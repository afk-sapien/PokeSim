"""Observe and act through cartridge controls for Generation II adventures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections import Counter, deque
import random
import re
from types import SimpleNamespace

from ..planning.ledger import FIELD_MOVES, LEARN_KEPT
from ..planning.losses import ace_slot
from ..planning.shadow import Shadow
from ..planning.stance import FLEE, STORY, Encounter, stance
from ..runtime.supervision import REFUSED_SHORTCUT
from .navigation import DIRS, Navigator
from pokecore.gen2.ram import Memory
from pokecore.gen2.screens import ScreenText, mask_roster
from pokecore.gen2.state import script_running
from .puzzles import push_plan
from .world import update as update_world
from .naming import Naming
from .kanto import journey as kanto_journey
from .menus import (MAX_STEPS, RADIO_MAX_STEPS, SLOT_MAX_STEPS, TASKS, Attack, Buy, ChangeBox, DayCare, FieldMove, Flee, Fly, Release,
                    Forget, Give, Lead, Learn, PutAway, Radio, Remedy, Sell, Send, ShowPartner, Storage, Take, Teach, Throw,
                    Toss, Use, UseOn, choose,
                    close_pc, menu_label, restore)

STUCK_WAITS = 40  # consecutive 24-frame waits (about 16 seconds of game time) before reporting a blocked objective
# The wPlayerSubStatus5 bit the battle engine sets while the player's Pokémon is Transformed.
SUBSTATUS_TRANSFORMED = 8
# Moves with no power of their own that use another move, which may be an attack.
BORROWED_MOVES = frozenset({'EFFECT_TRANSFORM', 'EFFECT_MIMIC', 'EFFECT_METRONOME', 'EFFECT_MIRROR_MOVE', 'EFFECT_SLEEP_TALK'})
# Rest heals with EFFECT_HEAL like Recover, then sleeps two turns. Leech Seed fails on a Grass foe.
REST, GRASS = 156, 22
# Moves that win back HP, so a foe's attacks may never knock out the Pokémon that knows one.
HEALING_MOVES = frozenset({'EFFECT_HEAL', 'EFFECT_MORNING_SUN', 'EFFECT_SYNTHESIS', 'EFFECT_MOONLIGHT',
                           'EFFECT_LEECH_SEED'})
# What long_odds answers when a catch should run and wait for a new move, member or ball.
LEAVE = 'leave'
# The bit the cartridge's loadwildmon script command sets in wBattleScriptFlags for the battle it starts.
SCRIPTED_BATTLE = 0x80


def transformed(mem, mon):
    """The active Pokémon as it fights. After Transform it has the foe's species, stats and moves.

    The party record keeps a Transformed Ditto's own Transform, so judging it by the party alone
    saw a level 100 Ditto with no attack at all.
    """
    if mem is None or mon is None or not mem.byte('wPlayerSubStatus5') & SUBSTATUS_TRANSFORMED:
        return mon
    stats = (mon.stats[0],) + tuple(mem.word(name) for name in (
        'wBattleMonAttack', 'wBattleMonDefense', 'wBattleMonSpeed', 'wBattleMonSpclAtk', 'wBattleMonSpclDef'))
    return replace(mon, species=mem.byte('wBattleMonSpecies'), moves=tuple(mem.read('wBattleMonMoves', 4)),
                   pp=tuple(value & 63 for value in mem.read('wBattleMonPP', 4)), stats=stats)


@dataclass(frozen=True)
class Action:
    button: str | None = None
    hold: int = 8
    gap: int = 16


@dataclass(frozen=True)
class Goal:
    key: str
    label: str
    map_name: str
    x: int
    y: int
    face: str | None = None
    # The goal kind the battle stance follows (planning/stance.py): story, travel, train or hunt.
    kind: str = STORY


class Policy:
    name = 'strategic'
    # The emulator's progress_events.GoalWatch, where a catch kept for an improve reason is noted.
    goal_watch = None

    def __init__(self, data, *, seed=None, starter='random'):
        self.data = data
        self.rng = random.Random(seed)
        self.starter = self.rng.choice(('chikorita', 'cyndaquil', 'totodile')) if starter == 'random' else starter
        if self.starter not in {'chikorita', 'cyndaquil', 'totodile'}:
            raise ValueError('Choose Chikorita, Cyndaquil or Totodile for this cartridge')
        self.nav = Navigator(data)
        self.decisions = 0
        self.mode = 'opening'
        # True while the last step backed out of a screen no plan owns. A checkpoint taken then
        # would bring the run back into that screen, so the emulator skips it.
        self.backing_out = False
        self.goal = None
        # The heal or supply errand the last errand decision picked, the step's journey pick, and
        # whether this step reached the errand decision.
        self.errand = None
        self.pick = None
        self.decided = False
        self.menu = None
        self.shopping = None
        self.shop_location = None
        self.talk_key, self.talk_frames = None, 0
        self.healing_map = None
        # The PC chosen last time, kept while it stays among the nearest so equal routes do not flip it.
        self.storage_pick = None
        self.completed = {}
        self.collection = {'target': None}
        # The best fighter level that lost to each boss. Store.attach keeps it in the adventure's store.
        from ..planning.losses import Losses
        self.losses = Losses()
        # The progress monitor's stand-downs and budgets, timed on ``clock``. Store.attach gives the adventure's.
        from ..runtime.supervision import Tables
        self.monitor_tables = Tables(clock=lambda: self.clock)
        # Owned one-time encounters that a walking return brought back for another capture.
        self.returned = set()
        # The party seen at this PC visit, so a member deposited at it is no spare (pcvalue.VisitTeam).
        from ..pcvalue import VisitTeam
        self.visit_team = VisitTeam()
        self.shop_offers = set()
        self.demand = {}
        self.naming = Naming(seed)
        self.learning = False
        self.refusals = {}
        # Core shortcuts the game refused, by key, with the PlayClock frame they may be tried again.
        self.blocked = {}
        # The PlayClock frame of the latest decision, which the decider passes to step. Never saved.
        self.clock = 0
        # The emulator replaces this with the store's trade preferences. Locked and offered partners are never released.
        self.trade_preferences = dict
        # And this with the store's linked adventure trainer ids (trade/partners.py), whose Pokémon may be released.
        self.trade_partners = frozenset
        self.release_cache = (None, None)
        self.rated_cache = (None, None)
        self.refused_in_row = 0
        self.result_ref = None
        self.recoveries = 0
        self.stranded = 0
        self.rescue = deque()
        # Why the wild shiny in this battle cannot be caught, read by the emulator for its notice.
        self.shiny_missed = None
        # A missing entry was left uncaught because only the upgrade slot was free and nothing may go.
        self.boxes_full = False
        # Run attempts the battle stance made: failed tries in this battle, whether one is under
        # way, and counts over the whole run that the replay audit reads.
        self.flee_tries, self.fleeing = 0, False
        self.flees = Counter()
        self.failure = None
        self.menu_ref, self.menu_steps = None, 0
        self.partner_move = None
        self.last_position = None
        self.same_position = 0
        self.interaction = None
        self.puzzle_cache = {}
        self.memory = None
        self.sp = None
        # The next activity a manager set (planning/pin.py). Never saved.
        self.pin = None
        self.resetting_puzzle = None
        self.unreachable_waits = 0
        # The arbiter's and the decide pipeline's picks beside the chain's, for the log and the replay
        # audit. Never saved.
        self.shadow = Shadow()
        # The step's decide pipeline offers (gen2/pipeline.py), the offer of the errand under way, which
        # a later step resumes, and the pipeline's pick for the trace. Never saved.
        self.ballot = None
        self.errand_offer = None
        self.pipeline_pick = None

    def state_dict(self):
        return {'starter': self.starter, 'rng': self.rng.getstate(), 'completed': self.completed, 'collection': self.collection, 'demand': self.demand, 'decisions': self.decisions,
                'naming': self.naming.state_dict(), 'learning': self.learning, 'partner_move': self.partner_move,
                'menu': {'kind': type(self.menu).__name__, 'state': asdict(self.menu)} if self.menu else None,
                'shopping': self.shopping, 'shop_location': self.shop_location, 'healing_map': self.healing_map,
                'interaction': self.interaction, 'resetting_puzzle': self.resetting_puzzle,
                'objects': {str(mid): {str(index): point for index, point in objects.items()}
                            for mid, objects in self.nav.objects.items()}}

    def load_state_dict(self, state):
        from .gamecorner import Coins, Prize, Slots
        from .npc_trades import Trade
        self.pin = None
        self.starter = state.get('starter', self.starter)
        if 'rng' in state:
            # Saved as JSON lists, so the tuples the generator wants are rebuilt.
            def tuples(value):
                return tuple(tuples(item) for item in value) if isinstance(value, (list, tuple)) else value
            self.rng.setstate(tuples(state['rng']))
        self.completed = state.get('completed', {})
        self.collection = state.get('collection', {'target': None})
        from .standdown import migrate
        migrate(self, state.get('decisions', 0))
        self.demand = {int(key): value for key, value in state.get('demand', {}).items()}
        self.decisions = state.get('decisions', 0)
        self.naming.load_state_dict(state.get('naming', {}))
        self.learning = state.get('learning', False)
        self.partner_move = state.get('partner_move')
        menu = state.get('menu')
        kinds = {**TASKS, 'Trade': Trade}
        self.menu = restore(kinds[menu['kind']], menu['state']) if menu and menu.get('kind') in kinds else None
        if menu and menu.get('kind') in {'Coins', 'Prize', 'Slots'}:
            self.menu = {'Coins': Coins, 'Prize': Prize, 'Slots': Slots}[menu['kind']](**menu['state'])
        self.shopping = tuple(state['shopping']) if state.get('shopping') else None
        self.shop_location = tuple(state['shop_location']) if state.get('shop_location') else None
        self.healing_map = state.get('healing_map')
        self.interaction = state.get('interaction')
        self.resetting_puzzle = state.get('resetting_puzzle')
        if isinstance(self.interaction, list):
            self.interaction = tuple(self.interaction)
        self.nav.objects = {int(mid): {int(index): tuple(point) for index, point in objects.items()}
                            for mid, objects in state.get('objects', {}).items()}

    STRANDED_LIMIT = 60
    MENU_STEP_LIMIT = MAX_STEPS
    MENU_STEP_LIMITS = {'Radio': RADIO_MAX_STEPS, 'Slots': SLOT_MAX_STEPS}

    def recover(self, level=1):
        """Drop every half-finished plan and press buttons that back out of unknown screens.

        Level 1 backs out with B. Level 2 mixes in directions and A from a seeded sequence, so a
        screen that B cannot leave still gets explored, and the same trouble gives the same buttons.
        """
        self.recoveries += 1
        self.menu = self.interaction = None
        self.learning = False
        self.refusals.clear()
        self.on_restore()
        if level <= 1:
            self.rescue = deque(['b', 'b', 'b'])
        else:
            rng = random.Random(self.recoveries)
            self.rescue = deque(button for _ in range(8)
                                for button in (rng.choice(('up', 'down', 'left', 'right')), 'b', rng.choice(('a', 'b'))))

    def fail(self, reason):
        """A menu task exceeded its step limit. Reset and let the emulator count the failure."""
        self.failure = reason
        self.recover(1)

    def take_failure(self):
        failure, self.failure = self.failure, None
        return failure

    def menu_step(self, snapshot, mem):
        """Run the current menu task, giving up when it takes implausibly many steps."""
        menu = self.menu
        name = type(menu).__name__
        if menu is not self.menu_ref:
            self.menu_ref, self.menu_steps = menu, 0
            if hasattr(menu, 'key') and self.blocked.get(menu.key(), -1) > self.clock:
                # The game refused this shortcut recently, so it is not tried again yet.
                return self.refused(f'The game keeps refusing the {name} shortcut')
            from .release import may_release
            if isinstance(menu, Release) and not may_release(self, snapshot, menu.box, menu.position):
                # The one release rule refuses it, as a team member or a Keep, so it waits as a refused shortcut.
                self.blocked[self.task_key(menu)] = REFUSED_SHORTCUT.until(self.clock)
                self.menu = None
                return self.refused('A release chose a Pokémon the PC values keep')
        self.menu_steps += 1
        limit = self.MENU_STEP_LIMITS.get(name, self.MENU_STEP_LIMIT)
        if self.menu_steps > limit:
            self.fail(f'The {name} menu task made no progress after {limit} steps')
            return None
        button = menu.step(snapshot, mem)
        failure = getattr(menu, 'failure', '')
        if failure:
            # A Game Corner task saw its screen stop changing and failed itself.
            self.fail(failure)
            return None
        result = getattr(menu, 'result', None)
        if result is not None and menu is not self.result_ref:
            self.result_ref = menu
            if result.completed:
                self.refused_in_row = 0
            elif getattr(menu, 'battle', False) and not isinstance(menu, Remedy) and not snapshot.in_battle:
                pass  # The battle ended under the shortcut, which is no refusal.
            elif not getattr(menu, 'box_full', False):
                self.blocked[self.task_key(menu)] = REFUSED_SHORTCUT.until(self.clock)
                if len(self.blocked) > 64:
                    self.blocked = {key: frame for key, frame in self.blocked.items() if frame > self.clock}
                self.refused(f'The game keeps refusing the {name} shortcut')
                if self.menu is not menu:
                    return None
        return button

    REFUSAL_LIMIT = 20

    @staticmethod
    def task_key(menu):
        key = getattr(menu, 'key', None)
        return key() if key else (type(menu).__name__,)

    def allowed(self, task, snapshot):
        """Whether the game has not refused this shortcut recently, and its PC list can reach the slot.

        Without the stack pointer a nickname holding a text command can stop Bill's PC list, so
        pc_list guards every release and withdrawal in that box.
        """
        if getattr(self, 'sp', None) is None and self.unlisted_box(task, snapshot):
            return False
        return self.blocked.get(self.task_key(task), -1) <= self.clock

    @staticmethod
    def unlisted_box(task, snapshot):
        from ..pc_list import gen2_unlisted_boxes
        if isinstance(task, Release):
            box = task.box
        elif isinstance(task, Storage) and task.operation != 'DEPOSIT':
            box = getattr(snapshot, 'active_box', None)
        else:
            return False
        return box in gen2_unlisted_boxes(getattr(snapshot, 'stored', ()))

    def refused(self, reason):
        """Count a refusal. Many in a row mean the plan keeps asking for something impossible."""
        self.refused_in_row += 1
        if self.refused_in_row > self.REFUSAL_LIMIT:
            self.refused_in_row = 0
            self.fail(reason)
        return None

    def on_restore(self):
        objects = self.nav.objects
        self.nav = Navigator(self.data)
        self.nav.objects = objects

    def describe(self):
        return f'strategic ({self.mode})'

    def goals(self, snapshot, query=None, every=False):
        """The goals a manager can set as the next activity, and why the list is empty. ``query`` is as
        in pin.grouped. The list keeps the picker's limit unless ``every`` asks for all of it."""
        from ..planning.pin import LIMIT
        from .collection import goal_list
        if snapshot is None or self.memory is None:
            return [], 'Not available now'
        return goal_list(self, snapshot, Memory(self.memory, self.data), Goal, query, None if every else LIMIT)

    def pin_goal(self, snapshot, key):
        """Set ``key``, a listed goal's key, as the next activity. A ValueError says why it cannot be."""
        from ..planning.pin import UNAVAILABLE, Pin
        goals, reason = self.goals(snapshot, every=True)
        match = next((goal for goal in goals if goal['key'] == key), None)
        if match is None:
            raise ValueError(reason or UNAVAILABLE.capitalize())
        self.pin = Pin(key, match['label'], started=getattr(self, 'ladder_pick', None) == key)
        return self.pin

    def unpin_goal(self):
        self.pin = None

    def drop_pin(self):
        """Drop the pin. Returns the label dropped, or None with no pin."""
        label = self.pin.label if self.pin else None
        self.pin = None
        return label

    def details(self):
        from .collection import active_target
        from .marathon import details as marathon_details
        return {'action': self.mode, 'decisions': self.decisions, 'starter': self.starter,
                'pin': self.pin.to_dict() if self.pin else None,
                'milestones': dict(self.completed), 'recoveries': self.recoveries, 'visited_tiles': len(self.nav.visits),
                'objective': {'key': self.goal.key, 'label': self.goal.label, 'reason': self.goal.label} if self.goal else {},
                'collection': {'version': self.data.game, 'dex_total': 251,
                               'phase': self.collection.get('phase', 'journey'),
                               'hunting': (active_target(self) or {}).get('species'),
                               'npc_trades': [row['index'] for row in self.collection.get('npc_trades', [])],
                               'marathon': marathon_details(self)},
                'blocked': self.unreachable_waits >= STUCK_WAITS,
                'reason': self.goal.label if self.goal else 'Start the adventure'}

    def journey(self, snapshot, mem):
        """The journey goal: the story goal, or the boss training it needs. Both are offered on the step's
        ballot, or outside a step on a ballot of their own, and the ballot's pick is the journey goal."""
        ballot = getattr(self, 'ballot', None)
        if ballot is None:
            from .pipeline import Ballot
            ballot = Ballot()
        goal = self.story(snapshot, mem)
        if goal is not None:
            ballot.offer(goal, self.story_site(), kind=self.story_kind())
        training = self.boss_training(snapshot, goal)
        if training is not None:
            ballot.offer(training, 'boss')
        return ballot.goal

    def story_site(self):
        """The site of this decision's story goal: an activity under way that holds the collection, the
        collection ladder's pick, or else the story."""
        if getattr(self, 'collection_decision', None) != self.decisions:
            return 'story'
        return 'holds' if getattr(self, 'ladder_hold', None) is not None else 'ladder'

    def story_kind(self):
        """The ladder's rung as the kind of its pick, which the audit counts frames against."""
        if self.story_site() != 'ladder':
            return None
        return getattr(self, 'ladder_rung', None)

    def story(self, snapshot, mem):
        # A saved postgame outing waits while an evolution, trade or other collection task takes
        # priority. Its battle rules resume only when the director chooses its hunting goal again.
        activity = (self.collection.get('postgame') or {}).get('activity')
        if activity:
            activity['suspended'] = True
        if snapshot.map == self.data.map_ids['POKECENTER_2F']:
            return Goal('return_from_cable', 'Return downstairs after the Cable Club', 'POKECENTER_2F', 0, 7)
        if self.collection.get('time_capsule_restore'):
            from .teams import assemble
            goal = assemble(self, snapshot, self.collection['time_capsule_restore'], Goal,
                            'Restore the adventure team after the Time Capsule')
            if goal:
                return goal
            self.collection.pop('time_capsule_restore', None)
        if self.collection.get('tower'):
            from .tower import journey
            goal = journey(self, snapshot, Goal)
            if goal:
                return goal
        if self.collection.get('contest'):
            from .contest import journey
            goal = journey(self, snapshot, Goal)
            if goal:
                return goal
        if not snapshot.event('EVENT_GOT_A_POKEMON_FROM_ELM'):
            x = {'cyndaquil': 6, 'totodile': 7, 'chikorita': 8}[self.starter]
            return Goal('starter', f'Choose {self.starter.title()}', 'ELMS_LAB', x, 4, 'up')
        self.completed.setdefault('starter', snapshot.frame)
        if not snapshot.event('EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON'):
            return Goal('mystery_egg', 'Visit Mr. Pokémon', 'MR_POKEMONS_HOUSE', 3, 6, 'up')
        self.completed.setdefault('mystery_egg', snapshot.frame)
        if not snapshot.event('EVENT_GAVE_MYSTERY_EGG_TO_ELM'):
            if not snapshot.event('EVENT_COP_IN_ELMS_LAB'):
                return Goal('officer', 'Tell the officer about the rival', 'ELMS_LAB', 4, 5)
            return Goal('deliver_egg', 'Bring the mystery egg to Elm', 'ELMS_LAB', 5, 3, 'up')
        self.completed.setdefault('deliver_egg', snapshot.frame)
        if not snapshot.badges & 1:
            return Goal('zephyr', 'Challenge Falkner', 'VIOLET_GYM', 5, 2, 'up')
        self.completed.setdefault('zephyr', snapshot.frame)
        if not snapshot.event('EVENT_GOT_TOGEPI_EGG_FROM_ELMS_AIDE'):
            from .quests import room_for_gift
            room = room_for_gift(self, snapshot, Goal)
            if room:
                return room
            return Goal('togepi', 'Receive Elm’s egg', 'VIOLET_POKECENTER_1F', 4, 4, 'up')
        self.completed.setdefault('togepi', snapshot.frame)
        if not snapshot.event('EVENT_CLEARED_SLOWPOKE_WELL'):
            if not snapshot.event('EVENT_AZALEA_TOWN_SLOWPOKETAIL_ROCKET'):
                return Goal('kurt', 'Help Kurt rescue the Slowpoke', 'KURTS_HOUSE', 3, 3, 'up')
            return Goal('slowpoke', 'Drive Team Rocket out of the well', 'SLOWPOKE_WELL_B1F', 5, 3, 'up')
        self.completed.setdefault('slowpoke', snapshot.frame)
        if not snapshot.badges & 2:
            return Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up')
        self.completed.setdefault('hive', snapshot.frame)
        if not snapshot.event('EVENT_HERDED_FARFETCHD'):
            if 'wFarfetchdPosition' in self.data.symbols:
                position = mem.byte('wFarfetchdPosition') or 1
            else:
                forest = self.data.maps[self.data.map_ids['ILEX_FOREST']]
                position = next((int(obj['script'].removeprefix('FarfetchdPosition'))
                                 for obj in forest['objects'] if obj['script'].startswith('FarfetchdPosition')
                                 and not snapshot.event(obj['event'])), 1)
            points = {1: (14, 32, 'up'), 2: (15, 24, 'down'), 3: (20, 25, 'up'),
                      4: (29, 21, 'down'), 5: (29, 31, 'left'), 6: (24, 36, 'up'),
                      7: (22, 32, 'up'), 8: (15, 28, 'down'), 9: (11, 35, 'left')}
            x, y, face = points.get(position, points[1])
            return Goal(f'farfetchd_{position}', 'Return the lost Farfetch’d', 'ILEX_FOREST', x, y, face)
        if not snapshot.event('EVENT_GOT_HM01_CUT'):
            return Goal('cut', 'Receive Cut from the charcoal maker', 'ILEX_FOREST', 5, 29, 'up')
        self.completed.setdefault('cut', snapshot.frame)
        if not snapshot.badges & 4:
            if snapshot.event('EVENT_MADE_WHITNEY_CRY'):
                return Goal('whitney_cry', 'Give Whitney a moment', 'GOLDENROD_GYM', 8, 5)
            return Goal('plain', 'Challenge Whitney', 'GOLDENROD_GYM', 8, 4, 'up')
        self.completed.setdefault('plain', snapshot.frame)
        if not snapshot.event('EVENT_GOT_SQUIRTBOTTLE'):
            if self.data.game == 'crystal':
                if not snapshot.event('EVENT_MET_FLORIA'):
                    return self.person(snapshot, 'floria', 'Ask Floria about the moving tree', 'ROUTE_36', 'Route36FloriaScript')
                if not snapshot.event('EVENT_TALKED_TO_FLORIA_AT_FLOWER_SHOP'):
                    return self.person(snapshot, 'floria_shop', 'Visit Floria at the flower shop', 'GOLDENROD_FLOWER_SHOP', 'FlowerShopFloriaScript')
            return self.person(snapshot, 'squirtbottle', 'Borrow the SquirtBottle', 'GOLDENROD_FLOWER_SHOP', 'FlowerShopTeacherScript')
        # The tree also stands again after a fled battle or a walking return.
        if not snapshot.event('EVENT_FOUGHT_SUDOWOODO'):
            return Goal('sudowoodo', 'Investigate the moving tree', 'ROUTE_36', 35, 10, 'up')
        if not snapshot.event('EVENT_ROUTE_36_SUDOWOODO'):
            # The tree stands again after a fled battle or a walking return.
            goal = self.returned_encounter(snapshot, Goal, 'Sudowoodo')
            if goal is not None:
                return goal or Goal('sudowoodo', 'Investigate the moving tree', 'ROUTE_36', 35, 10, 'up')
        self.completed.setdefault('sudowoodo', snapshot.frame)
        if self.data.game == 'crystal' and not snapshot.event('EVENT_RELEASED_THE_BEASTS'):
            if not snapshot.event('EVENT_HOLE_IN_BURNED_TOWER'):
                return Goal('burned_tower', 'Explore the Burned Tower', 'BURNED_TOWER_1F', 11, 9)
            return Goal('beasts', 'Discover the tower’s sleeping Pokémon', 'BURNED_TOWER_B1F', 10, 6)
        if self.data.game == 'crystal' and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER'):
            return self.person(snapshot, 'eusine', 'Talk with Eusine after the beasts awaken',
                               'BURNED_TOWER_B1F', 'BurnedTowerB1FEusine')
        if not snapshot.event('EVENT_GOT_HM03_SURF'):
            for name in ('NAOKO', 'SAYO', 'ZUKI', 'KUNI', 'MIKI'):
                if not snapshot.event(f'EVENT_BEAT_KIMONO_GIRL_{name}'):
                    return self.person(snapshot, f'kimono_{name.lower()}', 'Challenge the Kimono Girls',
                                       'DANCE_THEATER', 'TrainerKimonoGirl' + name.title())
            return self.person(snapshot, 'surf', 'Receive Surf', 'DANCE_THEATER', 'DanceTheaterSurfGuy')
        self.completed.setdefault('surf', snapshot.frame)
        if not snapshot.badges & 8:
            return Goal('fog', 'Challenge Morty', 'ECRUTEAK_GYM', 5, 2, 'up')
        self.completed.setdefault('fog', snapshot.frame)
        if not snapshot.event('EVENT_GOT_HM04_STRENGTH'):
            return self.person(snapshot, 'strength', 'Receive Strength', 'OLIVINE_CAFE', 'OlivineCafeStrengthSailorScript')
        partner = self.partner_goal(snapshot, 57)
        if partner:
            return partner
        if not snapshot.event('EVENT_JASMINE_EXPLAINED_AMPHYS_SICKNESS'):
            return self.person(snapshot, 'amphy', 'Help Jasmine at the lighthouse', 'OLIVINE_LIGHTHOUSE_6F', 'OlivineLighthouseJasmine')
        if not snapshot.event('EVENT_GOT_SECRETPOTION_FROM_PHARMACY'):
            return self.person(snapshot, 'medicine', 'Get medicine for Amphy', 'CIANWOOD_PHARMACY', 'CianwoodPharmacist')
        if not snapshot.badges & 32:
            if snapshot.map == self.data.map_ids['CIANWOOD_GYM']:
                entry = self.data.maps[snapshot.map]
                live = {index: (x, y) for index, x, y in snapshot.objects}
                for point, stand, face in [((3, 7), (3, 8), 'up'), ((5, 7), (5, 8), 'up'), ((4, 7), (5, 7), 'left')]:
                    index = next(i for i, obj in enumerate(entry['objects'], 1)
                                 if obj['sprite'] == 'SPRITE_BOULDER' and (obj['x'], obj['y']) == point)
                    if live.get(index, point) == point:
                        return Goal(f'push_{point}', 'Move the gym boulders with Strength', 'CIANWOOD_GYM', *stand, face)
            return self.person(snapshot, 'storm', 'Challenge Chuck', 'CIANWOOD_GYM', 'CianwoodGymChuckScript')
        self.completed.setdefault('storm', snapshot.frame)
        if not snapshot.event('EVENT_GOT_HM02_FLY'):
            return self.person(snapshot, 'fly', 'Receive Fly from Chuck’s wife', 'CIANWOOD_CITY', 'CianwoodCityChucksWife')
        if not snapshot.event('EVENT_JASMINE_RETURNED_TO_GYM'):
            return self.person(snapshot, 'heal_amphy', 'Deliver Amphy’s medicine', 'OLIVINE_LIGHTHOUSE_6F', 'OlivineLighthouseJasmine')
        if not snapshot.badges & 16:
            return Goal('mineral', 'Challenge Jasmine', 'OLIVINE_GYM', 5, 4, 'up')
        self.completed.setdefault('mineral', snapshot.frame)
        if not snapshot.event('EVENT_LAKE_OF_RAGE_RED_GYARADOS'):
            return Goal('red_gyarados', 'Investigate the red Gyarados', 'LAKE_OF_RAGE', 18, 23, 'up')
        if not snapshot.event('EVENT_DECIDED_TO_HELP_LANCE'):
            return self.person(snapshot, 'lance', 'Help Lance investigate Team Rocket', 'LAKE_OF_RAGE', 'LakeOfRageLanceScript')
        if not snapshot.event('EVENT_UNCOVERED_STAIRCASE_IN_MAHOGANY_MART'):
            return Goal('hideout_entrance', 'Find Team Rocket’s hideout', 'MAHOGANY_MART_1F', 4, 5)
        if not snapshot.event('EVENT_CLEARED_ROCKET_HIDEOUT'):
            if not snapshot.event('EVENT_TURNED_OFF_SECURITY_CAMERAS'):
                return Goal('security', 'Disable the hideout security cameras', 'TEAM_ROCKET_BASE_B1F', 19, 12, 'up')
            for event, key, script in [('EVENT_LEARNED_SLOWPOKETAIL', 'password_one', 'SlowpokeTailGrunt'),
                                       ('EVENT_LEARNED_RATICATE_TAIL', 'password_two', 'RaticateTailGrunt')]:
                if not snapshot.event(event):
                    return self.person(snapshot, key, 'Find the hideout passwords', 'TEAM_ROCKET_BASE_B3F', script)
            if not snapshot.event('EVENT_OPENED_DOOR_TO_GIOVANNIS_OFFICE'):
                return Goal('office_door', 'Open the executive’s office', 'TEAM_ROCKET_BASE_B3F', 10, 10, 'up')
            if not snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEM_4'):
                return Goal('executive', 'Challenge the Rocket executive', 'TEAM_ROCKET_BASE_B3F', 10, 8)
            if not snapshot.event('EVENT_LEARNED_HAIL_GIOVANNI'):
                return self.person(snapshot, 'murkrow', 'Learn the transmitter password', 'TEAM_ROCKET_BASE_B3F', 'RocketBaseMurkrow')
            if not snapshot.event('EVENT_OPENED_DOOR_TO_ROCKET_HIDEOUT_TRANSMITTER'):
                return Goal('transmitter_door', 'Open the transmitter room', 'TEAM_ROCKET_BASE_B2F', 14, 13, 'up')
            for number in range(1, 4):
                if not snapshot.event(f'EVENT_TEAM_ROCKET_BASE_B2F_ELECTRODE_{number}'):
                    return self.person(snapshot, f'electrode_{number}', 'Stop the radio transmitter',
                                       'TEAM_ROCKET_BASE_B2F', f'RocketElectrode{number}')
            return Goal('hideout_done', 'Finish helping Lance', 'TEAM_ROCKET_BASE_B2F', 7, 10)
        self.completed.setdefault('rocket_hideout', snapshot.frame)
        if not snapshot.badges & 64:
            return Goal('glacier', 'Challenge Pryce', 'MAHOGANY_GYM', 5, 4, 'up')
        self.completed.setdefault('glacier', snapshot.frame)
        if not snapshot.event('EVENT_CLEARED_RADIO_TOWER'):
            if not snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEM_3'):
                return Goal('fake_director', 'Find the Radio Tower director', 'RADIO_TOWER_5F', 0, 3)
            if not snapshot.event('EVENT_USED_BASEMENT_KEY'):
                return Goal('basement_key', 'Unlock the underground passage', 'GOLDENROD_UNDERGROUND', 18, 7, 'up')
            if not snapshot.event('EVENT_RECEIVED_CARD_KEY'):
                if snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_WAREHOUSE']:
                    return self.person(snapshot, 'card_key', 'Rescue the Radio Tower director',
                                       'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GoldenrodUndergroundWarehouseDirectorScript')
                if (snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES']
                        and snapshot.x >= 20 and 7 <= snapshot.y < 14
                        and not snapshot.event('EVENT_EMERGENCY_SWITCH')):
                    return Goal('emergency_switch', 'Open the underground emergency exit',
                                'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
                for number, x in [(3, 2), (2, 10), (1, 16)]:
                    if not snapshot.event(f'EVENT_SWITCH_{number}'):
                        return Goal(f'switch_{number}', 'Open the underground shutters',
                                    'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', x, 2, 'up')
                return self.person(snapshot, 'card_key', 'Rescue the Radio Tower director',
                                   'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GoldenrodUndergroundWarehouseDirectorScript')
            if snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_WAREHOUSE']:
                return Goal('warehouse_exit', 'Leave the underground warehouse',
                            'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
            if (snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES']
                    and snapshot.x >= 20 and 7 <= snapshot.y < 14 and not snapshot.event('EVENT_EMERGENCY_SWITCH')):
                return Goal('emergency_exit', 'Open the underground exit',
                            'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
            if not snapshot.event('EVENT_USED_THE_CARD_KEY_IN_THE_RADIO_TOWER'):
                return Goal('card_key_slot', 'Open the Radio Tower shutter', 'RADIO_TOWER_3F', 14, 3, 'up')
            return Goal('radio_tower', 'Free the Radio Tower', 'RADIO_TOWER_5F', 16, 5)
        self.completed.setdefault('radio_tower', snapshot.frame)
        partner = self.partner_goal(snapshot, 250)
        if partner:
            return partner
        if not snapshot.event('EVENT_GOT_HM07_WATERFALL'):
            return self.person(snapshot, 'waterfall', 'Find Waterfall in the Ice Path', 'ICE_PATH_1F', 'IcePath1FHMWaterfall')
        for number in range(1, 5):
            if not snapshot.event(f'EVENT_BOULDER_IN_ICE_PATH_{number}'):
                if snapshot.map != self.data.map_ids['ICE_PATH_B1F']:
                    return Goal('ice_boulders', 'Clear a route through the Ice Path', 'ICE_PATH_B1F', 3, 14)
                goal = self.boulder(snapshot, mem, 'ICE_PATH_B1F', f'EVENT_BOULDER_IN_ICE_PATH_{number}', number + 2)
                if goal:
                    return goal
        if snapshot.map == self.data.map_ids['BLACKTHORN_CITY']:
            self.completed.setdefault('ice_path', snapshot.frame)
        if ('ice_path' not in self.completed or not snapshot.event('EVENT_BEAT_CLAIR')
                and self.constant(snapshot).startswith('ICE_PATH_')):
            name = self.constant(snapshot)
            if name == 'ICE_PATH_B2F_MAHOGANY_SIDE':
                return Goal('ice_crossing', 'Cross the frozen cavern', 'ICE_PATH_B3F', 3, 5)
            if name == 'ICE_PATH_B3F':
                return Goal('ice_lower', 'Continue toward Blackthorn', 'ICE_PATH_B2F_BLACKTHORN_SIDE', 3, 4)
            if name == 'ICE_PATH_B2F_BLACKTHORN_SIDE':
                return Goal('ice_climb', 'Climb toward the Ice Path exit', 'ICE_PATH_B1F', 11, 26)
            if name == 'ICE_PATH_B1F' and snapshot.y > 20:
                return Goal('ice_exit_corridor', 'Find the Ice Path exit', 'ICE_PATH_1F', 37, 14)
            if name == 'ICE_PATH_1F' and snapshot.x > 30 and snapshot.y >= 13:
                return Goal('blackthorn', 'Arrive in Blackthorn City', 'BLACKTHORN_CITY', 36, 10)
            if name == 'ICE_PATH_1F':
                return Goal('ice_stairs', 'Reach the frozen cavern stairs', 'ICE_PATH_B1F', 3, 14)
            return Goal('ice_descent', 'Descend into the frozen cavern', 'ICE_PATH_B2F_MAHOGANY_SIDE', 17, 2)
        if not snapshot.event('EVENT_BEAT_CLAIR'):
            for number, warp in [(3, 4), (2, 3), (1, 5)]:
                if not snapshot.event(f'EVENT_BOULDER_IN_BLACKTHORN_GYM_{number}'):
                    if snapshot.map != self.data.map_ids['BLACKTHORN_GYM_2F']:
                        return Goal('gym_boulders', 'Prepare a route to Clair', 'BLACKTHORN_GYM_2F', 7, 9)
                    goal = self.boulder(snapshot, mem, 'BLACKTHORN_GYM_2F', f'EVENT_BOULDER_IN_BLACKTHORN_GYM_{number}', warp)
                    if goal:
                        return goal
            return self.person(snapshot, 'clair', 'Challenge Clair', 'BLACKTHORN_GYM_1F', 'BlackthornGymClairScript')
        if not snapshot.badges & 128:
            if self.data.game == 'crystal':
                return self.person(snapshot, 'rising', 'Complete the Dragon Master’s test', 'DRAGON_SHRINE', 'DragonShrineElder1Script')
            return self.person(snapshot, 'rising', 'Find the Dragon Fang', 'DRAGONS_DEN_B1F', 'DragonsDenB1FDragonFangScript')
        self.completed.setdefault('rising', snapshot.frame)
        partner = self.partner_goal(snapshot, 127)
        if partner:
            return partner
        if not snapshot.hall_of_fame_count:
            rooms = [('WILL', 'WILLS_ROOM', 'WillScript_Battle'), ('KOGA', 'KOGAS_ROOM', 'KogaScript_Battle'),
                     ('BRUNO', 'BRUNOS_ROOM', 'BrunoScript_Battle'), ('KAREN', 'KARENS_ROOM', 'KarenScript_Battle')]
            for name, room, script in rooms:
                if not snapshot.event(f'EVENT_BEAT_ELITE_4_{name}'):
                    return self.person(snapshot, f'league_{name.lower()}', f'Challenge {name.title()}', room, script)
            if not snapshot.event('EVENT_BEAT_CHAMPION_LANCE'):
                return self.person(snapshot, 'league_lance', 'Challenge Champion Lance', 'LANCES_ROOM', 'LancesRoomLanceScript')
            return Goal('hall_of_fame', 'Enter the Hall of Fame', 'HALL_OF_FAME', 4, 7)
        self.completed.setdefault('champion', snapshot.frame)
        return kanto_journey(self, snapshot, mem, Goal)

    def boulder(self, snapshot, mem, map_name, event, warp):
        if self.resetting_puzzle == snapshot.map:
            return self.reset_puzzle_goal(map_name)
        entry = self.data.maps[snapshot.map]
        known = self.nav.objects.setdefault(snapshot.map, {})
        active = [(index, obj) for index, obj in enumerate(entry['objects'], 1)
                  if obj['sprite'] == 'SPRITE_BOULDER'
                  and not (obj['event'] in self.data.events and snapshot.event(obj['event']))]
        target = next((i for i, (_, obj) in enumerate(active) if obj['event'] == event), None)
        if target is None:
            return None
        positions = tuple(known.get(index, (obj['x'], obj['y'])) for index, obj in active)
        landing = entry['warps'][warp - 1]
        hole = (landing['x'], landing['y'])
        obstacles = tuple(known.get(index, (obj['x'], obj['y'])) for index, obj in enumerate(entry['objects'], 1)
                          if obj['sprite'] != 'SPRITE_BOULDER' and obj['kind'] != 'OBJECTTYPE_ITEMBALL'
                          and not (obj['event'] in self.data.events and snapshot.event(obj['event'])))
        key = (snapshot.map, positions, target, obstacles)
        if key not in self.puzzle_cache:
            grid = self.nav.collision(snapshot, mem.memory)
            plan = push_plan(grid, entry['width'], entry['height'], self.data.permissions,
                             (snapshot.x, snapshot.y), positions, target, hole, obstacles=obstacles)
            self.puzzle_cache[key] = plan
            predicted = list(positions)
            for offset, (stand, direction) in enumerate(plan or []):
                dx, dy = DIRS[direction]
                stone = (stand[0] + dx, stand[1] + dy)
                index = predicted.index(stone)
                predicted[index] = (stone[0] + dx, stone[1] + dy)
                self.puzzle_cache[(snapshot.map, tuple(predicted), target, obstacles)] = plan[offset + 1:]
        plan = self.puzzle_cache[key]
        if plan:
            stand, direction = plan[0]
            return Goal(f'push_{event}', 'Push a boulder into the opening', map_name, *stand, direction)
        self.puzzle_cache.clear()
        self.resetting_puzzle = snapshot.map
        return self.reset_puzzle_goal(map_name)

    def reset_puzzle_goal(self, map_name):
        if map_name == 'ICE_PATH_B1F':
            return Goal('reset_ice', 'Reset the boulder arrangement', 'ICE_PATH_1F', 37, 4)
        return Goal('reset_gym', 'Reset the boulder arrangement', 'BLACKTHORN_GYM_1F', 7, 7)

    def needed_move(self, snapshot):
        if self.partner_move is not None:
            if not any(not mon.egg and self.partner_move in self.data.species[mon.species]['machines'] for mon in snapshot.party):
                return self.partner_move
            self.partner_move = None
        return 127 if snapshot.badges & 128 else 250 if snapshot.badges & 64 else 57

    def partner_goal(self, snapshot, move, shore=None):
        """The goal that fetches a partner for ``move``, or None. ``shore`` is the move whose shore a fishing
        trip picks, the move the partner is wanted for so far by default."""
        if any(not mon.egg and move in self.data.species[mon.species]['machines'] for mon in snapshot.party):
            return None
        if self.no_room(snapshot):
            # A full team, every box full and no spare to release leave nowhere to put a team member
            # down, so a partner can be neither withdrawn nor caught. A trade that sends the partner
            # away can leave the run here; visiting the PC would only fail to deposit forever.
            return None
        candidates = [mon for mon in snapshot.stored if not mon.egg
                      and move in self.data.species[mon.species]['machines']]
        if len(snapshot.party) == 6 or candidates:
            return self.storage_goal(snapshot)
        if not snapshot.event('EVENT_GOT_GOOD_ROD'):
            return self.person(snapshot, 'good_rod', 'Get a fishing rod', 'OLIVINE_GOOD_ROD_HOUSE', 'GoodRodGuru')
        return self.fishing(snapshot, shore)

    # Prompts where the adventure should answer YES at once, and prompts it must always decline.
    YES_PROMPTS = re.compile(r'HEAL')
    NO_PROMPTS = re.compile(r'MONEY|SAVE|CALL|PHONE|REGISTER|NUMBER')
    NO_LIMIT = 3

    def unknown_yes_no(self, snapshot):
        """Decline YES or NO prompts the policy has no plan for, instead of mashing A into YES.

        Mom's savings and phone calls both ask YES or NO in the overworld. A prompt that
        keeps coming back after repeated refusals is one the story needs, so it gets a YES.
        """
        rows = snapshot.tiles
        yes = next((i for i, row in enumerate(rows[:12]) if menu_label(row) == 'YES'), None)
        if yes is None or yes + 1 >= 12 or menu_label(rows[yes + 1]) != 'NO' or '▶' not in rows[yes] + rows[yes + 1]:
            return None
        question = ' '.join(' '.join(rows[13:]).upper().split())
        if self.NO_PROMPTS.search(question):
            return 'b'
        if self.YES_PROMPTS.search(question):
            return None
        count = self.refusals.get(question, 0)
        if count >= self.NO_LIMIT:
            self.refusals.clear()
            return None
        if len(self.refusals) > 32:
            self.refusals.clear()
        self.refusals[question] = count + 1
        return 'b'

    def constant(self, snapshot):
        """Map constant, or an empty name before the game has loaded a real map."""
        return self.data.maps.get(snapshot.map, {}).get('constant', '')

    def travel_region(self, snapshot):
        name = self.constant(snapshot)
        if ((name == 'TOHJO_FALLS' and snapshot.x < 20 or name == 'ROUTE_27' and snapshot.x < 32)
                and not any(127 in mon.moves for mon in snapshot.party)):
            return self.data.maps[self.data.map_ids['NEW_BARK_TOWN']]['region']
        return self.data.maps[snapshot.map]['region']

    def returned_encounter(self, snapshot, Goal, name):
        """Prepare for a one-time encounter that came back: a storage goal, False to go now, None to wait."""
        if self.in_league(snapshot) or self.in_transmitter_room(snapshot):
            # The League rooms only lead forward, so finish the run before going back for it.
            return None
        if not snapshot.can_catch:
            if self.no_room(snapshot):
                return None
            goal = self.storage_goal(snapshot)
            return Goal('collection_box', f'Make room for {name}', goal.map_name, goal.x, goal.y, goal.face)
        master = self.data.items['MASTER_BALL']
        # The Master Ball stays reserved for legendaries, and a battle without a ball only knocks it out.
        return False if any(item != master and count for item, count in snapshot.pockets['balls']) else None

    def storage_units(self, snapshot):
        """The ledger's next box unit and the next one that can go straight from the box. Kept until
        storage or the plans change."""
        from .ledger import storage_unit
        key = (self.rating_key(snapshot), snapshot.pockets.get('items', ()),
               tuple(self.collection.get('prerequisites', ())), self.decisions // 600)
        if self.release_cache[0] != key:
            self.release_cache = (key, (storage_unit(self, snapshot), storage_unit(self, snapshot, direct=True)))
        return self.release_cache[1]

    def release_owners(self):
        """The original trainers whose Pokémon a release may let go: the player and the linked adventures.
        None before the cartridge's memory is attached, which leaves the trainer out of the rules."""
        from ..trade.partners import owners
        player = Memory(self.memory, self.data).word('wPlayerID') if self.memory is not None else None
        return owners(player, self.trade_partners())

    def rating_key(self, snapshot):
        """Everything the PC values read: the Pokémon, the plans, the trade settings, the linked
        adventures, the League rewards, the owner's release requests, the Favor setting, the team
        seen at this PC visit, the Pokédex and the open hunt."""
        from .release import hunt_focus, plan_partners
        preferences = self.trade_preferences()
        return (snapshot.party, snapshot.stored, snapshot.active_box, tuple(sorted(self.demand.items())), self.visit_team.keys,
                frozenset(getattr(snapshot, 'owned', ()) or ()), hunt_focus(self.collection),
                tuple(sorted(map(str, plan_partners(self.collection)))), self.release_owners(),
                tuple(sorted((key, (value or {}).get('state')) for key, value in preferences.items())),
                frozenset(self.league_marks()) if hasattr(self, 'league_marks') else frozenset(),
                tuple(sorted(self.release_requests().items())) if hasattr(self, 'release_requests') else (),
                self.pc_favor() if hasattr(self, 'pc_favor') else None)

    def pc_rated(self, snapshot, marks=frozenset(), extra=()):
        """Every Pokémon scored as the next release scores it (pcvalue.py), for the PC tab, the ledger
        and the owner's requests. Kept until rating_key changes, so a waiting request does not rate the
        whole PC on every decision. Extra League reward ``marks`` or ``extra`` rows give a one-off rating."""
        from .release import release_rated
        if marks or extra:
            return release_rated(self, snapshot, marks=marks, extra=extra)
        key = self.rating_key(snapshot)
        if self.rated_cache[0] != key:
            self.rated_cache = (key, release_rated(self, snapshot))
        return self.rated_cache[1]

    def release_target(self, snapshot):
        """The spare duplicate to release next straight from the box, or None."""
        unit = self.storage_units(snapshot)[1]
        return unit.detail if unit else None

    def storage_target(self, snapshot):
        """The ledger's next box unit: a spare to release, or one whose item comes off first. None when
        nothing can free a slot."""
        return self.storage_units(snapshot)[0]

    def trade_spare(self, snapshot, protect=(), wished=()):
        """The spare to release so a trade can be prepared with every box full, or None.

        It is the lowest-value Pokémon that may go (pcvalue.py). The ``protect`` trade keys, hand-picked
        for a trade, stay as if set to Keep, and a ``wished`` species counts as stock.
        """
        from ..pcvalue import queue
        from .release import _keys, release_rated
        from pokecore.identity import same
        preferences = dict(self.trade_preferences())
        if protect:
            # A key from an older release names its Pokémon by trainer and DVs only.
            for mon in snapshot.stored:
                own = _keys(mon)[0]
                if any(same(own, key) for key in protect):
                    preferences[own] = {'state': 'locked'}
        return next((row.entry.record for row in queue(release_rated(self, snapshot, wished, preferences))
                     if self.allowed(Release(row.entry.record.box, row.entry.record.position), snapshot)), None)

    def unloaded(self, snapshot, mem):
        """Whether the cartridge restarted to its opening while memory still shows the save it read.

        The main menu reads the save's party and place to describe it, so the run looks started.
        No map is loaded until Continue, though, and every loaded map has a width. A live Crystal run
        reset in the Battle Tower walked into the blank walls of that unloaded map for hours.
        """
        return snapshot.started and not snapshot.in_battle and mem.byte('wMapWidth') == 0

    def battle_starting(self, mem):
        """Whether the wild battle script has begun while the battle itself has not.

        The battle transition draws over the map blocks the plan reads, so a plan made then sees no
        encounter tiles. A postgame hunt took that for an unloaded map and waited, and the goal stayed
        on that wait through the whole battle, so most of a Gold or Silver postgame hunt was counted
        as waiting. The goal that walked into the battle carries on through it instead.
        """
        return bool(mem.byte('wScriptRunning') and mem.byte('wTempWildMonSpecies'))

    def idle(self, snapshot):
        """Whether the run stands on its clock-wait tile, the moment between two patrol steps.

        The emulator does not treat this pause as a stuck run, since the clock-wait only ends when enough
        game time has passed.
        """
        goal = self.goal
        return (self.waiting(snapshot) and not snapshot.in_battle
                and (goal.x, goal.y) == (snapshot.x, snapshot.y))

    def waiting(self, snapshot):
        """Whether the run is walking the grass on purpose until the cartridge clock opens new work.

        The patrol earns no new progress, so the emulator does not reload it for lack of progress,
        but a patrol that stops moving is still caught by the stuck and frozen screen checks.
        """
        goal = self.goal
        return (goal is not None and goal.key == 'collection_idle' and self.menu is None
                and self.data.map_ids.get(goal.map_name) == snapshot.map)

    def no_room(self, snapshot):
        """Every box is full and nothing can be released, so a catch has nowhere to go."""
        return (not snapshot.can_catch and all(count >= 20 for count in snapshot.box_counts)
                and self.storage_target(snapshot) is None)

    def release_goal(self, snapshot, mem, releasing=False):
        """Visit a PC to let spare duplicates go while the ledger wants box slots freed.

        Without this a full PC leaves every catch, one-time encounter and field-move errand
        walking to a PC that has nowhere to put anything. A visit under way (``releasing``) frees
        slots up to the refill mark.
        """
        from ..planning.ledger import box_wanted
        from .release import headroom, pending
        # A spare whose item is coming off keeps the visit going until it is gone, even past the refill
        # mark, and an owner's release request starts a visit of its own.
        unequipping = bool(self.collection.get('unequip')) or pending(self, snapshot)
        # A catch goes to a free party slot first, so a new visit counts those as room. Without this a PC
        # errand that deposits one partner before it withdraws another started a release visit in between.
        room = headroom(snapshot) + (0 if releasing else max(6 - len(snapshot.party), 0))
        if (not (box_wanted(room, releasing) or unequipping) or self.in_league(snapshot) or self.in_transmitter_room(snapshot)
                or snapshot.map == self.data.map_ids['POKECENTER_2F'] or self.collection.get('time_capsule_restore')
                or self.collection.get('tower') or mem.byte('wStatusFlags2') & 4):
            return None
        if self.storage_target(snapshot) is None and not unequipping:
            return None
        goal = self.storage_goal(snapshot)
        if goal.key != 'storage':
            return None
        return Goal('collection_release', 'Make room in storage',
                    goal.map_name, goal.x, goal.y, goal.face)

    def storage_goal(self, snapshot):
        choices, unreachable = [], []
        region = self.travel_region(snapshot)
        for mid, entry in self.data.maps.items():
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            pcs = [(index % entry['width'], index // entry['width'] + 1)
                   for index, tile in enumerate(entry['collision']) if tile == 0x93]
            # Kept for a cartridge restored somewhere no route is known, such as a cable room.
            unreachable.extend((entry['region'] != region, mid, x, y) for x, y in pcs)
            if entry['region'] != region:
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.walk(snapshot, mid)
            if route is None:
                continue
            choices.extend((len(route), mid, x, y) for x, y in pcs)
        if not choices:
            if snapshot.map == self.data.map_ids['POKECENTER_2F']:
                return Goal('return_from_cable', 'Return downstairs after the Cable Club', 'POKECENTER_2F', 0, 7)
            # Aim at the nearest known Pokémon Center by id and let navigation and stall recovery sort it out.
            _, mid, x, y = min(unreachable)
        else:
            nearest = min(choices)[0]
            tied = [choice[1:] for choice in choices if choice[0] == nearest]
            # Two Pokémon Centers the same number of maps away can swap places as the player crosses a
            # warp, as Rock Tunnel and Route 10 do. Keeping the earlier pick stops the walk turning back.
            kept = getattr(self, 'storage_pick', None)
            mid, x, y = kept if kept in tied else min(tied)
            self.storage_pick = (mid, x, y)
        return Goal('storage', 'Prepare a place for a field move partner', self.data.maps[mid]['constant'], x, y, 'up')

    def fishing(self, snapshot, move=None):
        move = self.needed_move(snapshot) if move is None else move
        map_name = 'BLACKTHORN_CITY' if move == 127 else 'OLIVINE_CITY'
        mid = self.data.map_ids[map_name]
        entry = self.data.maps[mid]
        choices = []
        for y in range(1, entry['height'] - 1):
            for x in range(1, entry['width'] - 1):
                if not self.nav.passable(entry['collision'][y * entry['width'] + x]):
                    continue
                for face, (dx, dy) in DIRS.items():
                    if entry['collision'][(y + dy) * entry['width'] + x + dx] not in (0x21, 0x29):
                        continue
                    path = self.nav.local(snapshot, [(x, y)]) if snapshot.map == mid else []
                    # An unreachable shore ranks last instead of leaving nothing to choose from.
                    choices.append((len(path) if path is not None else 1_000_000, x, y, face))
        _, x, y, face = min(choices)
        return Goal('fish_surf', 'Catch a partner for field moves', map_name, x, y, face)

    # Shop scripts that check an event and skip the pokemart once it is set, in all three games.
    CLOSED_SHOPS = {'MahoganyMart1FPharmacistScript': 'EVENT_DECIDED_TO_HELP_LANCE'}

    def clerk_present(self, snapshot, entry, shop):
        """Whether a clerk running this shop's script is on the map.

        A set event flag hides its object, so a shop whose every clerk is hidden cannot be used:
        Mahogany Mart's Team Rocket pharmacist leaves for good once the hideout is cleared, and
        the grandmother at the other counter takes over the shop.

        A clerk can also stay on the map and stop selling. Once the player agrees to help Lance,
        the pharmacist only talks about him until he leaves, so his counter is closed too.
        """
        closed_by = self.CLOSED_SHOPS.get(shop['script'])
        if closed_by and snapshot.event(closed_by):
            return False
        return any(obj['script'] == shop['script']
                   and (obj['event'] not in self.data.events or not snapshot.event(obj['event']))
                   for obj in entry['objects'])

    def person(self, snapshot, key, label, map_name, script):
        mid = self.data.map_ids[map_name]
        entry = self.data.maps[mid]
        matches = [(i, obj) for i, obj in enumerate(entry['objects'], 1) if obj['script'] == script]
        index, obj = next(((i, obj) for i, obj in matches
                           if obj['event'] not in self.data.events or not snapshot.event(obj['event'])), matches[0])
        x, y = next(((x, y) for i, x, y in snapshot.objects if i == index), (obj['x'], obj['y'])) if snapshot.map == mid else (obj['x'], obj['y'])
        grid = self.nav.collision(replace(snapshot, map=mid), self.memory if snapshot.map == mid else None)
        choices, approaches = [], []
        for face, (dx, dy) in DIRS.items():
            for distance in (1, 2):
                point = (x - dx * distance, y - dy * distance)
                if not (0 <= point[0] < entry['width'] and 0 <= point[1] < entry['height']):
                    continue
                if distance == 2 and grid[(y - dy) * entry['width'] + x - dx] not in (0x90, 0x98):
                    continue
                if not self.nav.passable(grid[point[1] * entry['width'] + point[0]]):
                    continue
                approaches.append((*point, face))
                path = self.reachable_path(snapshot, mid, point)
                if path is not None:
                    choices.append((len(path), point[0], point[1], face))
        if not choices:
            # Every approach is blocked for now. The walk takes one the map regions join, so it waits on the
            # people in the way. The tile below is the last resort, and a walk with no route to it is recorded.
            cut, surf = bool(snapshot.badges & 2), bool(snapshot.badges & 8)
            x, y, face = next(((px, py, face) for px, py, face in approaches
                               if self.nav.regions.route(snapshot, mid, [(px, py)], cut=cut, surf=surf) is not None),
                              (x, y + 1, 'up'))
            return Goal(key, label, map_name, x, y, face)
        _, x, y, face = min(choices)
        return Goal(key, label, map_name, x, y, face)

    def reachable_path(self, snapshot, mid, point):
        """Path to a tile, or None when it cannot be reached right now.

        On the current map, a failed local search means the tile is blocked (for example by a
        person standing on it). regions.route then answers [] for 'same region, use local nav',
        which must not be read as 'already there'.
        """
        same_map = snapshot.map == mid
        path = self.nav.local(snapshot, [point], self.memory) if same_map else None
        if path is not None:
            return path
        route = self.nav.regions.route(snapshot, mid, [point], cut=bool(snapshot.badges & 2),
                                       surf=bool(snapshot.badges & 8))
        if same_map and route == []:
            return None
        return route

    def in_league(self, snapshot):
        return self.constant(snapshot) in {
            'WILLS_ROOM', 'KOGAS_ROOM', 'BRUNOS_ROOM', 'KARENS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'}

    def in_transmitter_room(self, snapshot):
        return (snapshot.map == self.data.map_ids['TEAM_ROCKET_BASE_B2F']
                and snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEF_2')
                and not snapshot.event('EVENT_CLEARED_ROCKET_HIDEOUT'))

    def errand_allowed(self, snapshot, mem):
        """Whether a heal or supply errand may break off the current goal."""
        well_item = (self.goal.key == 'collection_trade_item'
                     and self.constant(snapshot) in {'SLOWPOKE_WELL_B1F', 'SLOWPOKE_WELL_B2F'})
        return (not self.goal.key.startswith('push_') and not well_item
                and (not self.collection.get('contest') or not mem.byte('wStatusFlags2') & 4))

    # Goals that end in a gym leader, Elite Four, Champion or Red battle, which the boss check guards
    # (planning/boss.py). The rival's battles are scripted on the way to other goals, so none is a goal.
    BOSSES = frozenset({'zephyr', 'hive', 'plain', 'fog', 'storm', 'mineral', 'glacier', 'clair',
                        'league_will', 'league_koga', 'league_bruno', 'league_karen', 'league_lance',
                        'surge', 'sabrina', 'erika', 'janine', 'misty', 'brock', 'blaine', 'blue', 'red'})

    # The training before a boss goal, by goal key: the level the best fighter trains to first, the
    # level of the boss's ace and the map the team trains on. The Elite Four and Lance share the key
    # 'league', since their rooms run back to back. A loss raises the bar (planning/losses.py).
    BOSS_FLOORS = {'zephyr': 14}
    BOSS_ACES = {'zephyr': 9, 'hive': 16, 'plain': 19, 'fog': 25, 'storm': 30, 'mineral': 35, 'glacier': 31,
                 'clair': 40, 'league': 50, 'surge': 46, 'sabrina': 48, 'erika': 46, 'janine': 39,
                 'misty': 47, 'brock': 44, 'blaine': 50, 'blue': 58, 'red': 81}
    BOSS_TRAINING = {'zephyr': 'ROUTE_31', 'hive': 'ROUTE_33', 'plain': 'ROUTE_34', 'fog': 'ROUTE_37',
                     'storm': 'ROUTE_39', 'mineral': 'ROUTE_39', 'glacier': 'ROUTE_44', 'clair': 'ROUTE_45',
                     'league': 'VICTORY_ROAD', 'surge': 'ROUTE_6', 'sabrina': 'ROUTE_8', 'erika': 'ROUTE_7',
                     'janine': 'ROUTE_15', 'misty': 'ROUTE_24', 'brock': 'ROUTE_2', 'blaine': 'ROUTE_21',
                     'blue': 'ROUTE_2', 'red': 'SILVER_CAVE_ROOM_1'}
    BOSS_NAMES = {'zephyr': 'Falkner', 'hive': 'Bugsy', 'plain': 'Whitney', 'fog': 'Morty', 'storm': 'Chuck',
                  'mineral': 'Jasmine', 'glacier': 'Pryce', 'clair': 'Clair', 'league': 'the Elite Four',
                  'surge': 'Lt. Surge', 'sabrina': 'Sabrina', 'erika': 'Erika', 'janine': 'Janine',
                  'misty': 'Misty', 'brock': 'Brock', 'blaine': 'Blaine', 'blue': 'Blue', 'red': 'Red'}
    BOSS_ROOMS = {'VIOLET_GYM': 'zephyr', 'AZALEA_GYM': 'hive', 'GOLDENROD_GYM': 'plain', 'ECRUTEAK_GYM': 'fog',
                  'CIANWOOD_GYM': 'storm', 'OLIVINE_GYM': 'mineral', 'MAHOGANY_GYM': 'glacier',
                  'BLACKTHORN_GYM_1F': 'clair', 'BLACKTHORN_GYM_2F': 'clair', 'VERMILION_GYM': 'surge',
                  'SAFFRON_GYM': 'sabrina', 'CELADON_GYM': 'erika', 'FUCHSIA_GYM': 'janine',
                  'CERULEAN_GYM': 'misty', 'PEWTER_GYM': 'brock', 'SEAFOAM_GYM': 'blaine',
                  'VIRIDIAN_GYM': 'blue', 'SILVER_CAVE_ROOM_3': 'red',
                  'WILLS_ROOM': 'league_will', 'KOGAS_ROOM': 'league_koga', 'BRUNOS_ROOM': 'league_bruno',
                  'KARENS_ROOM': 'league_karen', 'LANCES_ROOM': 'league_lance'}

    @staticmethod
    def boss_key(key):
        return 'league' if key.startswith('league_') else key

    def move_power(self, move):
        entry = self.data.moves.get(move) or {}
        return entry.get('power') or entry.get('effect') in BORROWED_MOVES

    def fighter_level(self, party):
        """The level of the best party Pokémon that can deal damage, the one a boss bar measures."""
        from ..planning.losses import best_level
        return best_level(party, self.move_power)

    def boss_ace(self, key):
        """The level of the boss's ace, from the cartridge's trainer tables when they were read."""
        from .readiness import ace_level
        key = self.boss_key(key)
        return ace_level(self.data, key) or self.BOSS_ACES[key]

    def boss_bar(self, key):
        """The level the best fighter trains to before the boss goal ``key``, its loss bar (planning/readiness.py)."""
        from ..planning.readiness import Boss, loss_bar
        key = self.boss_key(key)
        return loss_bar(Boss(key, self.boss_ace(key), floor=self.BOSS_FLOORS.get(key, 0)), self.losses)

    # The gyms the oracle judges by the team's matchup with the leader's ace, as Red, Blue and Yellow
    # do before every gym (planning/readiness.py). Falkner and the Kanto gyms have no matchup score, so
    # the loss bar alone holds them, and Falkner keeps his level floor.
    MATCHUP_GYMS = frozenset({'hive', 'plain', 'fog', 'storm', 'mineral', 'glacier', 'clair'})

    def boss(self, snapshot, goal):
        """The boss ``goal`` names, as the oracle sees it: its ace, floor and matchup scores."""
        from ..planning.readiness import Boss
        from .readiness import LEAGUE, readiness
        key = self.boss_key(goal.key)
        if key == 'league':
            scores = tuple(readiness(self, snapshot.party, room) for room in LEAGUE)
        elif key in self.MATCHUP_GYMS:
            scores = (readiness(self, snapshot.party, goal.key),)
        else:
            scores = ()
        inside = self.in_league(snapshot) if key == 'league' else self.BOSS_ROOMS.get(self.constant(snapshot)) == key
        return Boss(key, self.boss_ace(key), floor=self.BOSS_FLOORS.get(key, 0), scores=scores,
                    league=key == 'league', inside=inside)

    def boss_training(self, snapshot, goal):
        """A walk that trains before the boss ``goal`` names, or None once the oracle finds the team ready.

        Inside the League nothing turns back, so its rooms carry on."""
        if goal is None or self.in_league(snapshot):
            return None
        if goal.key not in self.BOSSES:
            return self.story_training(snapshot, goal)
        from ..planning.readiness import LOSS, judge, team
        boss = self.boss(snapshot, goal)
        verdict = judge(boss, team(snapshot.party, self.move_power), self.losses)
        if verdict is None:
            return None
        name, target = self.BOSS_NAMES[boss.key], verdict.target
        if verdict.reason == LOSS:
            label = f'Train the team to level {target} before {name}'
        elif boss.league:
            label = f'Prepare for the Pokémon League: train until the team matches up or reaches level {target}'
        else:
            label = f'Prepare for {name}: train until the team matches up or reaches level {target}'
        from .training import walk_goal
        return walk_goal(self, snapshot, Goal, lambda: label, map_name=self.BOSS_TRAINING[boss.key])

    # The badge each boss goal earns, in the order the story takes them. A story loss trains where
    # the team would before the first one not yet won, or the League before the first Hall of Fame.
    BOSS_BADGES = (('zephyr', 1), ('hive', 2), ('plain', 4), ('fog', 8), ('storm', 32), ('mineral', 16),
                   ('glacier', 64), ('clair', 128), ('league', 0), ('surge', 1024), ('sabrina', 8192),
                   ('erika', 2048), ('janine', 4096), ('misty', 512), ('brock', 256), ('blaine', 16384),
                   ('blue', 32768))

    def story_training(self, snapshot, goal):
        """A walk that trains before a story goal the rival or a Rocket executive beat the team on, or None."""
        if goal.key not in self.losses.levels():
            # Only a loss gives a story goal a bar, so with none the oracle has nothing to judge.
            return None
        from ..planning.readiness import Boss, judge, team
        verdict = judge(Boss(goal.key), team(snapshot.party, self.move_power), self.losses)
        if verdict is None:
            return None
        bar = verdict.target
        key = next((key for key, badge in self.BOSS_BADGES
                    if not (snapshot.badges & badge if badge else getattr(snapshot, 'hall_of_fame_count', 0))), 'red')
        from .training import walk_goal
        return walk_goal(self, snapshot, Goal, lambda: f'Train the team to level {bar} before another try at: {goal.label}',
                         map_name=self.BOSS_TRAINING[key])

    def note_boss_loss(self, snapshot):
        """Remember the best fighter level that lost to the boss the goal names, which raises its bar.

        A loss is a black out or a battle that cannot end in the boss's room, or anywhere in the League.
        A reload into a battle leaves no goal yet, so then the room alone names the boss. A loss to the
        rival or a Rocket executive elsewhere counts against the goal under way, which waits on the win."""
        from ..planning.losses import boss_trainer
        goal, here = getattr(self.goal, 'key', None), self.constant(snapshot)
        key = goal if goal in self.BOSSES else self.BOSS_ROOMS.get(here)
        if key is not None and (key != goal or here == self.goal.map_name or self.in_league(snapshot)):
            self.losses.note(self.boss_key(key), self.fighter_level(snapshot.party))
        elif goal is not None and boss_trainer(snapshot, 2) is not None:
            self.losses.note(goal, self.fighter_level(snapshot.party), snapshot.enemy_level)

    def heal_blocked(self, snapshot):
        """Whether healing stands down here: the League, the transmitter room, Ice Path, the Goldenrod
        warehouse, or Burned Tower before the beasts run."""
        if (self.in_transmitter_room(snapshot) or self.in_league(snapshot)
                or self.constant(snapshot).startswith('ICE_PATH_')
                or self.constant(snapshot) in {
                    'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES'}):
            return True
        return (snapshot.map == self.data.map_ids['BURNED_TOWER_B1F']
                and (not snapshot.event('EVENT_RELEASED_THE_BEASTS') or self.data.game == 'crystal'
                     and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER')))

    def boss_ready(self, snapshot, blocked):
        """The boss check before the goal under way (planning/boss.py): READY, HEAL or UNREADY.

        HEAL needs a Pokémon Center the heal walk can reach, or, between League rooms, an item in the bag
        that treats a short fighter (league_items). UNREADY goes in anyway, and the journal says so once
        per leg. Each Pokémon Center the party steps into starts a leg with fresh trips.
        """
        from ..planning import boss
        from .ledger import fighters, league_treatment
        gate = getattr(self, 'boss_gate', None)
        if gate is None:
            gate = self.boss_gate = boss.Gate()
        goal = self.goal
        key = goal.key if goal is not None and goal.key in self.BOSSES else None
        party = fighters(self.data, snapshot)
        at_center = self.data.maps.get(snapshot.map, {}).get('constant', '').endswith('POKECENTER_1F')
        supply = key is not None and self.in_league(snapshot) and league_treatment(self.data, snapshot) is not None
        verdict = gate.decide(key, party, lambda: not blocked and self.center(snapshot) is not None,
                              where=snapshot.map, center=at_center, supply=supply)
        surveying = getattr(self, 'ladder_survey', False)
        if verdict == boss.UNREADY and not surveying and gate.note():
            from .collection import pin_events
            names = [mon.name for mon in snapshot.party if not mon.egg]
            pin_events(self).append(boss.unready_event(goal.label, party, names))
        if not surveying and gate.healed():
            from .collection import pin_events
            pin_events(self).append(boss.healed_event(goal.label))
        return verdict

    def healing(self, snapshot):
        from ..planning import boss
        from ..planning.ledger import PP
        from .ledger import battle_room, cured, walk_spent
        if self.heal_blocked(snapshot):
            if any(not mon.egg for mon in getattr(snapshot, 'party', ())):
                # No walk out from here, so a boss ahead is met as the party stands.
                self.boss_ready(snapshot, True)
            return None
        healthy = [mon for mon in snapshot.party if not mon.egg]
        # A status a cure in the bag clears is treated where the party stands (field_cure), not walked to a nurse.
        spent = bool(healthy) and walk_spent(self.data, cured(self.data, snapshot))
        surveying = getattr(self, 'ladder_survey', False)
        if not healthy or not spent and self.boss_ready(snapshot, False) != boss.HEAL:
            if not surveying:
                if getattr(self, 'pp_heal', False) and self.healing_map == snapshot.map:
                    # A heal its spent PP called for says so in the journal once the nurse is done.
                    from .collection import pin_events
                    pin_events(self).append(boss.pp_heal_event(self.data.maps[snapshot.map]['name']))
                self.pp_heal = False
            self.healing_map = None
            return None
        center = self.center(snapshot)
        if center is None:
            self.healing_map = None
            return None
        mid, nurse = center
        if self.healing_map is None and not surveying:
            self.pp_heal = spent and battle_room(self.data, snapshot)[PP] == 0
        self.healing_map = mid
        return Goal('heal', 'Restore the team at a Pokémon Center', self.data.maps[mid]['constant'],
                    nurse['x'], nurse['y'] + 2, 'up')

    def center(self, snapshot):
        """The Pokémon Center the heal walk goes to, as (map, nurse), or None when none is reachable."""
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        choices = []
        for mid, entry in self.data.maps.items():
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            if entry['region'] != self.travel_region(snapshot):
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.walk(snapshot, mid)
            if route is None:
                continue
            nurse =next(obj for obj in entry['objects'] if obj['sprite'] == 'SPRITE_NURSE')
            # The walk from Route 44 to Blackthorn City goes through Ice Path, where healing stands down.
            # The trip would step into the cave, hand back to the main goal, step out and choose the same
            # center again. So a known walk must stay out of Ice Path. With no walk known yet, the map
            # walk decides alone.
            walk = self.nav.regions.route(snapshot, mid, [(nurse['x'], nurse['y'] + 2)], cut=cut, surf=surf)
            if walk is None or not any(
                    self.data.maps[step[1][0]]['constant'].startswith('ICE_PATH_') for step in walk):
                choices.append((len(route), mid, nurse))
        if not choices:
            return None
        # Keep to the center already chosen while it stays reachable, so the trip does not switch halfway.
        _, mid, nurse = next((choice for choice in choices if choice[1] == self.healing_map), min(choices))
        return mid, nurse

    TALK_STALL_FRAMES = 80
    TALK_FAIL_FRAMES = 110

    def talk_progress(self, snapshot):
        """Count conversation decisions in which nothing the player owns or stands on has changed.

        A long run means A is repeating a dialogue loop, such as a clerk offering the same purchase
        again. Drop any shopping errand, back out with B, and in the end report the failure.
        """
        key = (snapshot.map, snapshot.x, snapshot.y, snapshot.money, tuple(snapshot.items))
        if key != self.talk_key:
            self.talk_key, self.talk_frames = key, 0
            return False
        self.talk_frames += 1
        if self.talk_frames < self.TALK_STALL_FRAMES:
            return False
        if self.talk_frames == self.TALK_STALL_FRAMES:
            self.shopping = self.shop_location = None
            if self.interaction in ('buy_balls', 'sell_supplies'):
                self.interaction = None
        if self.talk_frames >= self.TALK_FAIL_FRAMES:
            self.talk_frames = 0
            self.fail(f'A conversation in {snapshot.map_name} made no progress')
            return False
        return True

    def shop(self, snapshot):
        """A supply errand worth breaking off for and the commit that writes its purchase and its shop, or
        ``(None, None)``. The commit runs only when the errand is picked (rule A).

        Each trip is weighed against restocking later on the arbiter (see errands): the walk there and
        back, the puzzle maps on the way and what leaving the current work loses. That keeps the run
        from shopping out of the League, a puzzle map or a story dungeon, and from shopping through
        Ice Path before it is solved.
        """
        if not snapshot.event('EVENT_GAVE_MYSTERY_EGG_TO_ELM'):
            self.shop_location = None
            return None, None
        from . import errands, ledger
        exit_frames = errands.exit_cost(self, snapshot)
        if exit_frames >= errands.worth(self, snapshot):
            # No trip can beat restocking later from here. The chosen shop stays chosen for after.
            return None, None
        cut, surf = bool(snapshot.badges & 2), bool(snapshot.badges & 8)
        if snapshot.money < ledger.price(self.data, 'POKE_BALL'):
            self.shop_location = None
            # With no ball and no money for one, the ledger sells what is worth least for money.
            sale = None if snapshot.pockets['balls'] else ledger.ball_sale(self.data, snapshot)
            if sale is None:
                return None, None
            choices = []
            for mid, entry in self.data.maps.items():
                if entry['region'] != self.travel_region(snapshot):
                    continue
                for shop in entry['shops']:
                    if not self.clerk_present(snapshot, entry, shop):
                        continue
                    goal = self.person(snapshot, 'sell_supplies', 'Sell a spare item for capture supplies', entry['constant'], shop['script'])
                    route = self.nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=cut, surf=surf)
                    if route is not None and errands.worth_trip(self, snapshot, 'sell_supplies', len(route),
                                                                [node[0] for _, node, _, _ in route], exit_frames=exit_frames):
                        choices.append((len(route), mid, goal))
            if choices:
                def sell():
                    self.shopping = sale
                return min(choices, key=lambda row: row[:2])[-1], sell
            return None, None
        requests = ledger.supplies(self, snapshot)
        if not requests:
            self.shop_location = None
            return None, None
        if self.shop_location and self.nav.regions.between(snapshot, cut, surf):
            # In a ledge hop the coordinates read the wall tile jumped over, which is in no region, so no
            # route can be judged until the player lands. The shop already chosen stays the goal. The walk
            # to Olivine Mart drops three ledges on Route 39, and the trip was dropped in each hop.
            mid, script, _ = self.shop_location
            return self.person(snapshot, 'buy_balls', 'Restock adventure supplies', self.data.maps[mid]['constant'], script), None
        choices = []
        for priority, (key, names, amount) in enumerate(requests):
            reserve = ledger.held_money(self.data, snapshot, key)
            for mid, entry in self.data.maps.items():
                if entry['region'] != self.travel_region(snapshot) or not entry['shops']:
                    continue
                # Cures are bought only where the player stands (ledger.cure_wanted), never on a trip.
                if key == 'cures' and mid != snapshot.map:
                    continue
                route = self.nav.walk(snapshot, mid)
                if route is None:
                    continue
                current = bool(self.shop_location) and mid == self.shop_location[0]
                crossing = [dest for _, dest, _, _ in route]
                if not errands.worth_trip(self, snapshot, 'buy_balls', len(route), crossing,
                                          current=current, exit_frames=exit_frames):
                    continue
                for shop in entry['shops']:
                    if not self.clerk_present(snapshot, entry, shop):
                        continue
                    item = next((self.data.items[name] for name in names
                                 if self.data.items[name] in shop['items']
                                 and self.data.item_attributes[self.data.items[name]]['price'] <= snapshot.money - reserve), None)
                    if item:
                        goal = self.person(snapshot, 'buy_balls', 'Restock adventure supplies', entry['constant'], shop['script'])
                        walk = self.nav.regions.route(snapshot, mid, [(goal.x, goal.y)], cut=cut, surf=surf)
                        # The walk can pass a puzzle map the map route did not, and a trip that breaks off
                        # there drops the shop at its mouth, so the next goal walks back out and the shop
                        # is chosen again.
                        if walk is None or not errands.worth_trip(
                                self, snapshot, 'buy_balls', len(route), crossing + [node[0] for _, node, _, _ in walk],
                                current=current, exit_frames=exit_frames):
                            continue
                        choices.append((priority, 0 if self.shop_location == (mid, shop['script'], item) else 1,
                                        len(walk), mid, item, shop['script'], amount, reserve))
        if not choices:
            self.shop_location = None
            return None, None
        _, _, _, mid, item, script, amount, reserve = min(choices)
        price = self.data.item_attributes[item]['price']

        def buy():
            self.shop_location = (mid, script, item)
            self.shopping = (item, min(amount, (snapshot.money - reserve) // price))
        return self.person(snapshot, 'buy_balls', 'Restock adventure supplies', self.data.maps[mid]['constant'], script), buy

    def step(self, snapshot, memory, sp=None, clock=None):
        """``sp`` is the CPU stack pointer, which Core's PC lists read to press through a <CONT> name.

        ``clock`` is the PlayClock frame the policy's waits count. A call without one keeps the last.
        """
        if clock is not None:
            self.clock = clock
        self.pick, self.decided = None, False
        self.ballot = self.pipeline_pick = None
        action = self._step(snapshot, memory, sp)
        ballot = self.ballot
        if self.errand is not None and not self.decided and self.goal is self.pick and not snapshot.in_battle:
            # An errand under way is the goal until the next errand decision ends it. Otherwise each
            # menu, conversation and team step on the way ran under the journey goal behind it. The step
            # has already decided under that goal, so menus read the same goal as before. It is offered again
            # as it was picked, so it is still the enabler of the goal it serves.
            errand = getattr(self, 'errand_offer', None)
            if ballot is None:
                self.goal = self.errand
            elif errand is not None:
                self.goal = ballot.resume(errand)
            else:
                self.goal = ballot.offer(self.errand, 'heal')
        if ballot is not None:
            # Only the offer the step ends with writes, so an offer a later site overrides leaves nothing.
            ballot.commit()
        shadow = getattr(self, 'shadow', None)
        if ballot is not None and shadow is not None and self.goal is not None:
            # The decision is the pipeline's, and the shadow keeps its record for the gate and the replays.
            # A goal no site offered shows there as unlisted.
            decision = shadow.weigh('pipeline', lambda: ballot.decision, self.goal.key, None,
                                    getattr(snapshot, 'frame', None))
            self.pipeline_pick = decision.record() if decision is not None else None
        # A journey asked for outside a step weighs on a ballot of its own.
        self.ballot = None
        return action

    def _step(self, snapshot, memory, sp=None):
        self.memory, self.sp = memory, sp
        self.decisions += 1
        from .release import team_keys
        self.visit_team.observe(snapshot.map, team_keys(snapshot.party))
        from .postgame import observe
        observe(self, snapshot)
        from .collection import observe_search
        observe_search(self, snapshot)
        from .training import observe as observe_training
        observe_training(self, snapshot)
        self.backing_out = False
        self.shiny_missed = None
        if getattr(snapshot, 'all_fainted', False):
            self.note_boss_loss(snapshot)
        if not snapshot.in_battle:
            self.flee_tries, self.fleeing = 0, False
        if self.rescue:
            self.mode = 'finding another approach'
            self.backing_out = True
            return Action(self.rescue.popleft(), 8, 24)
        mem = Memory(memory, self.data)
        mem.sp = sp
        from .ruins import control
        puzzle = control(snapshot, mem) if snapshot.started and snapshot.valid else None
        if puzzle:
            self.mode = 'Solve the Ruins of Alph picture puzzle'
            return Action(None, 0, 24) if puzzle == 'wait' else Action(puzzle, 6, 24)
        update_world(self.nav.regions, snapshot)
        naming = self.naming.step(snapshot, mem)
        if naming:
            self.mode = 'naming'
            return Action(naming, 6, 18)
        if snapshot.hall_of_fame_count and snapshot.map == self.data.map_ids['HALL_OF_FAME']:
            self.mode = 'Hall of Fame and credits'
            return Action('a', 8, 52)
        if not snapshot.started or self.unloaded(snapshot, mem):
            self.mode = 'opening'
            return Action('start' if self.decisions % 20 == 1 else 'a', 8, 52)
        from .contest import control as contest_control
        contest_button = contest_control(self, snapshot, mem)
        if contest_button:
            self.mode = 'Catch a Bug-Catching Contest partner'
            return Action(contest_button, 8, 28)
        from .tower import control as tower_control
        tower_button = tower_control(self, snapshot, mem)
        if tower_button:
            self.mode = 'Choose the Battle Tower challenge'
            return Action(tower_button, 6, 26)
        if self.menu is None and not snapshot.in_battle and self.constant(snapshot).endswith('POKECENTER_1F'):
            if 'TURN OFF' in snapshot.text:
                self.mode, self.backing_out = 'Close the PC', True
                return Action(close_pc(snapshot), 8, 36)
            if 'CHANGE BOX' in snapshot.text or 'Choose a' in snapshot.text:
                self.mode, self.backing_out = 'Close the PC', True
                return Action('b', 8, 36)
        if self.menu is None and snapshot.started and not snapshot.in_battle and ('CANCEL' in snapshot.text or 'PACK' in snapshot.text and 'SAVE' in snapshot.text or 'Teach ' in snapshot.text and 'POKéMON?' in snapshot.text):
            self.mode, self.backing_out = 'Close a menu', True
            return Action('b', 8, 28)
        if getattr(self.menu, 'battle', False):
            # Remedies run in and out of battle. The other battle shortcuts end with the battle.
            button = self.menu_step(snapshot, mem)
            if button:
                self.mode = 'Heal the team' if isinstance(self.menu, Remedy) else 'battle'
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
        if snapshot.in_battle:
            self.mode = 'battle'
            return self.battle(snapshot, mem)
        if not ('┌' in snapshot.tiles[12] or mem.byte('wScriptRunning')):
            self.talk_key, self.talk_frames = None, 0
        self.nav.observe(snapshot, interrupted=script_running(memory, self.data.game))
        if self.resetting_puzzle is not None and self.resetting_puzzle != snapshot.map:
            self.resetting_puzzle = None
        releasing = self.goal is not None and self.goal.key == 'collection_release'
        starting = self.goal is not None and self.battle_starting(mem)
        # Each site that sets the goal from here on offers it on the step's ballot, and the goal is the
        # ballot's pick (gen2/pipeline.py). A site writes its state only when its goal is picked (rule A).
        from .pipeline import Ballot
        self.ballot = ballot = Ballot()
        if starting:
            self.goal = journey_goal = ballot.offer(self.goal, 'current')
        else:
            self.goal = journey_goal = self.journey(snapshot, mem)
        release = self.release_goal(snapshot, mem, releasing)
        if release:
            self.goal = journey_goal = ballot.offer(release, 'release')
        self.pick = self.goal
        if isinstance(self.menu, Storage) and (self.menu.box_full or 'BOX is full' in snapshot.text):
            box = next((box for box, count in enumerate(snapshot.box_counts) if count < 20), None)
            if box is not None:
                self.menu = ChangeBox(box)
        if self.menu:
            button = self.menu_step(snapshot, mem)
            if button:
                labels = {Buy: 'Buy supplies', Sell: 'Sell a spare item', Storage: 'Manage Pokémon storage',
                          ChangeBox: 'Choose a receiving box', Use: 'Use an item', ShowPartner: 'Show a Pokémon',
                          DayCare: 'Manage the Day Care partners', Lead: 'Prepare the lead Pokémon',
                          Give: 'Give a held item', Take: 'Take a held item', Fly: 'Fly to the next destination',
                          FieldMove: 'Use a field move', Radio: 'Tune the radio', Teach: 'Teach a move',
                          PutAway: 'Store a spare item in the PC', Toss: 'Toss a spare item'}
                self.mode = labels.get(type(self.menu), 'Manage the team')
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
            return Action(None, 0, 24)
        if self.data.game == 'crystal' and snapshot.map == self.data.map_ids['DRAGON_SHRINE']:
            for label in ('Pal', 'Strategy', 'Anybody', 'Love', 'Both'):
                action = choose(snapshot.tiles, label, exact=True)
                if action:
                    return Action(action, 8, 28)
        from .item_sources import answer as number_answer
        action = number_answer(self, snapshot)
        if action:
            return Action(action, 8, 28)
        if self.goal.key == 'radio_card' and 'YES' in snapshot.text and 'NO' in snapshot.text:
            negative = any(word in snapshot.text for word in ('FLASH', 'CHARMANDER', 'APRIKORN', 'MARIE'))
            return Action(choose(snapshot.tiles, 'NO' if negative else 'YES', exact=True) or 'a', 8, 28)
        # Textboxes cover the bottom six rows. Scripted walking is allowed to finish.
        if '┌' in snapshot.tiles[12] or mem.byte('wScriptRunning'):
            self.mode = 'conversation'
            # The nurse and every other talk on the way run under the heal, not the journey goal, so one
            # trip stays one goal and the restore lands inside it.
            if not starting and self.errand_allowed(snapshot, mem):
                heal = self.healing(snapshot)
                if heal:
                    self.goal = ballot.offer(heal, 'talk_heal')
            if self.talk_progress(snapshot):
                return Action('b', 8, 36)
            answer = self.unknown_yes_no(snapshot)
            if answer:
                return Action(answer, 8, 36)
            return Action('a', 8, 36)
        lead = self.level_lead(snapshot)
        if lead and self.allowed(lead, snapshot):
            # A refused reorder is retried later rather than holding up the journey.
            self.menu = lead
            return Action(None, 0, 24)
        for event, move in ([] if self.collection.get('tower') or self.collection.get('contest') or self.collection.get('time_capsule_restore') else [('EVENT_GOT_HM01_CUT', 15), ('EVENT_GOT_HM02_FLY', 19), ('EVENT_GOT_HM03_SURF', 57),
                            ('EVENT_GOT_HM04_STRENGTH', 70), ('EVENT_GOT_HM06_WHIRLPOOL', 250), ('EVENT_GOT_HM07_WATERFALL', 127)]):
            if snapshot.event(event) and not any(move in mon.moves for mon in snapshot.party):
                protected = FIELD_MOVES
                ace = ace_slot(snapshot.party, self.move_power)
                slot = min((i for i, mon in enumerate(snapshot.party)
                            if not mon.egg and move in self.data.species[mon.species]['machines']
                            and not all(known in protected for known in mon.moves)),
                           key=lambda i: (i == ace, len(protected.intersection(snapshot.party[i].moves)), i), default=None)
                if slot is not None:
                    teach = Teach(move, slot)
                    if not self.allowed(teach, snapshot):
                        # A refused lesson is retried later rather than asked for at every step.
                        continue
                    self.menu = teach
                    return Action(None, 0, 24)
                compatible = [mon for mon in snapshot.party if not mon.egg
                              and move in self.data.species[mon.species]['machines']]
                if not compatible and move in {57, 250, 127} and not self.no_room(snapshot):
                    # The trip fishes on the shore for this move, and the move it is for is written only when
                    # the trip runs.
                    partner = self.partner_goal(snapshot, move, shore=move)
                    if partner is not None:
                        def commit(move=move):
                            self.partner_move = move
                        self.goal = ballot.offer(partner, 'partner', commit=commit)
                    break
                if 'ice_path' in self.completed:
                    candidates = [i for i, mon in enumerate(snapshot.party) if not mon.egg
                                  and move in self.data.species[mon.species]['machines']]
                    if candidates:
                        goal = self.person(snapshot, f'delete_hm_{candidates[0]}', f'Make room for {self.data.moves[move]["name"]}',
                                           'MOVE_DELETERS_HOUSE', 'MoveDeleter')
                        if goal is not None:
                            self.goal = ballot.offer(goal, 'delete_hm')
                        break
        lead = snapshot.party[0] if snapshot.party else None
        iron_tail = Teach(231, 0)
        if (lead and not lead.egg and snapshot.badges & 128 and self.data.items['TM23'] in dict(snapshot.items)
                and 231 in self.data.species[lead.species]['machines']
                and all(self.data.moves.get(move, {}).get('type', 0) in (0, 22) for move in lead.moves)
                and self.allowed(iron_tail, snapshot)):
            self.menu = iron_tail
            return Action(None, 0, 24)
        if not self.in_league(snapshot) and not self.collection.get('tower') and not self.collection.get('contest'):
            from .champion_shop import use as champion_use
            task = champion_use(self, snapshot)
            if task is not None and self.allowed(task, snapshot):
                self.menu = task
                return Action(None, 0, 24)
            if self.field_cure(snapshot):
                return Action(None, 0, 24)
        if self.in_league(snapshot) and (self.league_items(snapshot) or self.remedy(snapshot, cures=True)):
            return Action(None, 0, 24)
        if self.errand_allowed(snapshot, mem):
            prize_errand = self.goal.key in {'collection_coin_case', 'collection_coins', 'collection_prize', 'collection_slots'}
            heal = self.healing(snapshot)
            errand, commit = (heal, None) if heal or prize_errand else self.shop(snapshot)
            self.errand = self.errand_offer = None
            if errand is not None:
                self.goal = ballot.offer(errand, 'heal' if heal else 'shop', commit=commit)
                if self.goal is errand:
                    self.errand, self.errand_offer = errand, ballot.running
        else:
            self.errand = self.errand_offer = None
        if self.no_route_waiting(self.goal):
            # The goal found no route lately (no_route). An errand gives way to what the ballot picks
            # without it, and a goal with nothing to run instead looks around rather than walk the same
            # missing route again.
            if self.errand is not None and not self.no_route_waiting(journey_goal):
                self.goal = ballot.park(self.errand) or journey_goal
                self.errand = self.errand_offer = None
            if self.no_route_waiting(self.goal):
                self.decided = True
                self.mode = 'finding another approach'
                surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
                path = self.nav.explore(snapshot, memory, surf=surf)
                return self.walk(snapshot, memory, path) if path else Action(None, 0, 24)
        self.decided = True
        target =self.data.map_ids[self.goal.map_name]
        # A marathon runner covers the course on foot, so neither Fly nor Surf shortens a leg. The way
        # to the starting line is not timed, and from Kanto it needs both.
        from .marathon import racing
        running = self.goal.key == 'collection_marathon' and racing(self)
        from .flight import shortcut
        flight = None if running else shortcut(self, snapshot, mem, target)
        if flight:
            self.menu = flight
            self.mode = 'Fly to the next destination'
            return Action(None, 0, 24)
        surf = not running and bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        path = self.nav.toward(snapshot, target, [(self.goal.x, self.goal.y)], memory, surf=surf)
        if path is None and self.goal is not journey_goal:
            # A side goal that cannot be reached from here must not hide the main objective. It gives way to
            # what the ballot picks without it, and so on down to the journey goal.
            fallback = self.nav.toward(snapshot, self.data.map_ids[journey_goal.map_name],
                                       [(journey_goal.x, journey_goal.y)], memory, surf=surf)
            while fallback is not None and path is None and self.goal is not journey_goal:
                goal = ballot.park(self.goal) or journey_goal
                self.goal = journey_goal if goal is self.goal else goal
                path = fallback if self.goal is journey_goal else self.nav.toward(
                    snapshot, self.data.map_ids[self.goal.map_name], [(self.goal.x, self.goal.y)], memory, surf=surf)
        waypoint = False
        if path is None:
            path, waypoint = self.detour(snapshot, mem, memory, target, surf)
        # The goal's arrival reads what its site wrote, so the pick writes now (rule A).
        ballot.commit()
        self.mode = self.goal.label
        action = self.follow(snapshot, memory, path, waypoint, surf)
        if action:
            return action
        self.stranded = 0
        if path == []:
            if self.goal.key == 'return_from_cable':
                action = self.step_off(snapshot, memory, surf)
                if action:
                    return action
            if self.goal.key.startswith('collection_'):
                from .collection import arrive
                if self.goal.face and mem.byte('wPlayerDirection') & 12 != {'down': 0, 'up': 4, 'left': 8, 'right': 12}[self.goal.face]:
                    return Action(self.goal.face, 8, 16)
                button = arrive(self, snapshot)
                if button:
                    return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 36)
            if self.goal.key == 'snorlax' and mem.byte('wMapMusic') != 0x40:
                self.menu = Radio()
                return Action(None, 0, 24)
            if self.goal.key.startswith('delete_hm_') and self.interaction == self.goal.key:
                slot = int(self.goal.key.rsplit('_', 1)[1])
                move = next((move for move in (15, 70, 250) if move in snapshot.party[slot].moves), snapshot.party[slot].moves[0])
                self.menu = Forget(slot, move)
                return Action('a', 8, 36)
            if self.goal.key == 'storage' and self.interaction == self.goal.key:
                candidates = [mon for mon in snapshot.stored if not mon.egg
                              and self.needed_move(snapshot) in self.data.species[mon.species]['machines']]
                box = (next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
                       if snapshot.box_counts[snapshot.active_box] == 20 else None)
                if len(snapshot.party) < 6 and candidates:
                    box = candidates[0].box if candidates[0].box != snapshot.active_box else None
                if box is not None:
                    self.menu = ChangeBox(box)
                elif len(snapshot.party) == 6:
                    protected = FIELD_MOVES
                    from .breeding import carried
                    slot = min(range(1, len(snapshot.party)), key=lambda i:
                               (carried(self, snapshot, snapshot.party[i]),
                                bool(protected.intersection(snapshot.party[i].moves)), snapshot.party[i].egg,
                                snapshot.party[i].level))
                    self.menu = Storage('DEPOSIT', slot, len(snapshot.party))
                else:
                    mon = next((mon for mon in snapshot.stored if not mon.egg and mon.box == snapshot.active_box
                                and self.needed_move(snapshot) in self.data.species[mon.species]['machines']), None)
                    if mon is None:
                        return Action('b', 8, 36)
                    self.menu = Storage('WITHDRAW', mon.position, len(snapshot.party))
                return Action('a', 8, 36)
            if self.goal.key.startswith('push_') and mem.byte('wBikeFlags') & 1:
                self.nav.issued(snapshot, self.goal.face)
                return Action(self.goal.face, 16, 32)
            if self.goal.key == 'fish_surf' and self.interaction == self.goal.key:
                self.menu = Use(self.data.items['GOOD_ROD'])
                return Action(None, 0, 24)
            if self.goal.key == 'buy_balls' and self.interaction == self.goal.key:
                item, amount = self.shopping or (None, 0)
                affordable = snapshot.money // self.data.item_attributes[item]['price'] if item else 0
                if min(amount, affordable) < 1:
                    # Nothing here can be bought with the money in hand: forget the errand and leave.
                    self.shopping = self.shop_location = self.interaction = None
                    return Action('b', 8, 36)
                self.menu = Buy(item, min(amount, affordable), dict(snapshot.items).get(item, 0))
                return Action('a', 8, 36)
            if self.goal.key == 'sell_supplies' and self.interaction == self.goal.key:
                item, count = self.shopping
                self.menu = Sell(item, count)
                return Action('a', 8, 36)
            if self.goal.face and self.interaction != self.goal.key:
                self.interaction = self.goal.key
                return Action(self.goal.face, 8, 8)
            return Action('a', 8, 36)
        return Action(None, 0, 24)

    def detour(self, snapshot, mem, memory, target, surf):
        """A path for a goal with no walking route, and whether it only leads to a waypoint."""
        from .flight import outside
        # Fly only works outside and within one region, so a goal with no walking route is reached by
        # walking out, or on into the other region, first.
        exit_point = outside(self, snapshot, mem, target)
        if exit_point is not None:
            path = self.nav.toward(snapshot, exit_point[0], [exit_point[1]], memory, surf=surf)
            if path is not None:
                return path, True
        if (self.goal.key != 'sudowoodo' and snapshot.event('EVENT_FOUGHT_SUDOWOODO')
                and not snapshot.event('EVENT_ROUTE_36_SUDOWOODO')):
            # A returned Sudowoodo walls off Route 36. With no other way round, battle it even without a ball.
            tree = self.nav.toward(snapshot, self.data.map_ids['ROUTE_36'], [(35, 10)], memory, surf=surf)
            if tree is not None:
                goal = Goal('sudowoodo', 'Clear the moving tree off Route 36', 'ROUTE_36', 35, 10, 'up')
                ballot = getattr(self, 'ballot', None)
                self.goal = goal if ballot is None else ballot.offer(goal, 'sudowoodo')
                return tree, False
        return None, False

    def follow(self, snapshot, memory, path, waypoint, surf):
        """Walk the path, or handle having none. None once the goal itself is reached."""
        if path is not None:
            self.unreachable_waits = 0
        if path:
            # Walking toward a waypoint is not progress toward the goal. Stepping back out of a door the
            # stranded search walked into must not restart the count, or the policy never reports it.
            if not waypoint:
                self.stranded = 0
            return self.walk(snapshot, memory, path)
        if path is None or waypoint:
            # Standing on a waypoint Fly did not leave from is no better than having no route.
            return self.stranded_action(snapshot, memory, surf)
        return None

    def stranded_action(self, snapshot, memory, surf):
        """No route to the goal exists from here, so end the turn and record a failed attempt on it.

        When the map's regions still join the goal, only a person or a screen is in the way, so the walk
        looks around for a while first. Neither case asks for a reload, which replayed the same missing
        route after a full stall timeout and fed the stall watchdog.
        """
        self.stranded += 1
        if self.stranded >= self.STRANDED_LIMIT or not self.joined(snapshot, surf):
            self.stranded = 0
            return self.no_route(snapshot)
        path = self.nav.explore(snapshot, memory, surf=surf)
        if path:
            self.mode = 'finding another approach'
            return self.walk(snapshot, memory, path)
        # Briefly wait for moving people or map transitions before replanning, but do not wait
        # silently forever: after a long run of waits the objective is reported as stuck.
        self.unreachable_waits += 1
        if self.unreachable_waits >= STUCK_WAITS:
            self.mode = f'Stuck: cannot reach {self.goal.label}'
        return Action(None, 0, 24)

    def joined(self, snapshot, surf):
        """Whether the map regions join the player to the goal's tile, people and screens aside.

        A player in no region is between tiles. In a ledge jump the coordinates read the wall tile jumped
        over until the player lands. The regions say nothing about the route from there, so the walk looks
        around and counts as stranded rather than record a missing route that is there one step later.
        """
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        regions = self.nav.regions
        if not regions.memberships(snapshot.map, (snapshot.x, snapshot.y), cut, surf, arrive=True):
            return True
        return regions.route(snapshot, self.data.map_ids[self.goal.map_name], [(self.goal.x, self.goal.y)],
                             cut=cut, surf=surf) is not None

    def unreachable(self):
        """The walks that found no route lately (planning/unreachable.py), kept in the monitor's tables."""
        from ..planning.unreachable import FRAMES, NoRoute
        return NoRoute(self.monitor_tables, FRAMES)

    def no_route_waiting(self, goal):
        """Whether ``goal`` found no route lately and waits before it is walked again."""
        return goal is not None and self.unreachable().waiting(goal.key, goal.map_name, [(goal.x, goal.y)], self.clock)

    def no_route(self, snapshot):
        """End the turn of a walk with no route and record the failed attempt, with its map and target."""
        goal = self.goal
        self.unreachable().record(goal.key, goal.map_name, [(goal.x, goal.y)], self.clock, snapshot.map_name)
        self.unreachable_waits = 0
        self.mode = f'No route to {goal.label}'
        return Action(None, 0, 24)

    def step_off(self, snapshot, memory, surf):
        """Step off the tile the player stands on, or None when every side is blocked."""
        # Standing on stairs does not take them. A cancelled trade can leave the player on the
        # Pokémon Center 2F stairs, and pressing A there changes nothing. The next step walks back on.
        step = next((direction for direction, (dx, dy) in DIRS.items()
                     if self.nav.local(snapshot, [(snapshot.x + dx, snapshot.y + dy)], memory, surf=surf) == [direction]),
                    None)
        return self.walk(snapshot, memory, [step]) if step else None

    def walk(self, snapshot, memory, path):
        mem = Memory(memory, self.data)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        dx, dy = DIRS[path[0]]
        entry = self.data.maps[snapshot.map]
        nx, ny = snapshot.x + dx, snapshot.y + dy
        cut_tree = (0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x12, 0x1A))
        water = (surf and mem.byte('wPlayerState') not in (4, 8)
                 and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                 and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x21, 0x29))
        obstacle = (surf and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in ((0x24, 0x2C, 0x33) if path[0] == 'up' else (0x24, 0x2C)))
        if cut_tree or water or obstacle or (nx, ny) in {(x, y) for _, x, y in snapshot.objects}:
            key = (snapshot.map, snapshot.x + dx, snapshot.y + dy)
            if self.interaction == key and mem.byte('wPlayerDirection') & 12 == {'down': 0, 'up': 4, 'left': 8, 'right': 12}[path[0]]:
                return Action('a', 8, 36)
            self.interaction = key
            return Action(path[0], 8, 16)
        self.interaction = None
        self.nav.issued(snapshot, path[0])
        return Action(path[0], 16, 16)

    def league_items(self, snapshot):
        """Use the next item between League rooms (planning/boss.py treatment): a Revive for a fainted
        fighter, a restore up to the boss check's bar, or an Ether or Elixir for spent strong moves."""
        from .ledger import league_treatment
        found = league_treatment(self.data, snapshot)
        if found is None:
            return False
        slot, item, move = found
        count = dict(snapshot.items)[item]
        task = UseOn(item, slot, count, move) if move is not None else Remedy(item, slot, count)
        if not self.allowed(task, snapshot):
            return False
        self.menu = task
        return True

    def field_cure(self, snapshot):
        """Cure a status outside battle and outside the League with the cheapest cure in the bag
        (ledger.field_cure). The heal check leaves such a status out (ledger.cured)."""
        from .ledger import field_cure
        items = dict(snapshot.items)
        for slot, mon in enumerate(snapshot.party):
            name = field_cure(self.data, items, mon)
            if name is None:
                continue
            item = self.data.items[name]
            if self.allowed(task := Remedy(item, slot, items[item]), snapshot):
                self.menu = task
                return True
        return False

    def remedy(self, snapshot, *, active=None, cures=False):
        """Use a remedy on a party member, or on the one in battle when ``active`` is set. With ``cures``
        only status cures, which league_items leaves to it."""
        items = dict(snapshot.items)
        for slot, mon in enumerate(snapshot.party):
            if mon.egg or active is not None and slot != active or cures and (mon.hp == 0 or not mon.status):
                continue
            names = ()
            from .champion_shop import elixir
            restore = None if cures else elixir(self.data, snapshot, mon)
            # A remedy the game refused recently is skipped like any other refused shortcut, or the
            # battle would rebuild it every decision and never press a button.
            if restore and self.allowed(task := Remedy(restore, slot, items[restore]), snapshot):
                self.menu = task
                return True
            if mon.hp == 0:
                names = ('MAX_REVIVE', 'REVIVE')
            elif not cures and mon.hp < mon.max_hp * (0.55 if snapshot.in_battle else 0.8):
                names = ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION', 'SUPER_POTION', 'POTION')
            elif mon.status:
                names = ('FULL_RESTORE', 'FULL_HEAL', 'ANTIDOTE' if mon.status & 8 else
                         'AWAKENING' if mon.status & 7 else 'PARLYZ_HEAL' if mon.status & 64 else
                         'BURN_HEAL' if mon.status & 16 else 'ICE_HEAL')
            task = next((task for name in names if items.get(item := self.data.items[name], 0)
                         and self.allowed(task := Remedy(item, slot, items[item]), snapshot)), None)
            if task:
                self.menu = task
                return True
        return False

    def battle(self, snapshot, mem):
        # Roster nicknames are blanked so a mon named QUIT or FIGHT is not a menu.
        text = ScreenText(snapshot.text)
        if snapshot.tiles and '\n'.join(snapshot.tiles) == text:
            text = ScreenText('\n'.join(mask_roster(snapshot.tiles)))
        opponent = self.battle_target(snapshot, mem) if self.collection.get('tower') else snapshot
        # The native capture routine restores transformed wild opponents as Ditto.
        catch_species = 132 if mem.byte('wEnemySubStatus5') & 8 else snapshot.enemy_species
        needed = self.needed_move(snapshot)
        partner = (not any(needed in self.data.species[mon.species]['machines'] for mon in snapshot.party if not mon.egg)
                   and needed in self.data.species.get(catch_species, {}).get('machines', []))
        requested = (self.demand.get(catch_species, 0)
                     and sum(mon.species == catch_species and not mon.egg
                             for mon in snapshot.party + snapshot.stored) <= self.demand[catch_species])
        requested |= (catch_species in self.collection.get('prerequisites', ())
                      and not any(mon.species == catch_species and not mon.egg
                                  for mon in snapshot.party + snapshot.stored))
        own_rule = False
        if snapshot.in_battle == 1:
            # A wild carrier is caught only for the trade item it holds, never as one more copy.
            from .collection import item_hunts
            carried = item_hunts(self, snapshot).get(catch_species)
            own_rule = bool(carried) and mem.byte('wEnemyMonItem') == carried
        if catch_species == 201:
            # Each Unown letter counts separately in the Unown Pokédex, so catch every missing letter.
            from .collection import unown_letter, unown_missing
            own_rule |= unown_letter(mem.read('wEnemyMonDVs', 2)) in unown_missing(self, snapshot)
        # A wild shiny is always caught, an owned species too. Trainers' Pokémon never count.
        shiny = self.wild_shiny(snapshot)
        # A peer's request, a postgame better-DV hunt and a returned Pokémon catch an owned species only
        # when the PC would keep the copy (release.keeps_another, the one catch rule). A missing entry,
        # a field-move partner, a shiny, a missing Unown letter and an item carrier keep their own rules.
        from .postgame import quality_species, wild_dvs
        from .release import keeps_another
        upgrade = (snapshot.in_battle == 1 and catch_species in snapshot.owned and not (partner or shiny or own_rule)
                   and bool(requested or catch_species == quality_species(self) or catch_species in self.returned)
                   and keeps_another(self, snapshot, catch_species, dvs=wild_dvs(mem.read('wEnemyMonDVs', 2))))
        if (snapshot.in_battle == 1 and catch_species in self.returned and catch_species in {243, 244, 245, 249, 250, 251}
                and catch_species in snapshot.owned and not (upgrade or partner or shiny or own_rule)):
            # Close the return so neither the plan nor the retry timers bring back a refused legendary.
            self.declined = getattr(self, 'declined', set()) | {catch_species}
            self.returned = self.returned - {catch_species}
        catch = (snapshot.in_battle == 1 and (catch_species not in snapshot.owned or partner or own_rule or shiny or upgrade)
                 and snapshot.can_catch and any(self.data.item_names.get(item, '').casefold() in
                    {label.casefold() for label in self.ball_labels(snapshot)} for item, count in snapshot.pockets['balls'] if count))
        from .ledger import spare_throw
        if catch and not partner and not shiny and not spare_throw(self.data, snapshot, snapshot.enemy_species):
            catch = False
        if catch and not upgrade:
            # The last free slot is kept for an upgrade. Any other catch takes it only when a release can
            # follow, and a missing entry refused asks the owner for help (boxes_full).
            from .release import reserve_allows
            catch = reserve_allows(self, snapshot, catch_species, lambda: wild_dvs(mem.read('wEnemyMonDVs', 2)))
            self.boxes_full = not catch and catch_species not in snapshot.owned
        elif catch:
            self.boxes_full = False
        # A shiny that cannot be caught is run from, as Red, Blue and Yellow do, never knocked out.
        # The Bug-Catching Contest uses Park Balls and has its own rules in contest.control.
        self.shiny_missed = (self.shiny_miss_reason(snapshot)
                             if shiny and not catch and not mem.byte('wStatusFlags2') & 4 else None)
        weaken = self.capture_move(snapshot, mem) if catch else None
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        trapped = bool(mem.byte('wEnemySubStatus5') & 128 or mem.byte('wPlayerWrapCount'))
        # Scripted trap, red Gyarados, Celebi and Suicune battles forbid escape even without Mean Look.
        can_escape = not trapped and mem.byte('wBattleType') not in {7, 9, 11, 12}
        # Core shortcuts pick moves, balls and switches. Any pack or party submenu still open
        # here belongs to no running shortcut, so it is closed.
        if 'SWITCH' in text and 'STATS' in text:
            return Action('b', 8, 32)
        pocket = mem.byte('wCurPocket')
        if ('QUIT' in text or '×' in text
                or ('CANCEL' in text or '▶' in text or '▷' in text)
                and (pocket == 3 and any(re.match(r'(?:H[1-7]|\d{2})[ ▶▷]', row[5:]) for row in snapshot.tiles)
                     or pocket == 2 and any(self.data.item_names.get(item, '').upper() in text
                                            for item, _ in snapshot.pockets.get('key', ())))
                or 'CANCEL' in text and '/' not in text and 'ABLE' not in text):
            return Action('b')
        if any(row.startswith('ぐげござ') for row in snapshot.tiles[:2]):
            return Action('b', 8, 64)
        if 'already out' in text:
            return Action('b', 8, 24)
        if 'no will' in text:
            return Action('b', 8, 48)
        if 'CANCEL' in text and '/' in text and 'TYPE' not in text:
            active = min(mem.byte('wCurBattleMon'), max(0, len(snapshot.party) - 1))
            if snapshot.party and snapshot.party[active].hp:
                return Action('b')
            target = max((i for i, mon in enumerate(snapshot.party) if mon.hp and not mon.egg),
                         key=lambda i: max((self.move_score(move, snapshot.party[i], opponent)
                                            for move, pp in zip(snapshot.party[i].moves, snapshot.party[i].pp) if pp), default=0),
                         default=0)
            action = self.battle_task(Send(target), snapshot, mem)
            if action:
                return action
            cursor = mem.byte('wMenuCursorY')
            return Action('a' if target + 1 == cursor else 'down' if cursor < target + 1 else 'up')
        if 'FIGHT' in text and 'TYPE' not in text:
            action = self.stance_flee(snapshot, mem, catch=catch, shiny=shiny, escape=can_escape)
            if action:
                return action
            active = mem.byte('wCurBattleMon')
            switch = None
            # A static legendary only ever calls for the sleeper, and only while it is awake and
            # unguarded: a switch costs a sleep turn that a ball would use better.
            static = self.static_legend(snapshot)
            sleepable = static and not mem.byte('wEnemyMonStatus') and not mem.byte('wEnemyScreens') & 4
            if (catch and not roaming and not trapped and (partner or shiny or snapshot.enemy_species in {245, 249, 250, 251})
                    and weaken is None and (sleepable if static else snapshot.enemy_hp > snapshot.enemy_max_hp // 2)):
                candidates = [(self.capture_move(snapshot, mem, slot=i), i)
                              for i, mon in enumerate(snapshot.party)
                              if i != active and not mon.egg and mon.hp > mon.max_hp // 2
                              and (partner or mon.level * 2 >= snapshot.enemy_level)]
                if static:
                    candidates = [row for row in candidates if row[0] is not None and self.data.moves.get(
                        snapshot.party[row[1]].moves[row[0]], {}).get('effect') == 'EFFECT_SLEEP']
                switch = next((i for move, i in candidates if move is not None), None)
            if catch and weaken is None and switch is None and not (partner or trapped):
                odds = self.long_odds(snapshot, mem, catch_species, active, escape=can_escape)
                if odds == LEAVE:
                    # Nobody can weaken it, so the balls are kept and the species waits for a new
                    # move, member or ball (planning.throws). A refused run fights the battle out.
                    from .collection import defer
                    defer(self, snapshot, catch_species)
                    catch = False
                    action = self.battle_task(Flee(), snapshot, mem)
                    if action:
                        return action
                else:
                    switch = odds
            if switch is None and not catch and not trapped and self.collection.get('tower'):
                switch = self.tower_switch(snapshot, mem, active)
            fighters = [transformed(mem, mon) if index == active else mon for index, mon in enumerate(snapshot.party)]
            scores = [max((self.move_score(move, mon, opponent) for move, pp in zip(mon.moves, mon.pp) if pp), default=0)
                      if mon.hp and not mon.egg else 0 for mon in fighters]
            if (switch is None and not catch and not trapped and scores
                    and scores[min(active, len(scores) - 1)] == 0 and max(scores) > 0):
                switch = max(range(len(scores)), key=scores.__getitem__)
            if switch is None and not catch and not trapped and not self.collection.get('tower'):
                switch = self.trainee_switch(snapshot, active)
            action = switch is not None and self.battle_task(Send(switch), snapshot, mem)
            if action:
                return action
            if self.constant(snapshot) != 'BATTLE_TOWER_BATTLE_ROOM' and self.remedy(snapshot, active=mem.byte('wCurBattleMon')):
                return Action(None, 0, 24)
            self.learning = False
            if (roaming and not catch and can_escape and snapshot.in_battle == 1
                    and (snapshot.enemy_species not in snapshot.owned or snapshot.enemy_species in self.returned)):
                # A fainted roaming beast never returns, so leave it for a visit with room and balls.
                action = self.battle_task(Flee(), snapshot, mem)
                if action:
                    return action
            if catch and weaken is None:
                labels = [label.casefold() for label in self.ball_labels(snapshot)]
                balls = {self.data.item_names.get(item, '').casefold(): item for item, count in snapshot.pockets['balls'] if count}
                ball = next((balls[label] for label in labels if label in balls), None)
                action = ball is not None and self.battle_task(Throw(ball), snapshot, mem)
                if action:
                    return action
            mon = transformed(mem, snapshot.party[min(active, len(snapshot.party) - 1)]) if snapshot.party else None
            move = weaken if catch and weaken is not None else self.move_choice(snapshot, mem, mon, opponent, None) if mon else None
            if move is None and mon and not any(mon.pp):
                move = 0  # FIGHT with no PP left is Struggle, which the Core shortcut runs.
            action = move is not None and self.battle_task(Attack(move), snapshot, mem)
            if action:
                return action
            # No move has PP (Struggle) or the game refused the shortcut, so FIGHT is pressed and
            # the move list below picks the move. The cartridge remembers this cursor between turns.
            if mem.byte('wMenuCursorX') > 1:
                return Action('left')
            if mem.byte('wMenuCursorY') > 1:
                return Action('up')
            return Action('a')
        if any(phrase in text for phrase in ('trying to learn', 'Which move', 'HM moves', 'Forget an')):
            self.learning = True
            if snapshot.party:
                action = self.battle_task(Learn(self.learn_slot(snapshot.party[min(
                    mem.byte('wCurPartyMon'), len(snapshot.party) - 1)])), snapshot, mem)
                if action:
                    return action
        if ('TYPE/' in text or 'Disabled!' in text or 'No PP' in text or 'TYPE' in text and '/' in text
                or self.learning and '▶' in text and 'Which move' in text):
            slot = min(mem.byte('wCurPartyMon' if self.learning else 'wCurBattleMon'), max(0, len(snapshot.party) - 1))
            if snapshot.party:
                mon = snapshot.party[slot]
                if self.learning:
                    # The Core shortcut was refused, so the move list is answered directly.
                    forget = self.learn_slot(mon)
                    if forget == 'keep':
                        return Action('b')
                    target = forget + 1
                else:
                    move = self.move_choice(snapshot, mem, transformed(mem, mon), opponent, weaken)
                    target = 1 if move is None else move + 1
                cursor = mem.byte('wMenuCursorY')
                if cursor != target:
                    return Action('down' if cursor < target else 'up', 8, 40)
            return Action('a', 8, 40)
        return Action('a', 8, 24)

    @staticmethod
    def wild_shiny(snapshot):
        """The wild opponent is shiny. Trainers' Pokémon and a Ditto's borrowed look never count."""
        return getattr(snapshot, 'in_battle', 0) == 1 and bool(getattr(snapshot, 'enemy_shiny', False))

    def shiny_miss_reason(self, snapshot):
        """Why a wild shiny cannot be caught, in the words of the Red, Blue and Yellow notice."""
        if not snapshot.can_catch:
            return 'no storage space'
        if dict(snapshot.pockets['balls']).get(self.data.items['MASTER_BALL']):
            return 'only the Master Ball, kept for a legendary'
        return 'no balls'

    def static_legend(self, snapshot):
        """Lugia, Ho-Oh and Crystal's Tin Tower Suicune: catch rate 3, met once at a fixed spot."""
        return snapshot.enemy_species in {249, 250} or snapshot.enemy_species == 245 and self.data.game == 'crystal'

    def static_capture_move(self, snapshot, mem, mon):
        """Sleep first, then chip a sleeping legendary to half HP without the risk of a KO.

        In Gen II only sleep and freeze raise the catch chance (+10 on a catch rate of 3, against at
        most +3 for low HP), and paralysis would block sleep, so it is never used. Lugia and Ho-Oh
        open with Safeguard and cast it again as it ends, and an awake one Recovers any chip, so while
        Safeguard is up the balls wait: Disable the Safeguard, else chip or stall until it drops.
        """
        usable = [(index, self.data.moves.get(move, {})) for index, move in enumerate(mon.moves) if mon.pp[index]]
        status = mem.byte('wEnemyMonStatus')
        guarded = mem.byte('wEnemyScreens') & 4  # SCREENS_SAFEGUARD
        types = self.data.species[snapshot.enemy_species]['types']
        sleeper = not status and self.party_sleeper(snapshot)
        if not status and not guarded:
            sleep = [(entry['accuracy'], index) for index, entry in usable if entry.get('effect') == 'EFFECT_SLEEP'
                     and all(self.data.matchups.get((entry['type'], kind), 1) for kind in types)]
            if sleep:
                return max(sleep)[1]
            if sleeper:
                return None
        if guarded and sleeper:
            last = self.data.moves.get(mem.byte('wLastEnemyMove'), {}).get('effect')
            if last == 'EFFECT_SAFEGUARD' and not mem.byte('wEnemyDisableCount'):
                disable = next((index for index, entry in usable if entry.get('effect') == 'EFFECT_DISABLE'), None)
                if disable is not None:
                    return disable
        elif not status and any(self.data.moves.get(move, {}).get('effect') in {'EFFECT_HEAL', 'EFFECT_MORNING_SUN'}
                                for move in mem.read('wEnemyMonMoves', 4)):
            return None  # Recover undoes the chip, so throw.
        # Each sleep turn spent chipping is a throw lost (13/256 asleep), while half HP adds about 2/256
        # per throw, so chip only while plenty of sleep remains (the low bits count the turns left).
        if status and (snapshot.enemy_hp <= snapshot.enemy_max_hp // 2 or status & 0x07 < 3):
            return None
        if not status and not guarded and snapshot.enemy_hp <= snapshot.enemy_max_hp // 2:
            return None
        options = []
        for index, entry in usable:
            effect = entry.get('effect')
            if not entry.get('power'):
                if guarded and sleeper and ('_UP' in (effect or '') or effect == 'EFFECT_DEFENSE_CURL'):
                    options.append((0, 0, index))  # A harmless stall beats a 3/256 throw.
                continue
            hits = {'EFFECT_NORMAL_HIT': 1, 'EFFECT_FALSE_SWIPE': 1, 'EFFECT_DOUBLE_HIT': 2, 'EFFECT_MULTI_HIT': 5}.get(effect)
            if not hits:
                continue
            special = entry['type'] >= 20
            defense = mem.word('wEnemyMonSpclDef' if special else 'wEnemyMonDefense')
            attack = mon.stats[4 if special else 1]
            factor = 1.5 if entry['type'] in self.data.species[mon.species]['types'] else 1
            for kind in set(types):
                factor *= self.data.matchups.get((entry['type'], kind), 1)
            damage = (((2 * mon.level // 5 + 2) * entry['power'] * attack / max(1, defense)) / 50 + 2) * factor * hits
            # A critical hit doubles damage in Gen II; 2.5x leaves room for that and the top damage roll.
            if effect == 'EFFECT_FALSE_SWIPE':
                options.append((2, 0, index))
            elif 0 < damage * 2.5 < snapshot.enemy_hp:
                options.append((1, damage, index))
        return max(options)[2] if options else None

    def party_sleeper(self, snapshot):
        """Some healthy party Pokémon can still put the static legendary to sleep."""
        types = self.data.species[snapshot.enemy_species]['types']
        return any(mon.hp and not mon.egg and any(pp and self.data.moves.get(move, {}).get('effect') == 'EFFECT_SLEEP'
                                                  and all(self.data.matchups.get((self.data.moves[move]['type'], kind), 1)
                                                          for kind in types)
                                                  for move, pp in zip(mon.moves, mon.pp))
                   for mon in snapshot.party)

    LEARN_PROTECTED = LEARN_KEPT

    def learn_slot(self, mon):
        """The move slot a new level-up move replaces: the weakest unprotected one, or 'keep'."""
        if all(move in self.LEARN_PROTECTED for move in mon.moves):
            return 'keep'
        return min(range(4), key=lambda i: 999 if mon.moves[i] in self.LEARN_PROTECTED
                   else self.data.moves.get(mon.moves[i], {}).get('power', 0))

    def stance_flee(self, snapshot, mem, *, catch, shiny, escape):
        """Start running from this battle when the goal's stance says to flee, else None.

        The stance (planning/stance.py) decides from the goal's kind and the party's HP and PP. A
        failed run brings the FIGHT menu back, which counts one failed try. After ``FLEE_TRIES`` of
        them the battle is fought out.
        """
        if self.fleeing:
            # The FIGHT menu came back after a run attempt, so the escape failed.
            self.fleeing = False
            self.flee_tries += 1
            self.flees['failures'] += 1
        # A shiny the Bug-Catching Contest cannot catch is not a plain battle, and contest.control
        # owns it, so the stance sees no wild battle there.
        wild = snapshot.in_battle == 1 and (not shiny or catch or bool(self.shiny_missed))
        encounter = Encounter(wild=wild, wanted=catch, shiny=bool(self.shiny_missed), escape=escape,
                              tries=self.flee_tries)
        kind = getattr(self.goal, 'kind', STORY)
        from .ledger import battle_ledger
        books = battle_ledger(self.data)
        if stance(kind, encounter, books, goal=getattr(self.goal, 'key', kind),
                  resources=lambda: books.snapshot(snapshot)) is not FLEE:
            return None
        action = self.battle_task(Flee(), snapshot, mem)
        if action:
            self.fleeing = True
            self.flees['attempts'] += 1
        return action

    def battle_task(self, task, snapshot, mem):
        """Start a Core battle shortcut now, or return None when the game refused it recently."""
        if not self.allowed(task, snapshot) or mem.byte('wBattleType') == 3:
            # Battle type 3 is the catching tutorial, which takes no input from the player.
            return None
        self.menu = task
        button = self.menu_step(snapshot, mem)
        if button:
            return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
        if self.menu is task:
            self.menu = None
        return None

    def hopeless_battle(self, snapshot):
        """Whether a trainer battle under way can never be won.

        Nobody standing has an attack with PP that touches the foe, and each still has PP for some
        other move, so not even Struggle is left. A Vaporeon with only Rest and Growl left faced
        Lance's Gyarados this way, and Growl kept the foe from ever knocking it out. An Elixir in
        the bag would restore an attack, so the battle is not lost while one is there. A move that
        borrows another, like Transform or Metronome, may still bring an attack. A level 100 Ditto
        last in line at Koga was reloaded away before it could Transform, and once Transformed it
        was reloaded again for spending the copied attack, though Struggle was a few turns away.
        With no move that wins back HP the foe knocks everyone out in the end, so the battle ends in
        a loss. A Metapod with only Harden left at Falkner was reloaded back into the same battle.
        A healer the foe hits harder each turn than it heals is knocked out in the end too. A level 5
        Hoppip with Splash, Synthesis and Tail Whip, last in line at Chuck, was reloaded back into his
        Poliwrath's battle instead of blacking out and going to train.
        """
        if snapshot.in_battle != 2:
            return False
        from .champion_shop import elixir
        memory = getattr(self, 'memory', None)
        mem = Memory(memory, self.data) if memory is not None else None
        if mem is not None and mem.byte('wPlayerSubStatus5') & SUBSTATUS_TRANSFORMED:
            # A Transformed battler has five PP for each borrowed move, so Struggle is never far off.
            return False
        standing = [mon for mon in snapshot.party if mon.hp and not mon.egg]
        if not standing or any(not any(mon.pp) or elixir(self.data, snapshot, mon) for mon in standing):
            return False
        if not any(self.outlasts(snapshot, mem, mon) for mon in standing):
            return False
        return not any(pp and (self.move_score(move, mon, snapshot) > 0
                               or self.data.moves.get(move, {}).get('effect') in BORROWED_MOVES)
                       for mon in standing for move, pp in zip(mon.moves, mon.pp))

    def outlasts(self, snapshot, mem, mon):
        """Whether ``mon`` wins back more HP each turn than the foe's best hit takes from it.

        Rest heals fully and then sleeps two turns, so it wins back a third of the maximum each turn.
        Recover and the other full heals win back half, Morning Sun, Synthesis and Moonlight a quarter
        at least, and Leech Seed an eighth of the foe's maximum, unless the foe is Grass. Without the
        battle memory the foe's moves are unknown, so no healer counts and the battle timeout decides.
        A scenario asks before the policy's first step, when it holds no memory yet.
        """
        heals = [(move, self.data.moves[move]['effect']) for move, pp in zip(mon.moves, mon.pp)
                 if pp and self.data.moves.get(move, {}).get('effect') in HEALING_MOVES]
        if not heals or mem is None:
            return False
        stats = tuple(mem.word('wEnemyMon' + stat) for stat in ('MaxHP', 'Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef'))
        grass = GRASS in self.data.species.get(snapshot.enemy_species, {}).get('types', ())

        def heal(move, effect):
            if effect == 'EFFECT_LEECH_SEED':
                return 0 if grass else stats[0] / 8
            if effect == 'EFFECT_HEAL':
                return mon.max_hp / (3 if move == REST else 2)
            return mon.max_hp / 4
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level, stats=stats)
        target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
            enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
        hit = max((self.move_score(move, enemy, target) for move in mem.read('wEnemyMonMoves', 4)), default=0)
        return hit < max(heal(move, effect) for move, effect in heals)

    def move_choice(self, snapshot, mem, mon, opponent, weaken):
        """The move slot to use this turn, or None when no move has PP."""
        options = [(self.move_score(move, mon, opponent), index)
                   for index, move in enumerate(mon.moves) if move and mon.pp[index]
                   and not (mem.byte('wPlayerDisableCount') and move == mem.byte('wDisabledMove'))]
        if self.collection.get('tower'):
            reflected = {self.data.moves.get(move, {}).get('effect') for move in mem.read('wEnemyMonMoves', 4)}
            options = [(score * (0.1 if score < snapshot.enemy_hp
                        and ('EFFECT_COUNTER' if self.data.moves[mon.moves[index]]['type'] < 20
                             else 'EFFECT_MIRROR_COAT') in reflected else 1), index)
                       for score, index in options]
        if snapshot.in_battle == 2 and not self.collection.get('tower'):
            normal_available = any(self.data.moves.get(move, {}).get('type') == 0 and mon.pp[index]
                                   and self.move_score(move, mon, opponent) > 0
                                   for index, move in enumerate(mon.moves) if move)
            if normal_available:
                options = [(score * (0.25 if mon.pp[index] <= 5
                                    and self.data.moves[mon.moves[index]]['type'] != 0 else 1), index)
                           for score, index in options]
        recovery = self.recovery_move(snapshot, mem, mon, options) if self.collection.get('tower') else None
        poison = self.poison_move(snapshot, mem, mon, options) if self.collection.get('tower') else None
        for choice in (recovery, poison, weaken):
            if choice is not None:
                return choice
        return max(options)[1] if options else None

    def ball_labels(self, snapshot):
        from .quests import beasts_roaming, static_wanted
        master = ()
        if snapshot.enemy_species in {243, 244, 245, 249, 250, 251}:
            master = ('MASTER BALL',)
            # A static legend waits for its own room, so the roaming beasts keep the Master Ball.
            if self.static_legend(snapshot) and beasts_roaming(self, snapshot):
                master = ()
        elif self.wild_shiny(snapshot) and not beasts_roaming(self, snapshot) and not static_wanted(self, snapshot):
            # A shiny may have the Master Ball once every other ball is spent, as it may never be seen
            # again, but not while a legend still to catch needs it.
            master = ('MASTER BALL',)
        regular = ('ULTRA BALL', 'GREAT BALL', 'POKé BALL', 'LURE BALL', 'FAST BALL',
                   'HEAVY BALL', 'LEVEL BALL', 'LOVE BALL', 'FRIEND BALL', 'MOON BALL')
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        return master + regular if roaming else regular + master

    def long_odds(self, snapshot, mem, species, active, *, escape):
        """What a catch does when its battler cannot weaken the target and the next throw is under
        1 in 10 (planning.throws): the slot of a party member that can weaken it, LEAVE when nobody can
        and the target is untouched, or None to throw.

        A shiny, a legendary, a roamer, a one-time encounter and a contest catch always get throws, and
        so does a battle with no escape. So does a wild battle a map script started, which a run only
        meets again by talking to it, as the story does with the transmitter's Electrodes. Paralysis
        adds nothing to a Gen II throw, so a member that can only paralyze is not switched in for it.
        """
        from ..planning.throws import GEN2_BALLS, THROW_BAR, gen2_throw
        from .ledger import ONE_CHANCE
        if (self.wild_shiny(snapshot) or species in ONE_CHANCE or mem.byte('wStatusFlags2') & 4
                or mem.byte('wBattleScriptFlags') & SCRIPTED_BATTLE):
            return None
        held = {self.data.item_names.get(item, '').casefold() for item, count in snapshot.pockets['balls'] if count}
        ball = next((label for label in self.ball_labels(snapshot) if label.casefold() in held), None)
        if ball is None:
            return None
        rate, multiplier = self.data.species[species]['catch_rate'], GEN2_BALLS.get(ball, 1)
        chance = gen2_throw(rate, multiplier, snapshot.enemy_hp, snapshot.enemy_max_hp, mem.byte('wEnemyMonStatus'))
        if chance >= THROW_BAR:
            return None
        foe = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level,
            stats=tuple(mem.word('wEnemyMon' + stat) for stat in ('MaxHP', 'Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef')))
        attacks = [move for move in mem.read('wEnemyMonMoves', 4) if move]
        for slot, mon in enumerate(snapshot.party):
            if slot == active or mon.egg or mon.hp <= mon.max_hp // 2:
                continue
            # A member the target knocks out in one hit weakens nothing. A level 40 Ursaring on Route 28
            # knocked out three members of level 26 or less in turn, and the run then left it anyway.
            target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
                                     enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
            if max((self.move_score(move, foe, target) for move in attacks), default=0) >= mon.hp:
                continue
            move = self.capture_move(snapshot, mem, slot=slot)
            if move is not None and self.data.moves.get(mon.moves[move], {}).get('effect') != 'EFFECT_PARALYZE':
                return slot
        untouched = chance <= gen2_throw(rate, multiplier, snapshot.enemy_max_hp, snapshot.enemy_max_hp, 0)
        return LEAVE if escape and untouched else None

    def capture_move(self, snapshot, mem, slot=None):
        master = self.data.items['MASTER_BALL']
        if (dict(snapshot.pockets['balls']).get(master) and (self.ball_labels(snapshot)[0] == 'MASTER BALL'
                or not any(item != master and count for item, count in snapshot.pockets['balls']))):
            return None
        if not snapshot.party:
            return None
        mon = snapshot.party[min(mem.byte('wCurBattleMon') if slot is None else slot, len(snapshot.party) - 1)]
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        if roaming and mon.stats[3] // (4 if mon.status & 64 else 1) <= mem.word('wEnemyMonSpeed'):
            return None
        if roaming:
            # Beasts flee after a faster lead moves unless the lead has Mean Looked them or they sleep.
            # Sleep is also the only status that raises the Gen II catch rate, so never paralyze or hit.
            usable = [(index, self.data.moves.get(move, {})) for index, move in enumerate(mon.moves) if mon.pp[index]]
            if not mem.byte('wPlayerSubStatus5') & 128:
                trap = next((index for index, entry in usable if entry.get('effect') == 'EFFECT_MEAN_LOOK'), None)
                if trap is not None:
                    return trap
            if not mem.byte('wEnemyMonStatus'):
                sleep = [(entry['accuracy'], index) for index, entry in usable if entry.get('effect') == 'EFFECT_SLEEP'
                         and all(self.data.matchups.get((entry['type'], kind), 1)
                                 for kind in self.data.species[snapshot.enemy_species]['types'])]
                if sleep:
                    return max(sleep)[1]
            return None
        if self.static_legend(snapshot):
            return self.static_capture_move(snapshot, mem, mon)
        if not mem.byte('wEnemyMonStatus'):
            for index, move in enumerate(mon.moves):
                entry = self.data.moves.get(move, {})
                if (mon.pp[index] and entry.get('effect') in {'EFFECT_SLEEP', 'EFFECT_PARALYZE'}
                        and all(self.data.matchups.get((entry['type'], kind), 1)
                                for kind in self.data.species[snapshot.enemy_species]['types'])):
                    return index
        if snapshot.enemy_hp <= snapshot.enemy_max_hp // 2:
            return None
        options = []
        for index, move in enumerate(mon.moves):
            entry = self.data.moves.get(move, {})
            if not mon.pp[index] or not entry.get('power') or entry.get('effect') not in {'EFFECT_NORMAL_HIT', 'EFFECT_FALSE_SWIPE'}:
                continue
            special = entry['type'] >= 20
            defense = mem.word('wEnemyMonSpclDef' if special else 'wEnemyMonDefense')
            attack = mon.stats[4 if special else 1]
            factor = 1.5 if entry['type'] in self.data.species[mon.species]['types'] else 1
            for kind in set(self.data.species[snapshot.enemy_species]['types']):
                factor *= self.data.matchups.get((entry['type'], kind), 1)
            damage = (((2 * mon.level // 5 + 2) * entry['power'] * attack / max(1, defense)) / 50 + 2) * factor
            if entry.get('effect') == 'EFFECT_FALSE_SWIPE' or 0 < damage * 2.5 < snapshot.enemy_hp:
                options.append((damage, index))
        return max(options)[1] if options else None

    def battle_target(self, snapshot, mem):
        return SimpleNamespace(enemy_species=snapshot.enemy_species, enemy_level=snapshot.enemy_level,
            enemy_hp=snapshot.enemy_hp, enemy_defense=mem.word('wEnemyMonDefense'),
            enemy_special_defense=mem.word('wEnemyMonSpclDef'))

    def level_lead(self, snapshot):
        """Move the highest-level Pokémon to the front when the lead lags well behind it."""
        from .quests import beasts_roaming
        from .tower import holds_lead
        from .training import trainee_slot
        # Without an Exp. Share the partner in training leads instead, so it joins every battle.
        trainee = trainee_slot(self, snapshot)
        # The roaming-beast sleeper stays on record after the search is set aside for later, and the search
        # names it again when it resumes. On the training walk it would keep the trainee out of every battle.
        training = trainee is not None and self.goal is not None and self.goal.key == 'collection_train'
        # Once every beast is caught the search never runs again to clear its sleeper. Crystal kept a level 20
        # sleeper in front of a level 100 team, and each Sudowoodo return lost it in Victory Road and went back.
        if self.collection.get('roam_lead') and not beasts_roaming(self, snapshot):
            self.collection.pop('roam_lead')
        # A roaming-beast or static-legendary sleeper leads on purpose even when it is far below the rest of the
        # party, and so does the Tower team's chosen lead, which the Tower preparation would otherwise swap back.
        # The static-legendary sleeper also keeps the lead while the journey is still on the legendary quest
        # under another goal, and through a PC visit to free box slots, which comes and goes between quest steps.
        # Chaotic Escape swapped the sleeper and its level 100 lead back and forth for half an hour at a PC.
        sleeper = getattr(self, 'static_sleeper', None)
        storage = self.goal is not None and self.goal.key in {'collection_release', 'collection_box'}
        quest = getattr(self, 'legend_decision', None)
        questing = (quest is not None and quest == getattr(self, 'decisions', None) or storage) and not training
        if (self.collection.get('roam_lead') and not training or holds_lead(self)
                or self.goal and self.goal.key in {'legend_lugia', 'legend_ho_oh', 'legend_suicune', 'collection_static_lead'}
                or questing and sleeper and snapshot.party
                and (snapshot.party[0].trainer_id, tuple(snapshot.party[0].dvs)) == sleeper):
            return None
        if trainee is not None:
            mon = snapshot.party[trainee]
            return Lead(trainee, (mon.trainer_id, mon.dvs)) if trainee else None
        strongest = max((i for i, mon in enumerate(snapshot.party) if not mon.egg),
                        key=lambda i: snapshot.party[i].level, default=0)
        if not strongest or snapshot.party[strongest].level <= snapshot.party[0].level + 5:
            return None
        mon = snapshot.party[strongest]
        return Lead(strongest, (mon.trainer_id, mon.dvs))

    def trainee_switch(self, snapshot, active):
        """Swap a leading trainee for the strongest healthy partner when it would lose the battle.

        A switch comes before the opponent's move, and every Pokémon sent out shares the experience, so the
        trainee still levels without an Exp. Share. It only happens while the trainee is out, so it never repeats.
        """
        from .training import trainee_slot
        if active != trainee_slot(self, snapshot) or active >= len(snapshot.party):
            return None
        mon = snapshot.party[active]
        if mon.level >= snapshot.enemy_level + 5 and mon.hp * 2 > mon.max_hp:
            return None
        healthy = [i for i, row in enumerate(snapshot.party) if i != active and not row.egg and row.hp * 4 > row.max_hp]
        best = max(healthy, key=lambda i: snapshot.party[i].level, default=None)
        return best if best is not None and snapshot.party[best].level > mon.level else None

    def tower_switch(self, snapshot, mem, active):
        if active >= len(snapshot.party):
            return None
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level,
            stats=tuple(mem.word('wEnemyMon' + stat) for stat in ('MaxHP', 'Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef')))
        moves = mem.read('wEnemyMonMoves', 4)
        opponent = self.battle_target(snapshot, mem)
        rows = []
        for slot, mon in enumerate(snapshot.party):
            if not mon.hp or mon.egg:
                continue
            target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=mon.hp,
                enemy_defense=mon.stats[2], enemy_special_defense=mon.stats[5])
            received = max((self.move_score(move, enemy, target) for move in moves), default=0)
            dealt = max((self.move_score(move, mon, opponent) for move, pp in zip(mon.moves, mon.pp) if pp), default=0)
            rows.append((slot, received / mon.hp, dealt, received))
        current = next((row for row in rows if row[0] == active), None)
        if current is None:
            return None
        healing = any(self.data.moves.get(move, {}).get('effect') in {'EFFECT_HEAL', 'EFFECT_MORNING_SUN',
                      'EFFECT_MOONLIGHT', 'EFFECT_SYNTHESIS', 'EFFECT_REST'} for move in moves)
        if (healing and not mem.byte('wEnemyMonStatus') and 92 not in snapshot.party[active].moves
                and not {3, 9}.intersection(self.data.species[snapshot.enemy_species]['types'])
                and current[2] * 2 < snapshot.enemy_hp):
            poison = next((slot for slot, _, _, received in rows
                           if slot != active and {92, 105} <= set(snapshot.party[slot].moves)
                           and snapshot.party[slot].pp[snapshot.party[slot].moves.index(92)]
                           and snapshot.party[slot].hp > received * 2.25), None)
            if poison is not None:
                return poison
        if current[1] < 0.65:
            return None
        def speed(mon):
            return mon.stats[3] / (4 if getattr(mon, 'status', 0) & 64 else 1)
        if current[2] >= snapshot.enemy_hp and speed(snapshot.party[active]) >= enemy.stats[3]:
            return None
        candidates = []
        for slot, danger, dealt, received in rows:
            mon = snapshot.party[slot]
            margin = 1.25 if speed(mon) >= enemy.stats[3] else 2.25
            if (slot != active and danger < current[1] * 0.65 and mon.hp > received * margin
                    and dealt >= snapshot.enemy_hp * 0.15):
                candidates.append((dealt / max(1, snapshot.enemy_hp) - danger, slot))
        return max(candidates)[1] if candidates else None

    def poison_move(self, snapshot, mem, mon, options):
        if mem.byte('wEnemyMonStatus') or {3, 9}.intersection(self.data.species[snapshot.enemy_species]['types']):
            return None
        if max((score for score, _ in options), default=0) * 2 >= snapshot.enemy_hp:
            return None
        return next((i for i, move in enumerate(mon.moves) if mon.pp[i]
                     and self.data.moves.get(move, {}).get('effect') == 'EFFECT_TOXIC'
                     and any(index == i for _, index in options)), None)

    def recovery_move(self, snapshot, mem, mon, options):
        slot = next((i for i, move in enumerate(mon.moves) if mon.pp[i]
                     and self.data.moves.get(move, {}).get('effect') == 'EFFECT_HEAL'), None)
        if slot is None or mem.byte('wPlayerDisableCount') and mem.byte('wDisabledMove') == mon.moves[slot]:
            return None
        reflected = {self.data.moves.get(move, {}).get('effect') for move in mem.read('wEnemyMonMoves', 4)}
        attacks = [self.data.moves.get(move, {}) for move in mon.moves if self.data.moves.get(move, {}).get('power')]
        if (mem.byte('wEnemyMonStatus') & 8 and attacks
                and all(('EFFECT_COUNTER' if move['type'] < 20 else 'EFFECT_MIRROR_COAT') in reflected for move in attacks)):
            return slot
        hp, maximum = mem.word('wBattleMonHP'), mem.word('wBattleMonMaxHP')
        if not 0 < hp < maximum * 0.55 or max((score for score, _ in options), default=0) >= snapshot.enemy_hp:
            return None
        enemy = SimpleNamespace(species=snapshot.enemy_species, level=snapshot.enemy_level,
            stats=tuple(mem.word('wEnemyMon' + stat) for stat in ('MaxHP', 'Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef')))
        target = SimpleNamespace(enemy_species=mon.species, enemy_level=mon.level, enemy_hp=hp,
            enemy_defense=mem.word('wBattleMonDefense'), enemy_special_defense=mem.word('wBattleMonSpclDef'))
        damage = max((self.move_score(move, enemy, target) for move in mem.read('wEnemyMonMoves', 4)), default=0)
        return slot if damage < maximum / 2 else None

    def move_score(self, mid, mon, snapshot):
        move = self.data.moves.get(mid, {})
        power = move.get('power', 0)
        if not power:
            return 0
        kind = move['type']
        factor = 1
        for target_type in set(self.data.species.get(snapshot.enemy_species, {}).get('types', [])):
            factor *= self.data.matchups.get((kind, target_type), 1)
        if not factor:
            return 0
        accuracy = move.get('accuracy', 100) / 100
        effect = move.get('effect')
        if effect == 'EFFECT_STATIC_DAMAGE':
            return power * accuracy
        if effect == 'EFFECT_LEVEL_DAMAGE':
            return mon.level * accuracy
        if effect == 'EFFECT_SUPER_FANG':
            return getattr(snapshot, 'enemy_hp', 0) / 2 * accuracy
        attack = mon.stats[1 if kind < 20 else 4]
        if kind < 20 and getattr(mon, 'status', 0) & 16:
            attack /= 2
        enemy = self.data.species.get(snapshot.enemy_species, {}).get('stats', [50] * 6)
        defense = getattr(snapshot, 'enemy_defense' if kind < 20 else 'enemy_special_defense', None)
        if defense is None:
            defense = (enemy[2 if kind < 20 else 5] + 8) * 2 * getattr(snapshot, 'enemy_level', mon.level) / 100 + 5
        stab = 1.5 if kind in self.data.species[mon.species]['types'] else 1
        score = ((2 * mon.level / 5 + 2) * power * attack / max(1, defense) / 50 + 2) * factor * stab * accuracy
        if effect == 'EFFECT_MULTI_HIT':
            score *= 3
        if effect in {'EFFECT_DOUBLE_HIT', 'EFFECT_POISON_MULTI_HIT'}:
            score *= 2
        if move.get('effect') in {'EFFECT_EXPLOSION', 'EFFECT_SELFDESTRUCT'}:
            score *= 0.1
        if move.get('effect') in {'EFFECT_RECHARGE', 'EFFECT_RAZOR_WIND', 'EFFECT_SOLARBEAM'}:
            score *= 0.5
        return score
