"""Observe and act through cartridge controls for Generation II adventures."""
from __future__ import annotations

from dataclasses import asdict
from collections import Counter, deque
import random

from ...planning.ledger import FIELD_MOVES
from ...planning.losses import ace_slot
from ...planning.shadow import Shadow
from ...runtime import policy as protocol
from ...runtime.policy import Action
from ..navigation import Navigator
from pokecore.gen2.ram import Memory
from pokecore.gen2.state import script_running
from ..world import update as update_world
from ..naming import Naming
from ..menus import (TASKS, Buy, ChangeBox, DayCare, FieldMove, Fly, Forget, Give, Lead, PutAway, Radio, Remedy, Sell,
                     ShowPartner, Storage, Take, Teach, Toss, Use, choose, close_pc, restore)
from .battle import SUBSTATUS_TRANSFORMED, BattlePart, transformed
from .errands import ErrandPart
from .items import ItemPart
from .menus import MenuPart
from .navigation import NavigationPart
from .pins import PinPart
from .reads import Reads
from .state import SAVE_VERSION, Goal, Saved
from .storage import StoragePart
from .story import StoryPart

__all__ = ['Goal', 'Memory', 'Policy', 'SAVE_VERSION', 'SUBSTATUS_TRANSFORMED', 'Saved', 'transformed', 'update_world']


class Policy(MenuPart, PinPart, StoryPart, StoragePart, ErrandPart, NavigationPart, ItemPart, BattlePart, protocol.Policy):
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
        # The heal and supply errands (gen2/errands.py), the one the last errand decision picked, the
        # step's journey pick, and whether this step reached the errand decision.
        from ...planning.errand import Trip
        from ..errands import Heal, Shop
        self.heal, self.shop, self.trip = Heal(), Shop(), Trip()
        self.pick = None
        self.decided = False
        self.menu = None
        self.talk_key, self.talk_frames = None, 0
        # The PC chosen last time, kept while it stays among the nearest so equal routes do not flip it.
        self.storage_pick = None
        self.completed = {}
        self.collection = {'target': None}
        # The best fighter level that lost to each boss. Store.attach keeps it in the adventure's store.
        from ...planning.losses import Losses
        self.losses = Losses()
        # The progress monitor's stand-downs and budgets, timed on ``clock``. Store.attach gives the adventure's.
        from ...runtime.supervision import Tables
        self.monitor_tables = Tables(clock=lambda: self.clock)
        # Owned one-time encounters that a walking return brought back for another capture.
        self.returned = set()
        # The party seen at this PC visit, so a member deposited at it is no spare (pcvalue.VisitTeam).
        from ...pcvalue import VisitTeam
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
        # The battle and screen state of the decision under way, read when first asked. Never saved.
        self.reads = None
        # The next activity a manager set (planning/pin.py). Never saved.
        self.pin = None
        self.resetting_puzzle = None
        self.unreachable_waits = 0
        # The arbiter's and the decide pipeline's picks beside the chain's, for the log and the replay
        # audit. Never saved.
        self.shadow = Shadow()
        # The step's decide pipeline offers (gen2/pipeline.py) and the pipeline's pick for the trace.
        # Never saved.
        self.ballot = None
        self.pipeline_pick = None
        # The offer the goal ran under when a ballot last chose it, which the goal record reads. Never saved.
        self.goal_offer = None
        # The source and goal key of the last decision's pick, which tells the stuck guard whether the
        # goal that stopped is the collection's and can be set aside. Never saved.
        self.picked = None

    def state_dict(self):
        return Saved(
            starter=self.starter, rng=self.rng.getstate(), completed=self.completed, collection=self.collection,
            demand=self.demand, decisions=self.decisions, naming=self.naming.state_dict(), learning=self.learning,
            partner_move=self.partner_move,
            menu={'kind': type(self.menu).__name__, 'state': asdict(self.menu)} if self.menu else None,
            errands={errand.key: errand.state_dict() for errand in (self.heal, self.shop)},
            interaction=self.interaction, resetting_puzzle=self.resetting_puzzle,
            objects={str(mid): {str(index): point for index, point in objects.items()}
                     for mid, objects in self.nav.objects.items()}).to_dict()

    def load_state_dict(self, state):
        from ..gamecorner import Coins, Prize, Slots
        from ..npc_trades import Trade
        # A pin belongs to the moment it was set, so it never outlives a load, even of a save it cannot read.
        self.pin = None
        saved = Saved.read(state)
        if saved is None:
            self.on_restore()
            return
        if saved.starter is not None:
            self.starter = saved.starter
        if saved.rng is not None:
            # Saved as JSON lists, so the tuples the generator wants are rebuilt.
            def tuples(value):
                return tuple(tuples(item) for item in value) if isinstance(value, (list, tuple)) else value
            self.rng.setstate(tuples(saved.rng))
        self.completed = saved.completed
        self.collection = saved.collection
        from ..standdown import migrate
        migrate(self, saved.decisions)
        from ..kinds import adopt
        adopt(self.collection)
        self.demand = {int(key): value for key, value in saved.demand.items()}
        self.decisions = saved.decisions
        self.naming.load_state_dict(saved.naming)
        self.learning = saved.learning
        self.partner_move = saved.partner_move
        menu = saved.menu
        kinds = {**TASKS, 'Trade': Trade}
        self.menu = restore(kinds[menu['kind']], menu['state']) if menu and menu.get('kind') in kinds else None
        if menu and menu.get('kind') in {'Coins', 'Prize', 'Slots'}:
            self.menu = {'Coins': Coins, 'Prize': Prize, 'Slots': Slots}[menu['kind']](**menu['state'])
        for errand in (self.heal, self.shop):
            errand.load_state_dict(saved.errands.get(errand.key, {}))
        self.interaction = saved.interaction
        self.resetting_puzzle = saved.resetting_puzzle
        if isinstance(self.interaction, list):
            self.interaction = tuple(self.interaction)
        self.nav.objects = {int(mid): {int(index): tuple(point) for index, point in objects.items()}
                            for mid, objects in saved.objects.items()}
        self.on_restore()

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

    def on_restore(self):
        objects = self.nav.objects
        self.nav = Navigator(self.data)
        self.nav.objects = objects

    def step(self, ctx):
        """The one action of a decision. ``ctx.sp`` is the CPU stack pointer, which Core's PC lists read
        to press through a <CONT> name, and ``ctx.clock`` the PlayClock frame the policy's waits count."""
        snapshot = ctx.snapshot
        self.clock = ctx.clock
        self.pick, self.decided = None, False
        self.ballot = self.pipeline_pick = None
        try:
            action = self._step(snapshot, ctx.mem, ctx.sp)
        finally:
            # The reads belong to this decision's memory, which the emulator changes before the next one.
            self.reads = None
        ballot = self.ballot
        if self.trip.goal is not None and not self.decided and self.goal is self.pick and not snapshot.in_battle:
            # An errand under way is the goal until the next errand decision ends it. Otherwise each
            # menu, conversation and team step on the way ran under the journey goal behind it. The step
            # has already decided under that goal, so menus read the same goal as before. It is offered again
            # as it was picked, so it is still the enabler of the goal it serves.
            self.goal = self.trip.resume(ballot)
        if ballot is not None:
            # Only the offer the step ends with writes, so an offer a later site overrides leaves nothing.
            ballot.commit()
            running = self.goal_offer = ballot.running
            self.picked = None if running is None else (running.source, running.key)
        shadow = getattr(self, 'shadow', None)
        if ballot is not None and shadow is not None and self.goal is not None:
            # The decision is the pipeline's, and the shadow keeps its record for the gate and the replays.
            # A goal no site offered shows there as unlisted.
            decision = shadow.weigh('pipeline', lambda: ballot.decision, self.goal.key, None,
                                    getattr(snapshot, 'frame', None))
            self.pipeline_pick = decision.record() if decision is not None else None
        # A journey asked for outside a step weighs on a ballot of its own.
        self.ballot = None
        return [action]

    def _step(self, snapshot, memory, sp=None):
        self.memory, self.sp = memory, sp
        self.reads = Reads(memory, self.data.game)
        self.decisions += 1
        from ..release import team_keys
        self.visit_team.observe(snapshot.map, team_keys(snapshot.party))
        from ..postgame import observe
        observe(self, snapshot)
        from ..collection import observe_search
        observe_search(self, snapshot)
        from ..training import observe as observe_training
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
        from ..ruins import control
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
        if not snapshot.started or self.unloaded(snapshot):
            self.mode = 'opening'
            return Action('start' if self.decisions % 20 == 1 else 'a', 8, 52)
        from ..contest import control as contest_control
        contest_button = contest_control(self, snapshot, mem)
        if contest_button:
            self.mode = 'Catch a Bug-Catching Contest partner'
            return Action(contest_button, 8, 28)
        from ..tower import control as tower_control
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
        if not ('┌' in snapshot.tiles[12] or snapshot.script_running):
            self.talk_key, self.talk_frames = None, 0
        self.nav.observe(snapshot, interrupted=script_running(memory, self.data.game))
        if self.resetting_puzzle is not None and self.resetting_puzzle != snapshot.map:
            self.resetting_puzzle = None
        releasing = self.goal is not None and self.goal.key == 'collection_release'
        starting = self.goal is not None and self.battle_starting(snapshot)
        # Each site that sets the goal from here on offers it on the step's ballot, and the goal is the
        # ballot's pick (gen2/pipeline.py). A site writes its state only when its goal is picked (rule A).
        from ..pipeline import Ballot
        self.ballot = ballot = Ballot()
        if starting:
            self.goal = journey_goal = ballot.offer(self.goal, 'current', self.story_candidate(self.goal, 'current'))
        else:
            self.goal = journey_goal = self.journey(snapshot, mem)
        release = self.release_goal(snapshot, mem, releasing)
        if release:
            self.goal = journey_goal = ballot.errand(release, 'release')
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
        from ..item_sources import answer as number_answer
        action = number_answer(self, snapshot)
        if action:
            return Action(action, 8, 28)
        if self.goal.key == 'radio_card' and 'YES' in snapshot.text and 'NO' in snapshot.text:
            negative = any(word in snapshot.text for word in ('FLASH', 'CHARMANDER', 'APRIKORN', 'MARIE'))
            return Action(choose(snapshot.tiles, 'NO' if negative else 'YES', exact=True) or 'a', 8, 28)
        # Textboxes cover the bottom six rows. Scripted walking is allowed to finish.
        if '┌' in snapshot.tiles[12] or snapshot.script_running:
            self.mode = 'conversation'
            # The nurse and every other talk on the way run under the heal, not the journey goal, so one
            # trip stays one goal and the restore lands inside it.
            if not starting and self.errand_allowed(snapshot, mem):
                heal, _ = self.heal.offer(self, snapshot)
                if heal:
                    self.goal = ballot.errand(heal, 'talk_heal')
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
                        self.goal = ballot.errand(partner, 'partner', commit=commit)
                    break
                if 'ice_path' in self.completed:
                    candidates = [i for i, mon in enumerate(snapshot.party) if not mon.egg
                                  and move in self.data.species[mon.species]['machines']]
                    if candidates:
                        goal = self.person(snapshot, f'delete_hm_{candidates[0]}', f'Make room for {self.data.moves[move]["name"]}',
                                           'MOVE_DELETERS_HOUSE', 'MoveDeleter')
                        if goal is not None:
                            self.goal = ballot.errand(goal, 'delete_hm')
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
            from ..champion_shop import use as champion_use
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
            heal, _ = self.heal.offer(self, snapshot)
            errand, commit = (heal, None) if heal or prize_errand else self.shop.offer(self, snapshot)
            self.trip.end()
            if errand is not None:
                self.goal = ballot.errand(errand, 'heal' if heal else 'shop', commit=commit)
                if self.goal is errand:
                    self.trip.start(errand, ballot.running)
        else:
            self.trip.end()
        if self.no_route_waiting(self.goal):
            # The goal found no route lately (no_route). An errand gives way to what the ballot picks
            # without it, and a goal with nothing to run instead looks around rather than walk the same
            # missing route again.
            if self.trip.goal is not None and not self.no_route_waiting(journey_goal):
                self.goal = ballot.park(self.trip.goal) or journey_goal
                self.trip.end()
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
        from ..marathon import racing
        running = self.goal.key == 'collection_marathon' and racing(self)
        from ..flight import shortcut
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
                from ..collection import arrive
                if self.goal.face and self.reads.ui.facing != self.goal.face:
                    return Action(self.goal.face, 8, 16)
                button = arrive(self, snapshot)
                if button:
                    return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 36)
            if self.goal.key == 'snorlax' and snapshot.map_music != 0x40:
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
                    from ..breeding import carried
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
            if self.goal.key.startswith('push_') and snapshot.strength:
                self.nav.issued(snapshot, self.goal.face)
                return Action(self.goal.face, 16, 32)
            if self.goal.key == 'fish_surf' and self.interaction == self.goal.key:
                self.menu = Use(self.data.items['GOOD_ROD'])
                return Action(None, 0, 24)
            action = self.shop.act(self, snapshot)
            if action:
                return action
            if self.goal.face and self.interaction != self.goal.key:
                self.interaction = self.goal.key
                return Action(self.goal.face, 8, 8)
            from ..quests import gift_goal, pressed
            if gift_goal(self.goal.key):
                # Each press here is a try at the gift, so a gift that never comes is set aside.
                pressed(self, self.goal.key, self.goal.map_name)
            return Action('a', 8, 36)
        return Action(None, 0, 24)
