"""An objective-driven policy that observes the game after every action."""
import random
from collections import Counter
from dataclasses import asdict

from pokecore.shortcuts import (BuyItem, ChangeBox, ChooseMove, DepositPokemon, FieldMove, LearnMove, ReleasePokemon,
                                    ReorderParty, RunAway, SellItem, SwitchPokemon, UseItem, WithdrawPokemon, item_kind)

from .base import Action, Policy
from ..planning.ledger import box_wanted
from pokecore.textmatch import ScreenText
from .battle import (BALLS, CURES, HEALING, HOPELESS, W_BATTLE_MON, W_ENEMY_MON, Decision, choose_battle,
                     healing_item, needs_healing, ranked_moves, read_battler, replacement_slot, useful_capture)
from .navigation import DIRS, PAIR_COLLISIONS, WATER_TILESETS, Navigator
from .naming import NamingController
from .pickups import Pickups, ground_item
from .puzzles import MANSION_MAPS, VICTORY_MAPS, BoulderPlanner, MansionPlanner, open_switches, seafoam_current_task
from .move_development import hm_upgrade, move_name
from .progression import GAME_STARTERS, STARTERS, YELLOW, Goal, healing_goal, journey, league_partner, milestones, story_goal
from . import training
from .menus import select, tap
from .shopping import ShoppingController
from .storage import FIELD_MOVE_GOALS
from .storage import StorageController
from .collection import CENTERS, EXPECTED_FRAMES, Collection, LEAGUE, SUPPORT_TRIPS, legendary_project, snorlax_project
from ..planning import values
from ..planning import arbiter
from ..planning.arbiter import Candidate, Tier
from ..planning.monitor import STOOD_DOWN
from ..planning.stance import FLEE_TRIES, STORY, TRAIN
from .awareness import ActionWatch
from .team import development_candidate, potential, readiness, reserve_to_deposit, storage_headroom
from ..screen import Screen, W_PLAYER_MON_NUMBER
from ..ram import W_TILEMAP
from ..strategy_data import ITEMS, MAPS, MOVES, SPECIES, WORLD, event_set
from ..pc_list import guarded
from ..shortcuts import ShortcutRunner, gen1_ui
from .. import config

EXPLORATION_CHANCE = 0.12
# A trip to buy a TM or Champion shop supplies is expected to take 20000 frames. It is dropped once it
# spent three times that, counted only while the trip is under way, without the item.
TM_TRIP_FRAMES = 20000
# Teaching an owned HM takes only menus. Red's seeded batch taught Strength in 1250 frames.
TEACH_FRAMES = 1250
# The HMs whose battle moves ``hm_upgrade`` weighs, Surf and Strength.
HM_TEACH_ITEMS = frozenset((ITEMS['HM03'], ITEMS['HM04']))
# A development excursion lasts until its partner gains a level. It ends sooner once this many frames
# pass without the partner gaining any experience, so grass without encounters cannot hold it.
DEVELOPMENT_STALL = 2400

W_WALK_COUNTER = 0xCFC5
W_FACING = 0xC109
W_WHICH_POKEMON = 0xCF92
W_MOVE_NUM = 0xD0E0
W_REPEL_STEPS = W_MOVE_NUM - 5  # wRepelRemainingSteps precedes the four-byte wMoves array
FACING = {"down": 0, "up": 4, "left": 8, "right": 12}
HM_ITEM_MOVES = {ITEMS[f'HM0{number}']: move for number, move in zip(range(1, 6), (15, 19, 57, 70, 148))}


def ready_to_climb(snapshot):
    """True once Victory Road 2F's own boulder is on its switch and 3F's work is outstanding.

    The mirror of ready_to_drop. Without it the ascent overrides whatever the run actually came
    here for — a standing encounter, an unbeaten trainer — with "climb to 3F", which cannot be
    routed from the entrance pocket, so the run shuttles back out to Route 23 and returns.
    """
    return (event_set(snapshot.event_flags, "EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH1")
            and not event_set(snapshot.event_flags, "EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2"))


def ready_to_drop(snapshot):
    """True once Victory Road 3F's own boulder sits on its switch and 2F's still does not.

    Without the first half the two Victory Road goals mirror each other — 2F sends the run up to
    3F, 3F sends it straight back down — and it rides the ladder forever while everything else,
    including healing a hurt party, is starved.
    """
    return (event_set(snapshot.event_flags, "EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2")
            and not event_set(snapshot.event_flags, "EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2"))


def wait():
    return [Action(None, 0, 12)]


def individual(mon):
    """Enough to tell two party members of one species apart for the length of a menu."""
    return mon.species, mon.level, mon.nick, mon.max_hp, tuple(mon.moves)


# The frames of a short errand such as a Pokémon Center visit, a shop trip, a pickup or a passage that
# unblocks the goal behind it. An errand cutting into another one under way pays these frames again.
ERRAND_FRAMES = 3000
# The kind of a goal, by key prefix, in the order they are tried. Each kind's candidate is built once,
# here, and the arbiter weighs it against the others. The first match wins.
GOAL_KINDS = (('heal', 'heal'), ('party_collection', 'collection'), ('party_league', 'collection'),
              ('party_', 'party'), ('teach_', 'moves'), ('buy_tm', 'moves'), ('restock', 'supplies'),
              ('collect_plan', 'plan'), ('collect_pickup', 'pickup'), ('collect_passage', 'passage'),
              ('hideout_elevator', 'passage'), ('collect_', 'collection'), ('catch_', 'catch'))
# Short goals that serve the goal behind them.
ERRANDS = frozenset(('heal', 'party', 'moves', 'supplies', 'pickup', 'passage', 'trash'))
# Goals that pick the party members they need, so no party upgrade cuts into them.
OWNS_PARTY = frozenset(('collection', 'catch', 'plan'))


def goal_kind(key):
    return next((kind for prefix, kind in GOAL_KINDS if key.startswith(prefix)), 'story')


def goal_candidate(goal, collection, kind=None):
    """The arbiter's candidate for ``goal``.

    A collection goal stands for the project the collection pick chose, with that candidate's tier,
    value and frames. The plan placeholder is worth nothing, so any real goal beats it. A story goal is
    worth a new entry in the story tier until the Champion is beaten. An errand is short upkeep.
    """
    key = goal.key
    kind = kind or goal_kind(key)
    if kind == 'collection':
        shadow = collection.shadow
        project = collection.project or {}
        inner = (shadow.picked.get('collection') if shadow.last.get('collection') == project.get('key')
                 else shadow.built.get('collection', {}).get(project.get('key'))) if project else None
        if inner:
            return Candidate(key, inner.tier, inner.value, inner.expected_frames, goal=kind)
        return Candidate(key, Tier.PROGRESS, values.SMALL, EXPECTED_FRAMES['other'], goal=kind)
    if kind == 'plan':
        return Candidate(key, Tier.FILLER, 0.0, ERRAND_FRAMES, goal=kind)
    if kind in ERRANDS:
        return Candidate(key, Tier.UPKEEP, values.SMALL, ERRAND_FRAMES, goal=kind)
    tier = Tier.PROGRESS if collection.completed_champion else Tier.STORY
    return Candidate(key, tier, values.NEW_ENTRY, EXPECTED_FRAMES['other'], goal=kind)


class Choice:
    """The goal sources of one overworld decision, weighed on the arbiter.

    ``pick`` is the best candidate offered so far and ``goal`` its goal. Each source offers its goal as a
    candidate, and the arbiter keeps the better of it and the pick. A failed precondition, such as a
    hurt party or a full box, cannot be weighed: the goal behind it cannot run until it is met, so its
    enabler replaces the pick. ``candidates`` lists what was weighed since the last replacement, so its
    arbiter pick is always ``pick``.
    """

    def __init__(self, goal, candidate):
        self.goal, self.pick = goal, candidate
        self.candidates = [candidate]

    @property
    def kind(self):
        return self.pick.goal

    @property
    def errand(self):
        """Whether the pick is an errand, which nothing short cuts into."""
        return self.kind in ERRANDS

    @property
    def owns_party(self):
        return self.kind in OWNS_PARTY

    def errand_candidate(self, key, kind, frames=ERRAND_FRAMES):
        """An errand that serves the pick. It takes the pick's tier and value, at least a small one, so it
        goes before the longer pick. It pays an errand's frames again to cut into another errand."""
        held = self.pick
        return Candidate(key, held.tier, max(held.value, values.SMALL), frames,
                         interrupt_frames=ERRAND_FRAMES if self.errand else 0.0, goal=kind)

    def wins(self, candidate):
        """Whether ``candidate`` would replace the pick. A goal under the pick's own key is its update.

        Nothing cuts into an errand under way except a step of the same errand. Only a failed
        precondition, through ``replace``, puts another goal first.
        """
        if candidate.key == self.pick.key:
            return True
        if self.errand:
            return candidate.goal == self.kind
        return arbiter.choose([self.pick, candidate]) is candidate

    def offer(self, goal, candidate):
        """Offer ``goal`` as ``candidate`` and return the goal the arbiter keeps. An errand under way
        weighs nothing but its own steps, so any other offer is left out of ``candidates``."""
        if self.wins(candidate):
            self.candidates.append(candidate)
            self.goal, self.pick = goal, candidate
        elif not self.errand:
            self.candidates.append(candidate)
        return self.goal

    def replace(self, goal, candidate):
        """Put ``goal`` first, as the enabler of a failed precondition."""
        self.goal, self.pick = goal, candidate
        self.candidates = [candidate]
        return goal


class StrategicPolicy(Policy):
    name = "strategic"

    @property
    def shadow(self):
        """The shadow arbiter, which the collection holds so that it outlives a reload."""
        collection = getattr(self, 'collection', None)
        return getattr(collection, 'shadow', None)

    def __init__(self, seed=None, starter=None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.naming = NamingController(seed)
        self.nav = Navigator()
        self.mode = "boot"
        self.goal = Goal("boot", "Start the adventure", "Wait for the game to become ready")
        self.reason = self.goal.reason
        self.completed = {}
        self.recoveries = 0
        self.decisions = 0
        self.journey = []
        self.interactions = {}
        self.interaction_count = 0
        self.collection = Collection()
        self.collection.trade_preferences = lambda: self.trade_preferences() if hasattr(self, 'trade_preferences') else {}
        choices = random.Random(f'{seed}:adventure-choices') if seed is not None else random.Random()
        self.fossil = choices.choice(('HELIX_FOSSIL', 'DOME_FOSSIL'))
        self.collection.eevee_choice = choices.choice((134, 135, 136))
        self.collection.dojo_choice = choices.choice((106, 107))
        self.pickups = Pickups()
        self.personality = self.rng.choice(('Sociable', 'Collector', 'Explorer'))
        self.starter_setting = starter if starter is not None else config.STARTER
        if self.starter_setting not in (*GAME_STARTERS, 'random'):
            raise ValueError('Unknown starter choice')
        # A separate draw preserves the existing naming and navigation sequences.
        self.starter = random.Random(seed).choice(STARTERS) if self.starter_setting == 'random' else self.starter_setting
        if YELLOW:
            self.starter = GAME_STARTERS[0]
        self.starter_confirmed = False
        self.history = []
        self.failures = {}
        self.readiness = {}
        self.next_goal = None
        self.tm_moves = {}
        self.tm_compatible = {}
        self.shop_offers = set()
        self.map_view = None
        self.escape_attempted = False
        self.shortcut = ShortcutRunner()
        # Run attempts the battle stance made over the whole run, which the replay audit reads.
        self.flees = Counter()
        self.on_restore()

    def reset(self):
        moves, compatible = self.tm_moves, self.tm_compatible
        self.__init__(self.seed, self.starter_setting)
        self.tm_moves, self.tm_compatible = moves, compatible

    @property
    def hopeless_battle(self):
        """The battle under way cannot end, so waiting out the battle timeout gains nothing."""
        return bool(self.intent and self.intent.reason == HOPELESS)

    def on_restore(self):
        self.collection.last_frame = None
        self.nav.restore()
        self.mansion = MansionPlanner()
        self.boulders = BoulderPlanner()
        self.intent = None
        self.intent_since = 0
        self.shortcut.cancel()
        self.mem = None
        self.sp = None
        self.last_kind = None
        self.last_signature = None
        self.unchanged_since = None
        self.confirming = None
        self.used_status = set()
        self.battle_key = None
        self.turns = 0
        self.last_switch_turn = -5
        self.catch_attempts = 0
        # Failed stance runs in this battle, and whether one is under way.
        self.flee_tries, self.fleeing = 0, False
        self.heal_latch = False
        self.shop = ShoppingController()
        self.pc = StorageController()
        # The spare the run lets go next as (box, position). Trading never offers it.
        self.release_spare = None
        self.pending_trade_key = None
        self.goal_attempts = 0
        self.observed_map = None
        self.settle_until = 0
        self.recovery_until = 0
        self.progress_frame = None
        self.progress_goal = None
        self.progress_targets = None
        self.goal_distance = None
        self.elevator_exit = False
        self.elevator_floor = "B1F"
        self.trash_checked = set()
        self.trash_pending = None
        self.trash_first = None
        self.social_target = None
        self.next_conversation = 0
        self.watch = ActionWatch()
        self.last_action = None
        self.excursion = None
        # The partner a development excursion trains, with its level and experience at the start and the
        # frame it last gained experience.
        self.development = None
        self.development_cooldown = 0
        self.development_index = None
        self.assessment_token = None
        self.menu_context = None
        self.pending_social = None
        self.supply_attempts = set()
        # The HM teach last scored, and the party and HMs it was scored for.
        self.hm_token = None
        self.hm_option = None
        self.tm_plan = None
        self.tm_frame = None
        # The TM and supply options last scored, and the party, bag and purse they were scored for.
        self.tm_token = None
        self.tm_options = None
        # The step's choice, which the overworld chain goes on weighing.
        self.choice = None

    def describe(self):
        return f"strategic ({self.mode})"

    def details(self):
        return {"collection": self.collection.details(), "objective": self.goal.to_dict(), "action": self.mode, "reason": self.reason,
                "milestones": self.completed.copy(), "recoveries": self.recoveries,
                "decisions": self.decisions, "visited_tiles": len(self.nav.visits),
                "journey": self.journey,
                "interactions": self.interaction_count,
                "personality": self.personality, "next": self.next_goal,
                "starter": self.starter, "starter_confirmed": self.starter_confirmed,
                "fossil": self.fossil,
                "pickups": self.pickups.state_dict(),
                "readiness": self.readiness, "history": self.history[-8:],
                "expectation": self.watch.expected['label'] if self.watch.expected else None,
                "map": self.map_view,
                "route": [list(target) for _, _, target in list(self.nav.path)[:24]]}

    def state_dict(self):
        return {"version": 1, "collection": self.collection.state_dict(), "navigation": self.nav.state_dict(), "rng": self.rng.getstate(),
                "recoveries": self.recoveries, "decisions": self.decisions,
                "naming": self.naming.state_dict(),
                "interactions": list(self.interactions), "interaction_count": self.interaction_count,
                "personality": self.personality, "history": self.history[-8:], "failures": self.failures,
                "starter": self.starter, "starter_confirmed": self.starter_confirmed,
                "fossil": self.fossil,
                "pickups": self.pickups.state_dict(), "escape_attempted": self.escape_attempted}

    def load_state_dict(self, data):
        if data.get("version") != 1:
            return
        self.collection.load(data.get("collection", {}))
        self.fossil = data.get('fossil', self.fossil)
        self.escape_attempted = bool(data.get('escape_attempted', False))
        if self.fossil not in ('HELIX_FOSSIL', 'DOME_FOSSIL'):
            self.fossil = 'HELIX_FOSSIL'
        self.pickups.load(data.get('pickups', {}))
        self.nav.load_state_dict(data.get("navigation", {}))
        self.naming.load_state_dict(data.get("naming", {}))
        self.interactions = {key: True for key in data.get("interactions", [])}
        self.interaction_count = data.get("interaction_count", len(self.interactions))
        self.personality = data.get('personality', self.personality)
        # Earlier policies always chose Bulbasaur. Do not reroll an old lab checkpoint.
        self.starter = data.get('starter', GAME_STARTERS[0])
        if self.starter not in GAME_STARTERS:
            self.starter = GAME_STARTERS[0]
        self.starter_confirmed = bool(data.get('starter_confirmed', False))
        self.history = data.get('history', [])[-8:]
        self.failures = dict(list(data.get('failures', {}).items())[-128:])
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, (list, tuple)) else value
        if "rng" in data:
            self.rng.setstate(tuples(data["rng"]))
        self.recoveries = data.get("recoveries", 0)
        self.decisions = data.get("decisions", 0)
        self.on_restore()

    def _select(self, scr, target, one_based=False, scroll=False):
        return select(scr, target, one_based, scroll)

    def step(self, ctx):
        s, mem = ctx.snapshot, ctx.mem
        scr = Screen(mem)
        kind = scr.kind(s)
        frame = s.frame
        pos = (s.map, s.x, s.y)
        self.decisions += 1
        # PC transfers briefly combine a new partner with the old slot's level.
        # Accept training gains in battle or after returning to the overworld.
        # A release visit to the PC is storage work, so its frames do not count against the project.
        # Nor do the heals, restocks and box changes the project needs, or the walk back from them.
        self.collection.observe(s, overworld=kind == 'overworld',
                                suspended=self.pickups.active is not None or self.tm_plan is not None
                                or self.goal.key == 'party_release',
                                support=self.goal.key in SUPPORT_TRIPS,
                                training_ready=bool(s.in_battle) or kind == 'overworld',
                                training_active=(self.goal.key == 'collect_train' and not self.heal_latch
                                                 and not needs_healing(s.party)
                                                 and (bool(s.in_battle) or kind == 'overworld' and pos in self.goal.targets)))
        self.pickups.observe(s, self.collection.elapsed)
        if self.collection.completed_champion and s.map == MAPS['HALL_OF_FAME']:
            self.goal = Goal('collect_ceremony','Celebrate the Champion victory','Finish the ceremony and continue the saved adventure')
            self.mode = 'Hall of Fame ceremony'
            self.reason = self.goal.reason
            return tap('a',6,24)
        if self.pending_social:
            key, started = self.pending_social
            if kind == 'dialogue' or s.in_battle:
                if key not in self.interactions:
                    self.interactions[key] = True
                    self.interaction_count += 1
                self.pending_social = None
            elif frame - started > 240:
                self.pending_social = None
        naming_action = self.naming.step(scr, s)
        if naming_action is not None:
            self.mode = "naming"
            self.reason = f"Enter {self.naming.target}" if self.naming.target else "Choose a random name"
            self.confirming = None
            self.intent = None
            self.shortcut.cancel()
            return [naming_action]
        self.mem, self.sp = mem, ctx.sp
        if self.release_changed(s):
            return tap('b')
        if self.shortcut.active:
            actions = self.shortcut.step(mem, self._ui(), frame)
            if actions:
                self.mode = f'shortcut: {self.shortcut.machine.kind}'
                self.reason = self.shortcut.purpose
                self.confirming = None
                self.last_kind = 'shortcut'
                self.last_action = (pos, actions[0].button)
                return actions
            if self.intent and self.shortcut.last.completed:
                # The game took the battle decision. The turn that follows can run past the
                # pending limit with knockouts, switches and level ups, and that is not a stuck action.
                self.intent_since = None
        if s.map != self.observed_map:
            self.observed_map = s.map
            self.settle_until = frame + 60
        world = WORLD.get(s.map)
        outside_map = (self.nav.use_world and world and not s.in_battle
                       and not (0 <= s.x < world["width"] and 0 <= s.y < world["height"]))
        if frame < self.settle_until or outside_map:
            # Poison can faint a partner between stepping over an edge and loading
            # the next map. Dismiss its text without recording temporary coordinates.
            if frame >= self.settle_until and outside_map and kind == 'dialogue':
                self.mode = 'dialogue'
                self.reason = 'Dismiss the message so the map transition can finish'
                return tap('b', 6, 24)
            self.mode = "waiting for map transition"
            return wait()
        self.completed = milestones(s)
        self.nav.update_story(s)
        if not s.in_battle and kind == "overworld":
            self.nav.update_live(s, mem)
        if s.party and not self.starter_confirmed and not YELLOW:
            families = {STARTERS[(d - 1) // 3] for d in s.owned if 1 <= d <= 9}
            if len(families) == 1:
                self.starter = families.pop()
            self.starter_confirmed = True
        # The story, the collection plan, the project under way and the errands under way are candidates.
        # Collection projects only start once the Champion is beaten, so the story and a project never
        # meet: the story is the pick until then and inside the League, and the plan placeholder after.
        if self.collection.completed_champion and s.map not in LEAGUE:
            base = Goal('collect_plan', 'Plan the next adventure project',
                        'Choose a collecting, evolution, training, or exploration objective')
        else:
            base = story_goal(s, self.starter, self.fossil) if s.started else self.goal
        choice = Choice(base, goal_candidate(base, self.collection))
        if self.collection.project and s.map not in LEAGUE:
            project_goal = self.collection.goal(s)
            if project_goal:
                # The collection weighed the project against the plan when it committed it, so the
                # project under way is the pick, as before, even in a test that starts one early.
                choice.replace(project_goal, goal_candidate(project_goal, self.collection, 'collection'))
        if self.pickups.active and s.map not in LEAGUE:
            choice.offer(self.pickups.goal(self.pickups.active), choice.errand_candidate('collect_pickup', 'pickup'))
        if self.pc.species:
            if any(p.species == self.pc.species for p in s.party) or self.pc.destination is None:
                self.pc.species = None
                self.pc.destination = None
            else:
                # The swap is under way, and the reserve it withdraws is the one the goal behind it needs.
                choice.replace(Goal('party_upgrade', 'Bring a stronger reserve onto the team',
                                    'Swap an underused reserve for a useful Pokémon already in storage',
                                    ((self.pc.destination, 13, 4),), 'up', True),
                               choice.errand_candidate('party_upgrade', 'party'))
        self.goal = choice.goal
        self.next_goal = self.goal.to_dict()
        league_rooms = {MAPS[n] for n in ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM')}
        withdrawing_partner = (
            self.goal.key == 'party_collection' and len(s.party) < 6
            and self.collection.project
            and any(species == self.collection.project['parent'] for species, level in s.boxed_pokemon)
        ) or (
            self.goal.key == 'party_league' and len(s.party) < 6
            and self.collection.project
            and len(self.collection.partner_matches(s, self.collection.project)) == 1
        ) or (
            # The field-move partner may sit in a full box. Making room first would switch away from
            # it again, and the two storage goals would trade boxes forever.
            self.goal.key in FIELD_MOVE_GOALS and len(s.party) < 6
            and self.pc.field_move_box(s, self.goal.key) is not None
        )
        # A release visit under way keeps going to the refill mark, so the next catch does not send the
        # run back to the PC for one more slot.
        release = self._release_target(s) if box_wanted(storage_headroom(s), self.release_spare is not None) else None
        self.release_spare = release
        if release and not withdrawing_partner and s.map not in league_rooms:
            # Room to catch is a precondition of every catch, so its enabler replaces the pick.
            self.pc.species = None
            self.pc.destination = None
            self.goal = choice.replace(Goal('party_release', 'Make room in storage',
                                            'Let a spare duplicate go so there is room for new catches',
                                            CENTERS, 'up', True), choice.errand_candidate('party_release', 'party'))
        elif s.box_full and not withdrawing_partner and s.next_free_box is not None and s.map not in league_rooms:
            self.pc.species = None
            self.pc.destination = None
            self.goal = choice.replace(Goal('party_box', 'Make room for new catches',
                                            f'Box {s.active_box + 1} is full. Visit a PC and switch to Box '
                                            f'{s.next_free_box + 1}', CENTERS, 'up', True),
                                       choice.errand_candidate('party_box', 'party'))
        self.choice = choice
        token = (s.badges, tuple((p.species, p.level, p.hp, p.status, p.moves, p.pp) for p in s.party), s.items)
        if s.party and token != self.assessment_token:
            self.readiness = readiness(s)
            self.assessment_token = token
        if world:
            self.map_view = {'id': s.map, 'name': s.map_name, 'width': world['width'], 'height': world['height'],
                             'player': [s.x, s.y], 'tiles': world['tiles'], 'passable': world['passable'],
                             'tileset': world['tileset'], 'warps': [w[:2] for w in world['warps']]}
        self.journey = journey(s, self.goal.key)
        self.mode = kind
        self.reason = self.goal.reason
        if s.in_battle:
            self.progress_frame = frame
        signature = (pos, kind, scr.text, scr.menu_index, scr.scroll, s.in_battle,
                     tuple((p.hp, p.status, p.pp) for p in s.party), s.items, s.event_flags)
        if signature != self.last_signature:
            self.unchanged_since = frame
        self.last_signature = signature
        if self.confirming:
            expected, sent = self.confirming
            if expected == signature and frame - sent < 48:
                return wait()
            self.confirming = None
        if not s.in_battle and mem[0xD736] & 0x80:
            self.mode = "riding the arrow tiles"
            self.progress_frame = frame
            return wait()
        walking = bool(mem[W_WALK_COUNTER]) and not s.in_battle
        self.nav.observe(pos, frame, walking, interrupted=kind != "overworld" or bool(s.in_battle))
        if walking and kind == "overworld":
            return wait()
        walking_state = mem[0xD700] | ((mem[0xD728] & 1) << 2)
        failure = self.watch.observe(s, kind, scr.cursor, walking_state,
                                     self.goal.key.startswith(('train_', 'catch_', 'collect_hunt', 'collect_train')) or self.developing)
        if failure:
            self._remember_failure(s, failure)
            self.intent = None
            self.excursion = None
            self.watch = ActionWatch()
            self.watch.last_failure = s.frame
            if kind != 'overworld':
                return tap('b')
            return self._recover(s)
        if self.intent and self.intent_since is not None and frame - self.intent_since > 900:
            self.intent = None
            self.recoveries += 1
            self.reason = "The action did not complete, return to a known menu"
            return tap("b") if kind != "overworld" else wait()
        if self.unchanged_since is not None and frame - self.unchanged_since > 1800:
            self.recoveries += 1
            self.intent = None
            self.unchanged_since = frame
            self.reason = "No progress detected, retry from a known state"
            if kind not in ("overworld", "dialogue", "naming"):
                return tap("b")
        actions = self._dispatch(s, scr, kind, mem)
        self.last_action = (pos, actions[0].button)
        if self.shortcut.active:
            # The shortcut verifies its own effect, so no menu watch or confirmation applies.
            self.last_kind = 'shortcut'
            return actions
        if not s.in_battle and self.watch.expected is None and actions[0].button == 'a' and kind not in ('dialogue', 'overworld', 'naming'):
            self.watch.begin('menu', 'Open the selected menu or advance its choice', s, kind)
        if actions[0].button == "a" and kind not in ("dialogue", "overworld", "naming"):
            self.confirming = (signature, frame)
        self.last_kind = kind
        return actions

    def _dispatch(self, s, scr, kind, mem):
        text = ScreenText(scr.text.upper())
        active = min(mem[W_PLAYER_MON_NUMBER], max(0, len(s.party) - 1))
        if kind == "yes_no":
            decision = self.pc.confirmation(s, scr, text, self.goal.key, self.collection.project,
                                            self._preferences(), self.menu_context, self.collection)
            if decision is not None:
                return self._menu_decision(decision, s)
            if self.goal.key == 'collect_trade' and getattr(self, 'pending_trade_key', None):
                choices = self.trade_preferences() if hasattr(self, 'trade_preferences') else {}
                if choices.get(self.pending_trade_key, {}).get('state') in ('locked', 'offered'):
                    return self._select(scr, 1)
            if "CHANGE" in text and "MON" in text:
                return self._select(scr, 1)
            if "ABANDON" in text or "STOP LEARNING" in text:
                return self._select(scr, 0)
            if "DELETE" in text or "FORGET" in text or "LEARN" in text:
                learner = min(mem[W_WHICH_POKEMON], max(0, len(s.party) - 1))
                slot = replacement_slot(s.party[learner], mem[W_MOVE_NUM]) if s.party else None
                return self._learn(s, slot) or self._select(scr, 0 if slot is not None else 1)
            return self._select(scr, 0)
        if kind == 'prize':
            return self._select(scr,2) if self.goal.key == 'collect_prize' else tap('b')
        if kind == "heal":
            self.reason = "Restore the whole party at the Pokémon Center"
            return self._select(scr, 0)
        if kind == "learn_move":
            learner = min(mem[W_WHICH_POKEMON], max(0, len(s.party) - 1))
            slot = replacement_slot(s.party[learner], mem[W_MOVE_NUM]) if s.party else None
            self.reason = "Keep useful coverage and protect HM moves"
            return self._learn(s, slot) or (tap("b") if slot is None else self._select(scr, slot))
        if not s.in_battle:
            self.used_status.clear()
            self.battle_key = None
            self.turns = 0
            self.catch_attempts = 0
            self.last_switch_turn = -5
            self.flee_tries, self.fleeing = 0, False
        if kind == "safari":
            missing = SPECIES.get(s.enemy_species, {}).get('dex') not in s.owned
            targeted = self.collection.repeat_target(s.enemy_species, s.map) == s.enemy_species
            if not s.can_catch or not (s.enemy_shiny or missing or targeted or useful_capture(s, s.enemy_species, s.enemy_level)):
                self.reason = ('Leave the encounter because the party and active box are full' if not s.can_catch
                               else 'Leave an unnecessary duplicate already covered by the collection')
                if scr.top_x != 13:
                    return tap('right')
                return self._select(scr, 1)
            self.reason = "Use Safari Balls in the Safari Zone"
            if scr.top_x != 1:
                return tap("left")
            return self._select(scr, 0)
        if kind == "battle":
            me, enemy = read_battler(mem, W_BATTLE_MON), read_battler(mem, W_ENEMY_MON)
            if s.in_battle == 1 and not s.enemy_shiny and SPECIES.get(enemy.species, {}).get('dex') in getattr(self.collection, 'closed_legendaries', ()):
                self.reason = 'This legendary return was already caught. Wait for the next walking milestone'
                return self._run(s) or self._fight(s, me, enemy)
            key = (s.enemy_species, s.enemy_level, enemy.max_hp)
            if key != self.battle_key:
                self.used_status.clear()
                self.catch_attempts = 0
                self.battle_key = key
                self.flee_tries, self.fleeing = 0, False
            if self.last_kind not in ("battle", None):
                self.intent = None
                self.turns += 1
            if self.intent and self.intent.kind == "fight" and not me.pp[self.intent.index]:
                self.intent = None
            if self.intent is None and self.fleeing:
                # The battle menu came back after a stance run, so the escape failed.
                self.fleeing = False
                self.flee_tries += 1
                self.flees['failures'] += 1
            if self.intent is None:
                self.intent = choose_battle(s, me, enemy, active, self.used_status,
                                            self.turns - self.last_switch_turn >= 3, self.catch_attempts,
                                            {'catch_cut': 15, 'catch_surf': 57, 'catch_strength': 70}.get(self.goal.key), collect_missing=True,
                                            capture_species=self.collection.project['species']
                                            if legendary_project(self.collection.project) else None,
                                            repeat_species=self.collection.repeat_target(enemy.species, s.map),
                                            training_index=self.collection.trainee(s, self.collection.project)
                                            if self.collection.project and self.collection.project['method'] == 'train' else None,
                                            kind=getattr(self.goal, 'kind', STORY), flee_tries=self.flee_tries)
                self.intent_since = s.frame
            self.mode = f"battle: {self.intent.kind}"
            self.reason = self.intent.reason
            return self._battle_shortcut(s, me, enemy)
        if kind in ("moves", "item_moves", "pause", "item_action", "quantity"):
            # Core shortcuts open these menus themselves. One left open is closed before the next request.
            return tap("b")
        if kind == "party":
            project = self.collection.project
            if (not s.in_battle and self.goal.key == 'collect_trade' and project
                    and s.map == project['map'] and self.intent is None):
                from ..trade.preferences import identity
                partner = self.collection.trade_candidate(s, project)
                target = partner.get('party_index') if partner else None
                if target is None:
                    return tap('b')
                actions = self._select(scr, target)
                if actions[0].button == 'a':
                    self.pending_trade_key = identity(asdict(s.party[target]))
                return actions
            if not s.in_battle:
                return tap("b")
            alive = [(p.hp, i) for i, p in enumerate(s.party) if p.hp and i != active]
            if not alive and s.party and s.party[active].hp:
                # The last partner standing cannot switch to itself. The game answers
                # "is already out!" and reopens this menu, so close it and fight on.
                self.reason = "No other partner can battle, so keep fighting"
                self.intent = None
                return tap("b")
            target = max(alive)[1] if alive else active
            actions = self._start_shortcut(s, SwitchPokemon(target), ('switch', target, self.battle_key, self.turns),
                                           'Replace the fainted active Pokémon')
            if actions:
                self.last_switch_turn = self.turns
                return actions
            # The game cannot leave a forced switch with B, so pick the partner by hand when Core declines.
            return self._select(scr, target)
        if kind == "party_action":
            # Only the forced-switch fallback above reaches this menu, where SWITCH is the first entry.
            return self._select(scr, 0) if s.in_battle else tap("b")
        if kind == 'shop':
            self.menu_context = 'shop'
            self.intent = None
            return self._menu_decision(self.shop.step(s, self.goal.key, self.collection.project), s)
        if kind == "elevator":
            target = 2 if self.elevator_floor == "B4F" else 0
            if scr.menu_index + scr.scroll == target:
                self.elevator_exit = True
            return self._select(scr, target, scroll=True)
        if kind == "vending":
            return self._select(scr, 0) if self.goal.key == "guard_drink" else tap("b")
        if kind == "list":
            if self.goal.key == 'collect_fossil' and self.menu_context != 'shop':
                fossils = [item for item in ('DOME_FOSSIL','HELIX_FOSSIL','OLD_AMBER') if dict(s.items).get(ITEMS[item])]
                desired = self.collection.project.get('item') if self.collection.project else None
                return self._select(scr,fossils.index(desired) if desired in fossils else 0,scroll=True)
            return tap("b")
        if kind in ('pc_root', 'change_box', 'pc'):
            self.menu_context = 'pc'
            return self._menu_decision(self.pc.step(s, scr, kind, self.goal.key,
                                                  self.collection.project, self._preferences(), self.collection), s)
        if kind == "dialogue":
            if self.intent and self.intent.kind == "fight" and ("DISABLED" in text or "NO PP" in text):
                self.intent = None
            if self.goal.key.startswith('collect_') or self.collection.completed_champion and s.map in LEAGUE:
                self.reason = 'Advance the collection interaction'
                return tap('a',6,24)
            self.reason = "Advance dialogue and wait for the next decision"
            accepting = scr.shop or any(row.strip("? ") == "HEAL" for row in scr.rows)
            return tap("a" if accepting or self.shop.selling or self.intent or s.in_battle or s.playtime_seconds == 0 or "EVOLV" in text or "WHAT?" in text else "b", 6, 24)
        if s.in_battle:
            return wait()
        if not s.started or (s.playtime_seconds == 0 and not s.party):
            return tap("a", 6, 24)
        return self._overworld(s, mem)

    def _overworld(self, s, mem):
        self.menu_context = None
        self.intent = None
        self.shop.leave_menu()
        pos = (s.map, s.x, s.y)
        if needs_healing(s.party):
            self.heal_latch = True
        if all(p.hp == p.max_hp and not p.status for p in s.party) and not needs_healing(s.party):
            self.heal_latch = False
            self.escape_attempted = False
        league_rooms = {MAPS[n] for n in ("LORELEIS_ROOM", "BRUNOS_ROOM", "AGATHAS_ROOM", "LANCES_ROOM", "CHAMPIONS_ROOM")}
        in_league = s.map in league_rooms
        choice = self.choice
        if choice is None or choice.goal is not self.goal:
            choice = Choice(self.goal, goal_candidate(self.goal, self.collection))
        self.choice = None
        if self.heal_latch and not in_league:
            choice.replace(healing_goal(s), choice.errand_candidate('heal', 'heal'))
        swap = choice.errand_candidate('party_upgrade', 'party')
        if (not s.box_full and not self.heal_latch and not choice.owns_party and choice.wins(swap)
                and 'Pokecenter' in WORLD.get(s.map, {}).get('name', '') and WORLD[s.map]['width'] == 14):
            weakest = reserve_to_deposit(s)
            if weakest is not None:
                p = s.party[weakest]
                upgrades = [(potential(sid, s.party) + level * 10, sid) for sid, level in s.boxed_pokemon
                            if level >= max(mon.level for mon in s.party) * 0.5
                            and not any(mon.species == sid for mon in s.party)]
                if upgrades and max(upgrades)[0] > potential(p.species, [mon for i, mon in enumerate(s.party) if i != weakest]) + p.level * 10 + 80:
                    self.pc.species = max(upgrades)[1]
                    self.pc.destination = s.map
                    choice.offer(Goal('party_upgrade', 'Bring a stronger reserve onto the team',
                                      'Swap an underused reserve for a useful Pokémon already in storage',
                                      ((s.map, 13, 4),), 'up', True), swap)
        goal = choice.goal
        if in_league:
            for target in sorted(range(len(s.party)), key=lambda i: s.party[i].level, reverse=True):
                mon = s.party[target]
                if mon.level < 35:
                    continue
                for item, qty in s.items:
                    if qty and mon.hp == 0 and item in (ITEMS["REVIVE"], ITEMS["MAX_REVIVE"]):
                        actions = self._use_item(s, item, target)
                        if actions:
                            return actions
                if mon.hp > 0:
                    depleted = any(move and not pp and MOVES.get(move, {}).get("power")
                                   for move, pp in zip(mon.moves, mon.pp))
                    if depleted:
                        for item, qty in s.items:
                            if qty and item in (ITEMS["ELIXER"], ITEMS["MAX_ELIXER"]):
                                actions = self._use_item(s, item, target)
                                if actions:
                                    return actions
                    choices = [(min(mon.max_hp - mon.hp, amount), item) for item, amount in HEALING.items()
                               if any(mid == item and qty for mid, qty in s.items)
                               and (mon.hp < mon.max_hp * 0.8 or mon.status & CURES.get(item, 0))]
                    if choices:
                        actions = self._use_item(s, max(choices)[1], target)
                        if actions:
                            return actions
        # A bag this full cannot take a new kind of item, Poké Balls included, so spend the vitamins and
        # Rare Candies that fill it, whether or not a collection project is under way.
        if len(s.items) >= 18:
            for item,qty in s.items:
                if item not in {ITEMS[n] for n in ('RARE_CANDY','HP_UP','PROTEIN','IRON','CARBOS','CALCIUM')}:
                    continue
                candidates = [i for i,p in enumerate(s.party) if p.level<100]
                if not candidates:
                    continue
                parent = (self.collection.project or {}).get('parent')
                target = next((i for i in candidates if s.party[i].species==parent),max(candidates,key=lambda i:s.party[i].level))
                signature = (item,qty,s.party[target].species,s.party[target].level)
                if signature not in self.supply_attempts:
                    self.supply_attempts.add(signature)
                    actions = self._use_item(s, item, target)
                    if actions:
                        return actions
        supplies = self.shop.plan(s, goal, self.collection.project, requested_goal=self.goal.key,
                                  healing=self.heal_latch, in_league=in_league,
                                  has_pokedex=self.completed.get('pokedex', False),
                                  completed_champion=self.collection.completed_champion)
        if supplies.goal is not goal:
            # The shop plans a restock only for supplies the goal cannot go on without.
            goal = choice.replace(supplies.goal, choice.errand_candidate(supplies.goal.key, 'supplies'))
        if supplies.prepared and self.collection.project:
            self.collection.project['supplies_prepared'] = True
        if supplies.abandon:
            self.collection.abandon(supplies.abandon)
        if self.heal_latch:
            # Medicine is useful when no known route to a center can be followed.
            for target, mon in enumerate(s.party):
                index = healing_item(s.items, mon)
                if index is not None and (mon.status & 8 or mon.hp < mon.max_hp * 0.25):
                    actions = self._use_item(s, s.items[index][0], target, "Treat the party before walking farther")
                    if actions:
                        return actions
        if not self.heal_latch and not in_league:
            upgrade = self._hm_option(s)
            if upgrade:
                _, target, item, move, _ = upgrade
                mon = s.party[target]
                attempt = ('hm', item, target, individual(mon))
                teach = Goal('teach_battle', f'Teach {move_name(move)}',
                             f'Improve {mon.nick or mon.name} using an owned HM')
                # Each teach is tried once for a party member and its moves, so one that fails does not
                # start again until the moves change.
                if attempt not in self.supply_attempts and choice.offer(teach, self.teach_candidate(choice, upgrade)) is teach:
                    self.supply_attempts.add(attempt)
                    self.goal = teach
                    self.reason = teach.reason
                    actions = self._use_item(s, item, target)
                    if actions:
                        return actions
        goal, tm_action = self._tm_development(s, goal, in_league, choice)
        if tm_action:
            return tm_action
        if goal.key == "thunder" and not event_set(s.event_flags, "EVENT_2ND_LOCK_OPENED"):
            goal = choice.replace(self._trash_goal(s), choice.errand_candidate('trash', 'trash'))
        if not self.heal_latch and not in_league and not choice.errand:
            # The collection pick weighs its own projects on the arbiter against the goal it is handed, and
            # commits the one it picks, so its pick is taken as it is. An errand under way is never handed
            # to it.
            collection_goal = self.collection.choose(s, self.nav, self.rng, goal)
            if collection_goal:
                collection_kind = goal_kind(collection_goal.key)
                candidate = (choice.errand_candidate(collection_goal.key, collection_kind) if collection_kind in ERRANDS
                             else goal_candidate(collection_goal, self.collection, 'collection'))
                if choice.kind not in ('collection', 'plan'):
                    self.next_goal = goal.to_dict()
                goal = choice.replace(collection_goal, candidate)
        # A legendary or a marathon under way loses its run when it leaves, so no pickup cuts into one.
        committed = legendary_project(self.collection.project) or (self.collection.project or {}).get('method') == 'marathon'
        pickup_errand = choice.errand_candidate('collect_pickup', 'pickup')
        if not self.heal_latch and not in_league and not committed and choice.wins(pickup_errand):
            pickup = self.pickups.choose(s, self.nav, goal, self.collection.elapsed)
            if pickup:
                self.next_goal = goal.to_dict()
                goal = choice.offer(pickup, pickup_errand)
        # A plan made north of Victory Road cannot reach most of Kanto, so the passage replaces it.
        # North means no route to the southern entrance through the gates open now.
        south = ((MAPS['ROUTE_23'], 8, 138),)
        if goal.key == 'collect_plan' and (
                s.map in VICTORY_MAPS or s.map in (MAPS['INDIGO_PLATEAU'], MAPS['ROUTE_23'])
                and self.nav.open_route(s, south) is None):
            goal = choice.replace(Goal('collect_passage', 'Return to Kanto for another expedition',
                                       'Solve the remaining passage puzzles and leave through the southern entrance',
                                       south),
                                  choice.errand_candidate('collect_passage', 'passage'))
        if s.map in (MAPS["ROCKET_HIDEOUT_ELEVATOR"], MAPS["CELADON_MART_ELEVATOR"], MAPS["SILPH_CO_ELEVATOR"]):
            rocket_lift = s.map == MAPS["ROCKET_HIDEOUT_ELEVATOR"]
            if self.elevator_exit and not rocket_lift:
                self.mode = "leaving the elevator"
                return tap("left" if s.x > 1 else "down", 8, 12)
            if self.elevator_exit:
                self.mode = "leaving the elevator"
                return tap("left" if s.x > 2 else "right" if s.x < 2 else "up", 8, 12)
            self.elevator_floor = "B4F" if goal.key == "hideout_elevator" else "B1F"
            # Inside a lift, the only way on is to ride it.
            goal = choice.replace(Goal("hideout_elevator", "Use the Rocket Hideout elevator",
                                       f"Select {self.elevator_floor} and leave the lift",
                                       ((s.map, 1, 2) if rocket_lift else (s.map, 3, 1),), "up", True),
                                  choice.errand_candidate('hideout_elevator', 'passage'))
        else:
            self.elevator_exit = False
        shadow = self.shadow
        if shadow is not None and shadow.changed('overworld', (goal.key, (self.collection.project or {}).get('key'))):
            shadow.compare('overworld', lambda: list(choice.candidates), goal.key, outer=True)
        self.goal = goal
        if self.next_goal and self.next_goal['id'] == goal.key:
            next_badge = next((row['title'] for row in self.journey if not row['done']), 'Celebrate the Champion victory')
            self.next_goal = {'id': 'milestone', 'title': next_badge}
        self.reason = goal.reason
        if self.progress_goal != goal.key or self.progress_targets != frozenset(goal.targets):
            # This local navigation timer supplements the expedition's cumulative idle budget.
            # A goal that keeps its key but moves its targets starts over too. The Fighting Dojo gift
            # first walks to the Karate Master and then to a ball, and the distance kept from the first
            # leg made the timer run out on arrival at the ball, so recovery pressed A beside it.
            self.progress_goal = goal.key
            self.progress_targets = frozenset(goal.targets)
            self.progress_frame = s.frame
            self.goal_distance = None
        if goal.key == 'collect_plan':
            self.mode = 'exploring between expeditions'
            self.watch.expected = None
            options = [(dr, target) for dr, target in self.nav.neighbors(pos, s.frame)
                       if target[0] not in LEAGUE]
            if not options:
                return wait()
            direction = min(options, key=lambda option: self.nav.visits.get(option[1], 0))[0]
            self.nav.issued(pos, direction, s.frame)
            return tap(direction, 8, 12)
        if goal.key == "champion":
            self.mode = "continuing after the Champion"
            self.reason = "Finish the Hall of Fame ceremony and continue the saved adventure"
            if s.map == MAPS['CHAMPIONS_ROOM']:
                from .progression import at
                goal = at('collect_ceremony','Enter the Hall of Fame','Finish the Champion ceremony','HALL_OF_FAME',4,6)
                self.goal = goal
            elif s.map in LEAGUE:
                return tap('a',6,24)
            else:
                self.reason = 'Explore while preparing the next collection expedition'
                return self._recovery_step(s)
        if s.frame < self.recovery_until:
            return self._recovery_step(s)
        project = self.collection.project
        if goal.key == 'collect_evolve' and project:
            target = self.collection.trainee(s, project)
            if target is not None:
                return self._use_item(s,ITEMS[project['evolution']['requirement']],target) or tap('b')
        if goal.key == 'collect_train' and project:
            target = self.collection.trainee(s, project)
            if target and s.party[target].hp:
                actions = self._reorder(s, target, 'Train a partner toward level 100')
                if actions:
                    return actions
        if goal.key == 'collect_hunt' and project and pos in goal.targets:
            if project['method']=='fish':
                direction = goal.facing_at(pos)
                if mem[W_FACING] != FACING[direction]:
                    return tap(direction,4,12)
                return self._use_item(s,ITEMS[project['rod']]) or tap('b')
        if goal.key in ("teach_cut", "teach_surf", "teach_strength"):
            hm, move = {"teach_cut": ("HM01", 15), "teach_surf": ("HM03", 57),
                        "teach_strength": ("HM04", 70)}[goal.key]
            candidates = [i for i, p in enumerate(s.party) if move in SPECIES.get(p.species, {}).get("hms", [])
                          and (0 in p.moves or replacement_slot(p, move) is not None)]
            if candidates:
                target = max(candidates, key=lambda i: s.party[i].level)
                action = self._use_item(s, ITEMS[hm], target)
                if action:
                    return action
            self.reason = "Explore for a partner that can learn the required field move"
            return self._recover(s)
        if (WORLD.get(s.map, {}).get('name', '').endswith('Gym') or in_league) and not goal.key.startswith(('heal', 'restock', 'collect_', 'train_', 'catch_', 'party_', 'teach_')):
            target = self.readiness.get('lead', 0)
            if target and target < len(s.party) and s.party[target].hp:
                actions = self._reorder(s, target, 'Lead with the best available matchup')
                if actions:
                    return actions
        if legendary_project(self.collection.project) and goal.key == 'collect_static':
            target = max((i for i, mon in enumerate(s.party) if mon.hp and any(
                MOVES.get(mid, {}).get('power') and pp for mid, pp in zip(mon.moves, mon.pp))),
                key=lambda i: s.party[i].level, default=0)
            if target != 0:
                actions = self._reorder(s, target, 'Lead the legendary expedition with a strong partner')
                if actions:
                    return actions
        if (legendary_project(self.collection.project) and goal.key == 'collect_static'
                and WORLD.get(s.map, {}).get('symbol', '').startswith('CERULEAN_CAVE')
                and not mem[W_REPEL_STEPS]):
            repel = next((ITEMS[name] for name in ('MAX_REPEL', 'SUPER_REPEL', 'REPEL')
                          if dict(s.items).get(ITEMS[name])), None)
            if repel is not None:
                action = self._use_item(s, repel)
                if action:
                    return action
        if not goal.key.startswith(("collect_", "party_collection", "party_league")) and (goal.key == "train_league_partner" or self.development_index is not None and self.developing):
            target = league_partner(s) if goal.key == 'train_league_partner' else self.development_index
            if target is not None and target != 0:
                actions = self._reorder(s, target, "Give the partner the lead position while training")
                if actions:
                    return actions
        if goal.key == 'collect_seafoam_current' and s.map == MAPS['SEAFOAM_ISLANDS_B3F']:
            task = seafoam_current_task(s, self.nav)
            direction = self.boulders.route(s, self.nav, task) if task else None
            if direction:
                if not mem[0xD728] & 1:
                    target = next((i for i, p in enumerate(s.party) if 70 in p.moves), None)
                    actions = self._field(s, 'STRENGTH', target, 'Use Strength to slow the Seafoam current')
                    if actions:
                        return actions
                self.mode = 'moving a boulder to slow the current'
                self.reason = 'Clear space and push the designated boulders into both holes'
                self.progress_frame = s.frame
                return tap(direction, 16, 16)
        if s.map in VICTORY_MAPS:
            # Every expedition must use currently open gates before assuming
            # another floor's puzzle can be solved along the route.
            direction = self.nav.open_route(s, goal.targets)
            if direction is not None:
                return self._move(s, mem, direction)
            at_goal = pos in goal.targets
            switches = open_switches(s)

            def push(direction):
                # Plan the push before reaching for Strength. A boulder in another section of the
                # floor is only reachable by ladder, so there is no push to make from here, and
                # activating Strength first opened the menu on every step without moving anything.
                if not mem[0xD728] & 1:
                    target = next((i for i, p in enumerate(s.party) if 70 in p.moves), None)
                    actions = self._field(s, 'STRENGTH', target, 'Use Strength to move the boulder')
                    if actions:
                        return actions
                self.mode = "moving a boulder onto the switch"
                self.reason = "Find legal pushes and keep room to walk around the boulder"
                self.progress_frame = s.frame
                return tap(direction, 16, 16)
            # Any loose boulder can go on any open switch, so a return trip that reaches the
            # second switch or the hole first solves it first, and a boulder in the way of every
            # switch is pushed aside before one of them.
            task, direction = self.boulders.switch_push(s, self.nav) if not at_goal else (None, None)
            if direction:
                return push(direction)
            if goal.key.startswith('collect_') and not at_goal and not direction:
                # Reach a puzzle from its accessible ladder instead of repeatedly
                # following an optimistic route through another floor's closed gate.
                targets = (((MAPS['VICTORY_ROAD_3F'], 23, 7), (MAPS['VICTORY_ROAD_3F'], 27, 15))
                           if s.map == MAPS['VICTORY_ROAD_2F'] else
                           ((MAPS['VICTORY_ROAD_2F'], 22, 16),) if s.map == MAPS['VICTORY_ROAD_3F'] else ())
                north_maps = LEAGUE | {MAPS['INDIGO_PLATEAU'], MAPS['INDIGO_PLATEAU_LOBBY']}
                southbound = goal.key == 'collect_passage' or bool(goal.targets) and all(
                    m not in VICTORY_MAPS | north_maps and (m != MAPS['ROUTE_23'] or y >= 40)
                    for m, x, y in goal.targets)
                if southbound:
                    # Once a switch opens the next pocket, continue toward the
                    # southern exit instead of returning through a solved section.
                    onward = ((MAPS['VICTORY_ROAD_1F'], 1, 1) if s.map == MAPS['VICTORY_ROAD_2F']
                              else (MAPS['VICTORY_ROAD_2F'], 1, 1) if s.map == MAPS['VICTORY_ROAD_3F'] else None)
                    if onward is not None:
                        targets = (onward, *targets)
                # Prefer the ladder into the upper puzzle whenever it is reachable.
                # The nearer east ladder otherwise undoes the lower switch detour.
                for target in targets:
                    direction = self.nav.open_route(s, (target,))
                    if direction is not None:
                        return self._move(s, mem, direction)
            if not at_goal and goal.targets:
                # Returning from the Plateau enters the east corridor of the third floor, where a
                # loose boulder walls off every ladder that leads on. Push one aside to reach one.
                task, direction = self.boulders.exit_push(s, self.nav, goal.targets)
                if direction:
                    return push(direction)
            upper_ladder = ((MAPS["VICTORY_ROAD_3F"], 23, 7),)
            # Reentry can strand the party beyond the lower switch. Reach the upper
            # puzzle by ladder when the lower boulder and the destination are inaccessible.
            upper_detour = (switches and not direction and pos not in goal.targets
                            and s.map == MAPS["VICTORY_ROAD_2F"]
                            and not event_set(s.event_flags, 'EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2')
                            and self.nav.route(pos, goal.targets, s.frame) is None
                            and self.nav.route(pos, upper_ladder, s.frame) is not None)
            if not at_goal and s.map == MAPS["VICTORY_ROAD_2F"] and (ready_to_climb(s) or upper_detour):
                goal = Goal("victory_ascent", "Reach the upper boulder puzzle", "Climb to the third floor", ((MAPS["VICTORY_ROAD_3F"], 23, 7),))
            elif not at_goal and s.map == MAPS["VICTORY_ROAD_3F"] and ready_to_drop(s):
                goal = Goal("victory_drop", "Follow the boulder downstairs", "Drop through the hole to reach the final switch", ((MAPS["VICTORY_ROAD_2F"], 22, 16),))
        if pos in goal.targets:
            if legendary_project(project) and goal.key == 'collect_static' and (
                    not s.can_catch or not dict(s.items).get(ITEMS['MASTER_BALL'])
                    and dict(s.items).get(ITEMS['ULTRA_BALL'], 0) < 5):
                self.collection.abandon('Prepare capture supplies and storage before starting the legendary battle')
                self.goal = Goal('collect_plan', 'Prepare another expedition', 'Make room and restock before returning')
                return wait()
            if goal.key == "snorlax" or goal.key == 'collect_static' and snorlax_project(project):
                action = self._use_item(s, ITEMS["POKE_FLUTE"])
                if action:
                    return action
            if goal.interact:
                self.mode = "interacting"
                if s.frame - self.progress_frame > 1200:
                    return self._recover(s)
                facing = goal.facing_at(pos)
                if mem[W_FACING] != FACING[facing]:
                    return tap(facing, 4, 12)
                if goal.key == "surge_switches":
                    self.trash_pending = self.trash_target
                return tap("a")
            if goal.key.startswith(("train_", "catch_", "collect_hunt", "collect_train")):
                self.mode = "training"
                options = [(dr, q) for dr, q in self.nav.neighbors(pos, s.frame) if q in goal.targets]
                direction = self.rng.choice(options)[0] if options else self.nav.explore(pos, s.frame, self.rng)
            else:
                return wait()
        else:
            if goal.key not in ("heal", "restock", "buy_tm"):
                social = None if goal.key.startswith(("collect_", "party_collection", "party_league")) else self._purposeful_detour(s, mem, goal)
                if social:
                    return social
                social = None if goal.key == 'collect_pickup' or (self.collection.project or {}).get('method') in ('train', 'marathon') or legendary_project(self.collection.project) else self._social_interaction(s, mem)
                if social:
                    return social
            curiosity = 0 if goal.key in ("heal", "restock", "buy_tm", "collect_pickup", "collect_hunt") or (self.collection.project or {}).get('method') in ('train', 'marathon') or legendary_project(self.collection.project) else EXPLORATION_CHANCE
            if s.map in MANSION_MAPS:
                direction = self.mansion.route(s, goal.targets, self.nav)
                if direction == "switch":
                    self.mode = "using the statue switch"
                    return tap("up", 4, 12) if mem[W_FACING] != FACING["up"] else tap("a")
            else:
                # Route 23 is the way into Victory Road, and a search from here assumes each floor's
                # boulder switch can be solved on the way. Inside, the run follows only open gates, so
                # a nearer target past an unsolved switch sent it in and straight back out, again and
                # again. Take the same open route here and keep the hopeful one for when none exists.
                direction = (self.nav.open_route(s, goal.targets)
                             if s.map == MAPS['ROUTE_23'] and goal.targets else None)
                if direction is None:
                    direction = self.nav.guided(pos, goal.targets, s.frame, self.rng, curiosity) if goal.targets else None
            self.mode = "following objective"
            path = self.mansion.path if s.map in MANSION_MAPS else self.nav.path
            remaining = len(path) if path else None
            if path:
                training.route_progress(self.collection.project, goal.key, path[-1][2], len(path))
            project = self.collection.project
            expedition = project and (legendary_project(project) or project.get('event_return')
                                      or project.get('method') == 'fossil')
            if (expedition and goal.key.startswith('collect_') and remaining is not None
                    and remaining < project.get('closest_distance', float('inf'))):
                project['closest_distance'] = remaining
                self.collection.idle_frames = 0
            if remaining is not None and (self.goal_distance is None or remaining < self.goal_distance):
                self.goal_distance = remaining
                self.progress_frame = s.frame
            if direction is None:
                self.mode = "exploring obstacle"
                self.reason = "The route is blocked or unknown, explore and learn a reachable path"
                direction = self.nav.explore(pos, s.frame, self.rng)
                # A Center that cannot be routed to is not worth insisting on: the run flees every
                # battle while it holds the heal goal, so it can neither heal nor black out, and a
                # blackout is itself the game's way back to a Center. Play on with who is standing.

            if s.frame - self.progress_frame > 2400:
                return self._recover(s)
        return self._move(s, mem, direction)

    def _move(self, s, mem, direction):
        """Follow one route step, opening field-move menus when needed."""
        pos = (s.map, s.x, s.y)
        dx, dy = DIRS[direction]
        world = WORLD.get(s.map, {})
        tree = self.nav._tile(world, s.x + dx, s.y + dy) if world else None
        live_tile = mem[W_TILEMAP + (9 + dy * 2) * 20 + 8 + dx * 2]
        if world.get("name", "").startswith("SilphCo") and live_tile in (0x18, 0x24, 0x5E):
            if any(item == ITEMS["CARD_KEY"] and qty for item, qty in s.items):
                self.mode = "unlocking a door"
                return tap(direction, 4, 12) if mem[W_FACING] != FACING[direction] else tap("a")
        if self.nav.can_surf and world.get("tileset") in WATER_TILESETS and tree in (0x14, 0x32, 0x48) and mem[0xD700] != 2:
            here = mem[W_TILEMAP + 9 * 20 + 8]
            ts = world["tileset"]
            if (live_tile not in (0x14, 0x32, 0x48)
                    or (ts, here, live_tile) in PAIR_COLLISIONS
                    or (ts, live_tile, here) in PAIR_COLLISIONS):
                self.nav.blocked[(pos, direction)] = s.frame + 600
                self.nav.path.clear()
                self.reason = "Find a shoreline at the same elevation as the water"
                return wait()
            if mem[W_FACING] != FACING[direction]:
                return tap(direction, 4, 12)
            target = next(i for i, p in enumerate(s.party) if 57 in p.moves)
            return (self._field(s, 'SURF', target, 'Use Surf to cross the water', direction,
                                'Surf was rejected at this shoreline')
                    or self._avoid(s, direction, 'Find another shoreline after Surf was refused'))
        if self.nav.can_cut and ((world.get("tileset") == "OVERWORLD" and tree == 0x3D)
                                 or (world.get("tileset") == "GYM" and tree == 0x50)):
            # Read the visible tile so a tree removed on this visit is not cut repeatedly.
            live_tile = mem[W_TILEMAP + (9 + dy * 2) * 20 + 8 + dx * 2]
            if live_tile == tree:
                if mem[W_FACING] != FACING[direction]:
                    return tap(direction, 4, 12)
                target = next(i for i, p in enumerate(s.party) if 15 in p.moves)
                return (self._field(s, 'CUT', target, 'Use Cut to open the route', direction,
                                    'Cut did not clear the tree')
                        or self._avoid(s, direction, 'Find another way around the tree after Cut was refused'))
        self.nav.issued(pos, direction, s.frame)
        self.watch.begin('move', f'Move {direction} or cross into the next area', s, pos)
        return tap(direction, 8, 12)

    def _trash_goal(self, snapshot):
        opened = event_set(snapshot.event_flags, "EVENT_1ST_LOCK_OPENED")
        if self.trash_pending is not None:
            last = self.trash_pending
            self.trash_pending = None
            if opened:
                self.trash_first = last
            elif self.trash_first is not None:
                self.trash_first = None
                self.trash_checked.clear()
            else:
                self.trash_checked.add(last)
        cans = [(1 + 2 * (i // 3), 7 + 2 * (i % 3)) for i in range(15)]
        if opened and self.trash_first is not None:
            x, y = cans[self.trash_first]
            options = [i for i, (tx, ty) in enumerate(cans) if abs(tx - x) + abs(ty - y) == 2]
        else:
            options = [i for i in range(15) if i not in self.trash_checked]
        if not options:
            self.trash_checked.clear()
            options = list(range(15))
        if getattr(self, "trash_target", None) not in options:
            self.trash_target = self.rng.choice(options)
        x, y = cans[self.trash_target]
        approaches = tuple((MAPS["VERMILION_GYM"], x - dx, y - dy, dr) for dr, (dx, dy) in DIRS.items())
        return Goal("surge_switches", "Open the gym’s electric barriers",
                    "Search the trash cans, then try a neighboring can when the first switch opens",
                    tuple(p[:3] for p in approaches), "up", True, approaches=approaches)

    def _menu_decision(self, decision, s):
        if decision.reason is not None:
            self.reason = decision.reason
        if decision.supplies_prepared and self.collection.project:
            self.collection.project['supplies_prepared'] = True
        if decision.request:
            return self._request(s, decision.request, decision.reason or self.reason) or decision.actions
        return decision.actions

    def _request(self, s, request, purpose):
        """Run a mart or PC request from a menu controller as a Core shortcut."""
        operation, *args = request
        if operation == 'buy':
            machine, key = BuyItem(*args), ('buy', s.map, args[0])
        elif operation == 'sell':
            machine, key = SellItem(*args), ('sell', s.map, args[0])
        elif operation == 'deposit':
            machine, key = DepositPokemon(*args), ('deposit', individual(s.party[args[0]]))
        elif operation == 'withdraw':
            machine, key = WithdrawPokemon(*args), ('withdraw', s.active_box, *args, len(s.party))
        elif operation == 'change_box':
            machine, key = ChangeBox(*args), ('change_box', *args)
        elif operation == 'release':
            machine, key = ReleasePokemon(*args, allow_release=True), ('release', s.active_box, *args)
            self.release_start = (s.active_box, self._box_count(s))
        else:
            raise ValueError(f'Unsupported menu request: {operation}')
        return self._start_shortcut(s, machine, key, purpose)

    def _preferences(self):
        return self.trade_preferences() if hasattr(self, 'trade_preferences') else {}

    def _shopping_item(self, snapshot, stock):
        return self.shop.item_for(snapshot, stock, self.goal.key, self.collection.project)

    def _release_target(self, snapshot):
        # A release that just failed is skipped until its retry time, so another spare goes first
        # instead of the same menu failing again and again.
        # Without the stack pointer a nickname can stop the PC list short of a slot, so that slot waits too.
        self.pc.avoid = frozenset(key[1:] for key, until in self.shortcut.failures.items()
                                  if key[0] == 'release' and until > snapshot.frame) | guarded(snapshot, self.sp)
        self.pc.partners = frozenset(self.trade_partners()) if hasattr(self, 'trade_partners') else frozenset()
        return self.pc.release_target(snapshot, self.collection.project, self._preferences(), self.collection,
                                      self.pc.avoid, self.pc.partners)

    def _pc_target(self, snapshot):
        return self.pc.target(snapshot, self.goal.key, self.collection.project, self._preferences(), self.collection)

    _sale_index = staticmethod(ShoppingController.sale_index)

    def _tm_options(self, s, standing):
        """The owned supplies and TMs the party could use and the purchase it could make, as
        ``(supplies, owned, purchase)``. They are scored again only when the party, the bag, the purse,
        the Champion counter's offers or the items standing down change, not on a timer."""
        from .. import tm_shop, champion_shop
        from .collection import champion
        token = (tuple((individual(p), p.hp > 0, p.status, tuple(p.max_pp)) for p in s.party), s.items, s.money,
                 frozenset(self.shop_offers), standing, self.tm_plan is None, champion(s))
        if token != self.tm_token:
            bag = dict(s.items)
            supplies = [(item, target) for item in (ITEMS['PP_UP'], ITEMS['RARE_CANDY'])
                        if bag.get(item) and (target := champion_shop.recipient(s, item)) is not None]
            owned = tm_shop.choose(s, self.tm_moves, self.tm_compatible, owned=True)
            purchase = None if self.tm_plan else (
                tm_shop.choose(s, self.tm_moves, self.tm_compatible, owned=False, skip=standing)
                or champion_shop.choose(s, self.shop_offers, skip=standing))
            self.tm_token, self.tm_options = token, (supplies, owned, purchase)
        return self.tm_options

    def purchase_candidate(self, plan):
        """The arbiter's candidate for a trip to the Champion counter to buy ``plan``.

        A TM is worth the move it gives: its share of a level 100 credit by the battle power it adds.
        Supplies are filler. Leaving a project under way costs the trip again, the walk back to it.
        """
        interrupt = TM_TRIP_FRAMES if self.collection.project else 0.0
        if plan.get('supply'):
            return Candidate('buy_tm', Tier.FILLER, values.SMALL, TM_TRIP_FRAMES, interrupt_frames=interrupt,
                             goal='moves')
        return Candidate('buy_tm', Tier.UPGRADE, values.move_gain(plan['before'], plan['after']), TM_TRIP_FRAMES,
                         interrupt_frames=interrupt, goal='moves')

    def teach_candidate(self, choice, upgrade):
        """The arbiter's candidate for teaching an owned HM, from ``hm_upgrade``.

        The teach serves the goal under way, so it takes the pick's tier, and it is worth the move it
        gives: its share of a level 100 credit by the battle power it adds. It runs in the menus, and
        cutting into a project under way pays its frames again, as a purchase pays its trip again.
        """
        gain, _, _, _, before = upgrade
        interrupt = TEACH_FRAMES if self.collection.project else 0.0
        return Candidate('teach_battle', choice.pick.tier, values.move_gain(before, before + gain), TEACH_FRAMES,
                         interrupt_frames=interrupt, goal='moves')

    def _hm_option(self, s):
        """The best HM teach for the party, scored again only when the party or its HMs change."""
        token = (tuple((p.species, p.level, p.moves, p.hp > 0, p.status) for p in s.party),
                 tuple(qty for item, qty in s.items if item in HM_TEACH_ITEMS))
        if token != self.hm_token:
            self.hm_token, self.hm_option = token, hm_upgrade(s)
        return self.hm_option

    def _buy_goal(self, s, plan):
        from .. import tm_shop, champion_shop
        item, target = plan['item'], plan['target']
        name = champion_shop.NAMES[item] if plan.get('supply') else tm_shop.label(item, self.tm_moves)
        quantity = plan.get('quantity', 1)
        price = champion_shop.PRICES[item] if plan.get('supply') else tm_shop.PRICES[item]
        if quantity > 1:
            name = f'{quantity} × {name}'
        purpose = ('Replenish useful supplies' if plan.get('supply')
                   else f'Improve {s.party[target].nick or s.party[target].name}')
        return Goal('buy_tm', f'Buy {name}',
                    f'{purpose} at the Champion counter. '
                    f'Price ₽{price:,}, keeping ₽{tm_shop.RESERVE:,} for supplies',
                    (tm_shop.COUNTER,))

    def _tm_development(self, s, goal, in_league, choice=None):
        """Offer what the party could gain from its bag and the Champion counter as candidates on
        ``choice``, and return the goal it keeps and the action that starts it, if any."""
        from .. import tm_shop, champion_shop
        if choice is None or choice.goal is not goal:
            choice = Choice(goal, goal_candidate(goal, self.collection))
        teach = choice.errand_candidate('teach_tm', 'moves')
        # Every option here is an errand or an upgrade, and neither cuts into an errand under way.
        if not self.tm_moves or self.heal_latch or in_league or not choice.wins(teach):
            return goal, None
        monitor = self.collection.director.monitor
        now = self.collection.elapsed
        if self.tm_plan:
            key = 'tm:' + str(self.tm_plan['item'])
            delta = max(0, min(120, s.frame - self.tm_frame)) if self.tm_frame is not None else 0
            self.tm_frame = s.frame
            monitor.start(key, expected_frames=TM_TRIP_FRAMES)
            if not tm_shop.valid_plan(s, self.tm_plan, self.tm_moves, self.tm_compatible, self.shop_offers):
                monitor.clear(key)
                self.tm_plan = None
            elif monitor.observe(key, delta, now=now).stand_down:
                # The monitor's backoff keeps this item aside, and the next best purchase may go instead.
                self.tm_plan = None
        stood = monitor._table(STOOD_DOWN)
        standing = frozenset(int(key[3:]) for key in stood if key.startswith('tm:') and monitor.standing_down(key, now))
        supplies, owned, purchase = self._tm_options(s, standing)
        bag = dict(s.items)
        for item, target in supplies:
            mon = s.party[target]
            attempt = (item, bag[item], champion_shop.signature(mon), mon.level, tuple(mon.max_pp))
            if attempt not in self.supply_attempts:
                self.supply_attempts.add(attempt)
                self.goal = choice.offer(Goal('teach_supply', f'Use {champion_shop.NAMES[item]}',
                                              f'Improve {mon.nick or mon.name} using an owned item'),
                                         choice.errand_candidate('teach_supply', 'moves'))
                return self.goal, self._use_item(s, item, target)
        if owned:
            item, target = owned['item'], owned['target']
            mon = s.party[target]
            attempt = ('tm', item, bag.get(item), owned['signature'], tuple(mon.moves))
            if attempt not in self.supply_attempts:
                self.supply_attempts.add(attempt)
                self.tm_plan = None
                name = tm_shop.label(item, self.tm_moves)
                self.goal = choice.offer(Goal('teach_tm', f'Teach {name}',
                                              f'Improve {mon.nick or mon.name} using an owned TM'), teach)
                self.reason = self.goal.reason
                return self.goal, self._use_item(s, item, target)
        if self.tm_plan:
            if bag.get(self.tm_plan['item']):
                return choice.goal, None
            # A trip under way is an errand, so only another errand's precondition stops it.
            return choice.offer(self._buy_goal(s, self.tm_plan), choice.errand_candidate('buy_tm', 'moves')), None
        if purchase:
            candidate = self.purchase_candidate(purchase)
            if choice.wins(candidate):
                self.tm_plan = purchase
                self.tm_frame = s.frame
            return choice.offer(self._buy_goal(s, purchase), candidate), None
        return choice.goal, None

    @staticmethod
    def _box_count(s):
        return sum(1 for p in s.stored_details if p.box == s.active_box)

    def release_changed(self, s):
        """Cancel a release whose spare moved or became protected. Core does not check who sits there."""
        machine = self.shortcut.machine
        if (machine is None or machine.kind != 'release_pokemon'
                or self._release_target(s) == (s.active_box, machine.position)):
            return False
        # Once the release is confirmed or the box has shrunk, it has landed. Let Core record it.
        start = getattr(self, 'release_start', None)
        if getattr(machine, 'committed', False) or (
                start and start[0] == s.active_box and self._box_count(s) < start[1]):
            return False
        self.shortcut.cancel()
        self.reason = 'The spare changed or became protected, so keep every Pokémon'
        return True

    def _ui(self):
        return gen1_ui(self.sp)

    def _start_shortcut(self, s, machine, key, purpose, on_done=None):
        """Begin a Core shortcut. None when it refuses, failed here recently, or memory is unavailable."""
        if self.mem is None:
            return None

        def finished(result, finished_machine):
            if not result.completed and finished_machine.inputs:
                self.history.append({'time': ':'.join(f'{v:02d}' for v in s.playtime), 'place': s.map_name,
                                     'message': f'{purpose}: {result.outcome}',
                                     'response': 'Avoid this request for a while and replan'})
                self.history = self.history[-8:]
            if on_done is not None:
                on_done(result, finished_machine)

        actions = self.shortcut.start(machine, key, s.frame, self.mem, self._ui(), purpose, finished)
        if actions:
            self.mode = f'shortcut: {machine.kind}'
            self.reason = purpose
            self.watch.expected = None
        return actions

    def _learn(self, s, slot):
        """Answer a learn-a-new-move prompt through Core: replace ``slot``, or keep the moves when None."""
        forget = 'keep' if slot is None else slot
        return self._start_shortcut(s, LearnMove(forget), ('learn', forget),
                                    "Keep useful coverage and protect HM moves")

    def _use_item(self, snapshot, item, target=0, purpose=None):
        if not any(mid == item and qty for mid, qty in snapshot.items):
            return None
        kind = item_kind(item)
        party_target = kind.target in ('party', 'move')
        if party_target and target >= len(snapshot.party):
            return None
        move = forget = None
        if kind.target == 'move':
            from ..champion_shop import pp_slot
            move = pp_slot(snapshot.party[target])
            if move is None:
                return None
        if kind.kind in ('tm', 'hm'):
            mon = snapshot.party[target]
            learned = HM_ITEM_MOVES.get(item) or self.tm_moves.get(item)
            if all(mon.moves):
                forget = replacement_slot(mon, learned) if learned else None
                if forget is None:
                    return None
        machine = UseItem(item, target if party_target else None, move, forget_move=forget)
        return self._start_shortcut(snapshot, machine, ('item', item, target if party_target else None),
                                    purpose or self.goal.reason)

    def _reorder(self, s, target, purpose):
        """Move party slot ``target`` to the lead outside battle."""
        def done(result, machine):
            if result.completed and self.development_index is not None:
                self.development_index = 0
        return self._start_shortcut(s, ReorderParty(target, 0), ('reorder', individual(s.party[target])),
                                    purpose, done)

    def _field(self, s, move, target, purpose, direction=None, failure=None):
        """Use a field move. A refused Surf or Cut blocks that step for a while."""
        pos = (s.map, s.x, s.y)

        def done(result, machine):
            if not result.completed and direction is not None:
                self.nav.blocked[(pos, direction)] = s.frame + 1200
                self.nav.path.clear()
                if failure:
                    self.reason = failure
        return self._start_shortcut(s, FieldMove(move, target), ('field', move, pos, direction), purpose, done)

    def _avoid(self, s, direction, reason):
        self.nav.blocked[((s.map, s.x, s.y), direction)] = s.frame + 1200
        self.nav.path.clear()
        self.reason = reason
        return wait()

    def _run(self, s):
        return self._start_shortcut(s, RunAway(), ('run', self.battle_key, self.turns), self.reason)

    def _battle_shortcut(self, s, me, enemy):
        """Carry out the battle decision with a Core shortcut, fighting when it cannot be done."""
        intent = self.intent
        if intent.kind == 'item' and intent.index < len(s.items):
            item = s.items[intent.index][0]
            if item not in BALLS or s.can_catch:
                actions = self._use_item(s, item, intent.target, intent.reason)
                if actions:
                    if item in BALLS:
                        self.catch_attempts += 1
                    return actions
        elif intent.kind == 'switch':
            actions = self._start_shortcut(s, SwitchPokemon(intent.index),
                                           ('switch', intent.index, self.battle_key, self.turns), intent.reason)
            if actions:
                self.last_switch_turn = self.turns
                return actions
        elif intent.kind == 'run':
            actions = self._run(s)
            if actions:
                if intent.stance and not self.fleeing:
                    self.fleeing = True
                    self.flees['attempts'] += 1
                return actions
        return self._fight(s, me, enemy)

    def _fight(self, s, me, enemy):
        intent = self.intent
        # A shiny is run from until the stance has failed FLEE_TRIES runs, then fought like any battle.
        protected = (s.in_battle == 1 and (s.enemy_shiny and self.flee_tries < FLEE_TRIES
                     or SPECIES.get(enemy.species, {}).get('dex') in (144, 145, 146, 150)
                     and SPECIES[enemy.species]['dex'] not in s.owned))
        if protected and (not intent or intent.kind != 'fight' or MOVES.get(
                me.moves[intent.index], {}).get('effect') not in ('SLEEP_EFFECT', 'PARALYZE_EFFECT')):
            self.reason = 'Leave rather than risk knocking out the legendary'
            actions = self._run(s)
            if actions:
                return actions
        available = [k for _, k in ranked_moves(me, enemy, self.used_status)]
        preferred = intent.index if intent and intent.kind == 'fight' else None
        # With every move out of PP, the game uses Struggle from any choice.
        slots = ([preferred] if preferred in available else []) + available or [0]
        for slot in dict.fromkeys(slots):
            reason = f"Use {MOVES.get(me.moves[slot], {}).get('name', 'an available move')}"
            actions = self._start_shortcut(s, ChooseMove(slot), ('move', slot, self.battle_key, self.turns), reason)
            if actions:
                if not MOVES.get(me.moves[slot], {}).get('power'):
                    self.used_status.add(me.moves[slot])
                if intent is None or intent.kind == 'fight':
                    self.intent = Decision('fight', slot, reason=reason)
                return actions
        self.intent = None
        return self._run(s) or wait()

    def _recover(self, snapshot):
        if self.goal.key == 'collect_pickup':
            self.pickups.defer(self.collection.elapsed, 'Pickup approach failed')
        self.recoveries += 1
        self.intent = None
        if (self.heal_latch and snapshot.map in VICTORY_MAPS and snapshot.valid
                and not snapshot.in_battle and not snapshot.textbox and not snapshot.start_menu
                and not self.escape_attempted):
            action = self._use_item(snapshot, ITEMS['ESCAPE_ROPE'])
            if action:
                # One ordinary item attempt per healing episode survives checkpoints
                # and trades. A failed attempt must not spend additional ropes.
                self.escape_attempted = True
                self.mode = 'escaping to heal'
                self.reason = 'Use an Escape Rope after the route to healing stalled'
                return action
        blocked = self.nav.blocked.copy()
        self.nav.restore()
        self.nav.blocked.update(blocked)
        self.goal_distance = None
        self.progress_frame = snapshot.frame
        self.recovery_until = snapshot.frame + 180
        return self._recovery_step(snapshot)

    def recover_stall(self, snapshot):
        """Change the plan in the current world before considering a save rewind."""
        if self.pickups.active:
            self.pickups.defer(self.collection.elapsed, 'Pickup approach was stationary too long')
        else:
            self.collection.abandon('The run was stationary too long')
        self.collection.idle_token = None
        self._remember_failure(snapshot, 'Stationary objective abandoned without reloading')
        self.on_restore()
        self.recoveries += 1
        self.recovery_until = snapshot.frame + 180
        self.mode = 'finding another approach'

    def _recovery_step(self, snapshot):
        self.mode = "finding another approach"
        self.reason = "Try nearby paths and interactions, then return to the objective"
        pos = (snapshot.map, snapshot.x, snapshot.y)
        if self.rng.random() < 0.2:
            return tap("a")
        direction = self.nav.explore(pos, snapshot.frame, self.rng)
        self.nav.issued(pos, direction, snapshot.frame)
        return tap(direction, 8, 12)

    def _remember_failure(self, s, message):
        self.history.append({'time': ':'.join(f'{v:02d}' for v in s.playtime), 'place': s.map_name,
                             'message': message, 'response': 'Close the menu or avoid the failed approach and replan'})
        self.history = self.history[-8:]
        if self.last_action:
            pos, button = self.last_action
            key = ':'.join(map(str, (*pos, button)))
            self.failures[key] = min(5, self.failures.get(key, 0) + 1)
            self.failures = dict(list(self.failures.items())[-128:])
            if button in DIRS:
                self.nav.blocked[(pos, button)] = s.frame + 600 * self.failures[key]
                self.nav.path.clear()
        self.reason = message

    @property
    def developing(self):
        """Whether a development excursion is under way."""
        return self.excursion is not None and self.excursion[2] == 'development'

    def _development_done(self, s):
        """Whether the development excursion has ended: its partner gained a level, left the party, or went
        ``DEVELOPMENT_STALL`` frames without gaining experience. The partner is found by who it is, since
        the excursion moves it to the lead."""
        progress = self.development
        mon = next((p for p in s.party if progress and (p.species, p.nick, p.dvs) == progress['partner']), None)
        if mon is None:
            return True
        if mon.experience > progress['experience']:
            progress['experience'], progress['since'] = mon.experience, s.frame
        return mon.level > progress['level'] or s.frame - progress['since'] >= DEVELOPMENT_STALL

    def _purposeful_detour(self, s, mem, main_goal):
        pos = (s.map, s.x, s.y)
        if self.heal_latch or main_goal.key.startswith(('heal', 'restock', 'train_', 'catch_', 'party_', 'teach_', 'league', 'collect_')) or s.map in MANSION_MAPS | VICTORY_MAPS:
            self.excursion = None
            return None
        if self.excursion:
            goal, expires, key = self.excursion
            ended = self._development_done(s) if key == 'development' else s.frame >= expires
            if ended or s.map != goal.targets[0][0]:
                self.excursion = None
                self.next_conversation = s.frame + 3600
                return None
            self.goal = goal
            self.next_goal = main_goal.to_dict()
            self.reason = goal.reason
            if pos in goal.targets:
                if key == 'development':
                    choices = [(dr, q) for dr, q in self.nav.neighbors(pos, s.frame) if q in goal.targets]
                    if not choices:
                        self.excursion = None
                        return None
                    direction = self.rng.choice(choices)[0]
                else:
                    self.excursion = None
                    self.next_conversation = s.frame + 3600
                    self.mode = 'following a curiosity'
                    facing = goal.facing_at(pos)
                    if mem[W_FACING] != FACING[facing]:
                        self.excursion = (goal, expires, key)
                        return tap(facing, 4, 12)
                    self.pending_social = (key, s.frame)
                    return tap('a')
            else:
                direction = self.nav.route(pos, goal.targets, s.frame)
                if not direction or len(self.nav.path) > 20:
                    self.excursion = None
                    self.next_conversation = s.frame + 1800
                    return None
            self.mode = 'training a partner' if key == 'development' else 'following a curiosity'
            self.nav.issued(pos, direction, s.frame)
            return tap(direction, 8, 12)
        if s.frame < self.next_conversation or self.rng.random() > EXPLORATION_CHANCE * 0.15:
            return None
        w = WORLD.get(s.map, {})
        if any(p.status for p in s.party) or max((p.hp / max(1, p.max_hp) for p in s.party), default=0) < 0.8:
            return None
        encounters = w.get('encounters', [])
        trainee = development_candidate(s, max((level for _, level in encounters), default=100))
        grass = tuple((s.map, x, y) for y, row in enumerate(w.get('tiles', [])) for x, tile in enumerate(row)
                      if tile == 0x52 and abs(x - s.x) + abs(y - s.y) <= 8)
        if trainee is not None and grass and s.frame >= self.development_cooldown:
            goal = Goal('train_partner', 'Give a promising partner some experience',
                        f'Train {s.party[trainee].nick or s.party[trainee].name} in nearby manageable encounters', grass,
                        kind=TRAIN)
            mon = s.party[trainee]
            self.development = {'partner': (mon.species, mon.nick, mon.dvs), 'level': mon.level,
                                'experience': mon.experience, 'since': s.frame}
            self.development_cooldown = s.frame + 18000
            self.development_index = trainee
            self.excursion = (goal, None, 'development')
            if trainee != 0:
                actions = self._reorder(s, trainee, goal.reason)
                if actions:
                    return actions
            return self._purposeful_detour(s, mem, main_goal)
        positions = self.nav.live_positions if self.nav.live_map == s.map else []
        candidates = []
        for i, o in enumerate(w.get('objects', [])):
            if o[2] in ('SPRITE_NURSE', 'SPRITE_CLERK', 'SPRITE_BOULDER', 'SPRITE_SNORLAX', 'SPRITE_BLUE', 'SPRITE_OAK') or (s.map, o[0], o[1]) in self.nav.cleared_objects:
                continue
            # An item the bag has no room for, including the Safari Zone's kept prize room, is left alone.
            item = ground_item(o)
            if item and not Pickups.has_space(s, item['item']):
                continue
            x, y = positions[i] if i < len(positions) else o[:2]
            key = f'{s.map}:{o[4]}'
            weight = 3 if (self.personality == 'Collector') == (o[2] == 'SPRITE_POKE_BALL') else 1
            candidates.append((x, y, key, 'Investigate a nearby item' if o[2] == 'SPRITE_POKE_BALL' else 'Meet someone nearby', weight))
        candidates += [(x, y, f'{s.map}:{name}', 'Read a local sign', 3 if self.personality == 'Explorer' else 1)
                       for x, y, name in w.get('backgrounds', []) if 'SIGN' in name or 'TRAINER_TIPS' in name]
        candidates = [c for c in candidates if c[2] not in self.interactions and 1 < abs(c[0] - s.x) + abs(c[1] - s.y) <= 8]
        self.next_conversation = s.frame + 1800
        if candidates:
            x, y, key, title, _ = self.rng.choices(candidates, weights=[c[4] for c in candidates])[0]
            approaches = tuple((s.map, x - dx, y - dy, dr) for dr, (dx, dy) in DIRS.items()
                               if self.nav._tile(w, x - dx, y - dy) in w['passable'])
            if approaches:
                goal = Goal('curiosity', title, f'{self.personality} detour, then return to {main_goal.title.lower()}',
                            tuple(p[:3] for p in approaches), approaches[0][3], True, approaches=approaches)
                direction = self.nav.route(pos, goal.targets, s.frame)
                if direction and len(self.nav.path) <= 16 and all(p[0][0] == s.map for p in self.nav.path):
                    self.excursion = (goal, s.frame + 900, key)
                    return self._purposeful_detour(s, mem, main_goal)
        return None

    def _social_interaction(self, snapshot, mem):
        pos = (snapshot.map, snapshot.x, snapshot.y)
        if self.social_target:
            origin, facing, key, label = self.social_target
            self.social_target = None
            if origin == pos and mem[W_FACING] == FACING[facing]:
                self.pending_social = (key, snapshot.frame)
                self.next_conversation = snapshot.frame + 900
                self.mode = label
                self.reason = "Take a moment to learn about the area before continuing"
                return tap("a")
        if snapshot.frame < self.next_conversation or self.rng.random() > 0.15:
            return None
        world = WORLD.get(snapshot.map, {})
        positions = self.nav.live_positions if self.nav.live_map == snapshot.map else []
        candidates = [(*(positions[i] if i < len(positions) else o[:2]), o[4], "talking to locals")
                      for i, o in enumerate(world.get("objects", []))
                      if o[2] not in ("SPRITE_NURSE", "SPRITE_CLERK", "SPRITE_BOULDER", "SPRITE_SNORLAX")
                      and (snapshot.map, o[0], o[1]) not in self.nav.cleared_objects]
        candidates += [(x, y, name, "reading a sign") for x, y, name in world.get("backgrounds", [])
                       if "SIGN" in name or "TRAINER_TIPS" in name]
        self.rng.shuffle(candidates)
        for x, y, name, label in candidates:
            key = f"{snapshot.map}:{name}"
            if key in self.interactions:
                continue
            direction = next((d for d, (dx, dy) in DIRS.items()
                              if (snapshot.x + dx, snapshot.y + dy) == (x, y)), None)
            if direction:
                self.social_target = (pos, direction, key, label)
                self.mode = label
                self.reason = "Notice someone or something along the way"
                if mem[W_FACING] == FACING[direction]:
                    return self._social_interaction(snapshot, mem)
                return tap(direction, 4, 12)
        return None
