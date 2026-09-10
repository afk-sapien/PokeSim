"""An objective-driven policy that observes the game after every action."""
import random

from .base import Action, Policy
from .battle import (BALLS, CURES, HEALING, W_BATTLE_MON, W_ENEMY_MON, Decision, choose_battle,
                     healing_item, needs_healing, ranked_moves, read_battler, replacement_slot, shopping_item)
from .navigation import DIRS, PAIR_COLLISIONS, WATER_TILESETS, Navigator
from .naming import NamingController
from .puzzles import MANSION_MAPS, VICTORY_MAPS, BoulderPlanner, MansionPlanner, boulder_task
from .progression import Goal, healing_goal, journey, league_partner, milestones, story_goal
from .collection import Collection, LEAGUE
from .awareness import ActionWatch
from .team import development_candidate, potential, readiness, reserve_to_deposit
from ..screen import Screen, W_PLAYER_MON_NUMBER
from ..ram import W_TILEMAP
from ..strategy_data import DATA, ITEMS, MAPS, MOVES, SPECIES, WORLD, event_set

W_WALK_COUNTER = 0xCFC5
W_FACING = 0xC109
W_WHICH_POKEMON = 0xCF92
W_MOVE_NUM = 0xD0E0
FACING = {"down": 0, "up": 4, "left": 8, "right": 12}


def tap(button, hold=6, gap=12):
    return [Action(button, hold, gap)]


def wait():
    return [Action(None, 0, 12)]


class StrategicPolicy(Policy):
    name = "strategic"

    def __init__(self, seed=None):
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
        self.exploration = 0.12
        self.journey = []
        self.interactions = {}
        self.interaction_count = 0
        self.collection = Collection()
        self.personality = self.rng.choice(('Sociable', 'Collector', 'Explorer'))
        self.history = []
        self.failures = {}
        self.readiness = {}
        self.next_goal = None
        self.map_view = None
        self.on_restore()

    def reset(self):
        self.__init__(self.seed)

    def on_restore(self):
        self.collection.last_frame = None
        self.nav.restore()
        self.mansion = MansionPlanner()
        self.boulders = BoulderPlanner()
        self.intent = None
        self.intent_since = 0
        self.last_kind = None
        self.last_signature = None
        self.unchanged_since = None
        self.confirming = None
        self.used_status = set()
        self.battle_key = None
        self.turns = 0
        self.last_switch_turn = -5
        self.catch_attempts = 0
        self.heal_latch = False
        self.shopping = False
        self.selling = False
        self.shop_item = None
        self.goal_attempts = 0
        self.observed_map = None
        self.settle_until = 0
        self.stock_latch = False
        self.recovery_until = 0
        self.progress_frame = None
        self.progress_goal = None
        self.goal_distance = None
        self.order_stage = None
        self.order_species = None
        self.pc_operation = None
        self.elevator_exit = False
        self.elevator_floor = "B1F"
        self.field_move = None
        self.trash_checked = set()
        self.trash_pending = None
        self.trash_first = None
        self.social_target = None
        self.next_conversation = 0
        self.watch = ActionWatch()
        self.last_action = None
        self.excursion = None
        self.development_until = 0
        self.development_cooldown = 0
        self.development_index = None
        self.assessment_token = None
        self.storage_species = None
        self.storage_map = None
        self.menu_context = None
        self.pending_social = None
        self.supply_attempts = set()

    def describe(self):
        return f"strategic ({self.mode})"

    def details(self):
        return {"collection": self.collection.details(), "objective": self.goal.to_dict(), "action": self.mode, "reason": self.reason,
                "milestones": self.completed.copy(), "recoveries": self.recoveries,
                "decisions": self.decisions, "visited_tiles": len(self.nav.visits),
                "exploration": self.exploration, "journey": self.journey,
                "interactions": self.interaction_count,
                "personality": self.personality, "next": self.next_goal,
                "readiness": self.readiness, "history": self.history[-8:],
                "expectation": self.watch.expected['label'] if self.watch.expected else None,
                "map": self.map_view,
                "route": [list(target) for _, _, target in list(self.nav.path)[:24]]}

    def state_dict(self):
        return {"version": 1, "collection": self.collection.state_dict(), "navigation": self.nav.state_dict(), "rng": self.rng.getstate(),
                "recoveries": self.recoveries, "decisions": self.decisions,
                "exploration": self.exploration, "naming": self.naming.state_dict(),
                "interactions": list(self.interactions), "interaction_count": self.interaction_count,
                "personality": self.personality, "history": self.history[-8:], "failures": self.failures}

    def load_state_dict(self, data):
        if data.get("version") != 1:
            return
        self.collection.load(data.get("collection", {}))
        self.nav.load_state_dict(data.get("navigation", {}))
        self.naming.load_state_dict(data.get("naming", {}))
        self.interactions = {key: True for key in data.get("interactions", [])}
        self.interaction_count = data.get("interaction_count", len(self.interactions))
        self.personality = data.get('personality', self.personality)
        self.history = data.get('history', [])[-8:]
        self.failures = dict(list(data.get('failures', {}).items())[-128:])
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, (list, tuple)) else value
        if "rng" in data:
            self.rng.setstate(tuples(data["rng"]))
        self.recoveries = data.get("recoveries", 0)
        self.decisions = data.get("decisions", 0)
        self.exploration = max(0.0, min(float(data.get("exploration", 0.12)), 0.3))
        self.on_restore()

    def _select(self, scr, target, one_based=False, scroll=False):
        current = scr.menu_index - int(one_based) + (scr.scroll if scroll else 0)
        if current != target:
            return tap("down" if current < target else "up")
        return tap("a")

    def _root(self, scr, kind):
        target_col, target_row = {"fight": (9, 0), "item": (9, 1), "switch": (15, 0), "run": (15, 1)}[kind]
        if scr.top_x != target_col:
            return tap("right" if target_col > scr.top_x else "left")
        return self._select(scr, target_row)

    def step(self, ctx):
        s, mem = ctx.snapshot, ctx.mem
        scr = Screen(mem)
        kind = scr.kind(s)
        frame = s.frame
        pos = (s.map, s.x, s.y)
        self.decisions += 1
        self.collection.observe(s)
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
            return [naming_action]
        if s.map != self.observed_map:
            self.observed_map = s.map
            self.settle_until = frame + 60
        world = WORLD.get(s.map)
        if frame < self.settle_until or (self.nav.use_world and world and not s.in_battle and
                                        not (0 <= s.x < world["width"] and 0 <= s.y < world["height"])):
            self.mode = "waiting for map transition"
            return wait()
        self.completed = milestones(s)
        self.nav.update_story(s)
        if not s.in_battle and kind == "overworld":
            self.nav.update_live(s, mem)
        self.goal = story_goal(s) if s.started else self.goal
        if self.collection.project and s.map not in LEAGUE:
            self.goal = self.collection.goal(s) or self.goal
        if self.storage_species:
            if any(p.species == self.storage_species for p in s.party) or self.storage_map is None:
                self.storage_species = None
                self.storage_map = None
            else:
                self.goal = Goal('party_upgrade', 'Bring a stronger reserve onto the team',
                                 'Swap an underused reserve for a useful Pokémon already in storage',
                                 ((self.storage_map, 13, 4),), 'up', True)
        self.next_goal = self.goal.to_dict()
        league_rooms = {MAPS[n] for n in ('LORELEIS_ROOM', 'BRUNOS_ROOM', 'AGATHAS_ROOM', 'LANCES_ROOM', 'CHAMPIONS_ROOM')}
        withdrawing_partner = (
            self.goal.key == 'party_collection' and len(s.party) < 6
            and self.collection.project
            and any(species == self.collection.project['parent'] for species, level in s.boxed_pokemon)
        )
        if s.box_full and not withdrawing_partner and s.next_free_box is not None and s.map not in league_rooms:
            self.storage_species = None
            self.storage_map = None
            targets = tuple((m, 13, 4) for m, w in WORLD.items()
                            if 'Pokecenter' in w['name'] and w['width'] == 14)
            self.goal = Goal('party_box', 'Make room for new catches',
                             f'Box {s.active_box + 1} is full. Visit a PC and switch to Box {s.next_free_box + 1}',
                             targets, 'up', True)
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
                                     self.goal.key.startswith(('train_', 'catch_', 'collect_hunt', 'collect_train')) or s.frame < self.development_until)
        if failure:
            self._remember_failure(s, failure)
            self.intent = None
            self.excursion = None
            self.watch = ActionWatch()
            self.watch.last_failure = s.frame
            if kind != 'overworld':
                return tap('b')
            return self._recover(s)
        if self.intent and frame - self.intent_since > 900:
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
        if not s.in_battle and self.watch.expected is None and actions[0].button == 'a' and kind not in ('dialogue', 'overworld', 'naming'):
            self.watch.begin('menu', 'Open the selected menu or advance its choice', s, kind)
        if actions[0].button == "a" and kind not in ("dialogue", "overworld", "naming"):
            self.confirming = (signature, frame)
        self.last_kind = kind
        return actions

    def _dispatch(self, s, scr, kind, mem):
        text = scr.text.upper()
        active = min(mem[W_PLAYER_MON_NUMBER], max(0, len(s.party) - 1))
        if kind == "yes_no":
            if "CHANGE" in text and "MON" in text:
                return self._select(scr, 1)
            if "ABANDON" in text or "STOP LEARNING" in text:
                return self._select(scr, 0)
            if "DELETE" in text or "FORGET" in text or "LEARN" in text:
                learner = min(mem[W_WHICH_POKEMON], max(0, len(s.party) - 1))
                slot = replacement_slot(s.party[learner], mem[W_MOVE_NUM]) if s.party else None
                return self._select(scr, 0 if slot is not None else 1)
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
            return tap("b") if slot is None else self._select(scr, slot)
        if not s.in_battle:
            self.used_status.clear()
            self.battle_key = None
            self.turns = 0
            self.catch_attempts = 0
            self.last_switch_turn = -5
        if kind == "safari":
            if not s.can_catch:
                self.reason = 'Leave the encounter because the party and active box are full'
                if scr.top_x != 13:
                    return tap('right')
                return self._select(scr, 1)
            self.reason = "Use Safari Balls in the Safari Zone"
            if scr.top_x != 1:
                return tap("left")
            return self._select(scr, 0)
        if kind == "battle":
            me, enemy = read_battler(mem, W_BATTLE_MON), read_battler(mem, W_ENEMY_MON)
            key = (s.enemy_species, s.enemy_level, enemy.max_hp)
            if key != self.battle_key:
                self.used_status.clear()
                self.catch_attempts = 0
                self.battle_key = key
            if self.last_kind not in ("battle", None):
                self.intent = None
                self.turns += 1
            if self.intent and self.intent.kind == "fight" and not me.pp[self.intent.index]:
                self.intent = None
            if self.intent is None:
                self.intent = choose_battle(s, me, enemy, active, self.used_status,
                                            self.turns - self.last_switch_turn >= 3, self.catch_attempts,
                                            {'catch_cut': 15, 'catch_surf': 57, 'catch_strength': 70}.get(self.goal.key), collect_missing=True)
                self.intent_since = s.frame
            self.mode = f"battle: {self.intent.kind}"
            self.reason = self.intent.reason
            return self._root(scr, self.intent.kind)
        if kind == "moves":
            me, enemy = read_battler(mem, W_BATTLE_MON), read_battler(mem, W_ENEMY_MON)
            available = ranked_moves(me, enemy, self.used_status)
            slot = self.intent.index if self.intent and self.intent.kind == "fight" else available[0][1] if available else 0
            if not any(k == slot for _, k in available):
                slot = available[0][1] if available else 0
            if not available:
                self.intent = None
                self.reason = "Return to the battle menu to switch, escape, or let the game use Struggle"
                return tap("b")
            self.reason = f"Use {MOVES.get(me.moves[slot], {}).get('name', 'an available move')}"
            if scr.menu_index == slot + 1 and not MOVES.get(me.moves[slot], {}).get("power"):
                self.used_status.add(me.moves[slot])
            return self._select(scr, slot, one_based=True)
        if kind == "party":
            project = self.collection.project
            if not s.in_battle and self.goal.key == 'collect_trade' and project:
                target = next((i for i,p in enumerate(s.party) if p.species==project['give']), None)
                return tap('b') if target is None else self._select(scr,target)
            if not s.in_battle and self.intent is None:
                return tap("b")
            if self.intent and self.intent.kind == "reorder":
                if s.party[0].species == self.order_species:
                    if self.development_index is not None:
                        self.development_index = 0
                    self.intent = None
                    return tap("b")
                target = 0 if self.order_stage == "destination" else self.intent.index
                return self._select(scr, target)
            if self.intent and self.intent.kind in ("switch", "item", "field"):
                target = self.intent.index if self.intent.kind in ("switch", "field") else self.intent.target
            else:
                alive = [(p.hp, i) for i, p in enumerate(s.party) if p.hp and i != active]
                target = max(alive)[1] if alive else active
                self.intent = Decision("switch", target, reason="Replace the fainted active Pokémon")
                self.intent_since = s.frame
            return self._select(scr, target)
        if kind == "party_action":
            if self.intent and self.intent.kind == "reorder":
                row = next((i for i, line in enumerate(scr.rows) if "SWITCH" in line), None)
                if row is not None and scr.cursor:
                    cy = scr.cursor[1]
                    if cy == row:
                        self.order_stage = "destination"
                    return tap("a" if cy == row else "down" if cy < row else "up")
                return tap("b")
            if self.intent and self.intent.kind == "field":
                row = next((i for i, line in enumerate(scr.rows) if self.field_move in line), None)
                if row is not None and scr.cursor:
                    cy = scr.cursor[1]
                    return tap("a" if cy == row else "down" if cy < row else "up")
                self.intent = None
                return tap("b")
            if self.intent and self.intent.kind == "switch":
                self.last_switch_turn = self.turns
                return self._select(scr, 0)
            return tap("b")
        if kind == "shop":
            self.menu_context = 'shop'
            self.intent = None
            self.selling = (self.selling and len(s.items) > 15) or len(s.items) >= 18
            if self.selling and self._sale_index(s) is not None:
                self.reason = "Sell spare TMs and Nuggets to make room for story items"
                return self._select(scr, 1)
            self.selling = False
            stock = DATA["marts"].get(WORLD.get(s.map, {}).get("name"), [])
            self.shop_item = self._shopping_item(s, stock)
            self.shopping = self.shop_item is not None
            self.reason = "Restock balls and medicine while keeping a cash reserve"
            return self._select(scr, 0) if self.shopping else tap("b")
        if kind == "quantity":
            return tap("a") if self.shopping or self.selling else tap("b")
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
            if self.selling:
                index = self._sale_index(s) if len(s.items) > 15 else None
                if index is None:
                    self.selling = False
                    return tap("b")
                return self._select(scr, index, scroll=True)
            if self.shopping:
                stock = DATA["marts"].get(WORLD.get(s.map, {}).get("name"), [])
                item = self._shopping_item(s, stock)
                if item is None:
                    self.shopping = False
                    return tap("b")
                self.shop_item = item
                return self._select(scr, stock.index(item), scroll=True)
            if self.menu_context == 'shop':
                return tap('b')
            if self.menu_context == 'pc' and self.goal.key.startswith("party_"):
                target = self._pc_target(s)
                return tap("b") if target is None else self._select(scr, target, scroll=True)
            if self.intent and self.intent.kind == "item" and self.intent.index < len(s.items):
                if s.items[self.intent.index][0] in BALLS and not s.can_catch:
                    self.intent = None
                    self.reason = 'Stop the capture attempt because storage is full'
                    return tap('b')
                if scr.menu_index + scr.scroll == self.intent.index and s.items[self.intent.index][0] in BALLS:
                    self.catch_attempts += 1
                return self._select(scr, self.intent.index, scroll=True)
            return tap("b")
        if kind == "pause":
            self.menu_context = 'bag'
            if self.intent and self.intent.kind in ("item", "field", "reorder"):
                label = "ITEM" if self.intent.kind == "item" else "MON"
                row = next((i for i, line in enumerate(scr.rows) if label in line), None)
                if row is not None and scr.cursor:
                    cy = scr.cursor[1]
                    return tap("a" if cy == row else "down" if cy < row else "up")
            return tap("b")
        if kind == "item_action":
            return self._select(scr, 0) if self.intent else tap("b")
        if kind == "pc_root":
            self.menu_context = 'pc'
            return self._select(scr, 0) if self.goal.key.startswith("party_") else tap("b")
        if kind == 'change_box':
            self.menu_context = 'pc'
            target = s.next_free_box if self.goal.key == 'party_box' else self.collection.project.get('box') if self.goal.key == 'party_collection' and self.collection.project else None
            self.reason = 'Select a storage box with room for new catches'
            return tap('b') if target is None or target == s.active_box else self._select(scr, target)
        if kind == "pc":
            self.menu_context = 'pc'
            if not self.goal.key.startswith("party_"):
                return tap("b")
            if scr.cursor and scr.cursor[0] == 10:
                return self._select(scr, 0)
            if self.goal.key == 'party_box' or (self.goal.key == 'party_collection' and len(s.party)<6 and self.collection.project and self.collection.project.get('box') != s.active_box):
                self.reason = 'Change the active storage box without releasing any Pokémon'
                return self._select(scr, 3)
            self.pc_operation = "deposit" if len(s.party) >= 6 else "withdraw"
            if self._pc_target(s) is None:
                return tap("b")
            return self._select(scr, 1 if self.pc_operation == "deposit" else 0)
        if kind == "dialogue":
            if not s.in_battle and ("NO SURF" in text or "NO PLACE TO GET OFF" in text):
                self._remember_failure(s, 'Surf was rejected at this shoreline')
                self.watch.expected = None
                self.intent = None
                self.field_move = None
                self.nav.path.clear()
                self.reason = "Leave the rejected Surf menu and find a reachable shoreline"
                return tap("b", 6, 24)
            if self.intent and self.intent.kind == "fight" and ("DISABLED" in text or "NO PP" in text):
                self.intent = None
            if self.goal.key.startswith('collect_') or self.collection.completed_champion and s.map in LEAGUE:
                self.reason = 'Advance the collection interaction'
                return tap('a',6,24)
            self.reason = "Advance dialogue and wait for the next decision"
            accepting = scr.shop or any(row.strip("? ") == "HEAL" for row in scr.rows)
            return tap("a" if accepting or self.shopping or self.selling or self.intent or s.in_battle or s.playtime_seconds == 0 or "EVOLV" in text or "WHAT?" in text else "b", 6, 24)
        if s.in_battle:
            return wait()
        if not s.started or (s.playtime_seconds == 0 and not s.party):
            return tap("a", 6, 24)
        if self.intent and self.intent.kind in ("item", "field", "reorder") and (s.frame - self.intent_since < 60 or scr.pause_menu):
            self.mode = "waiting for the menu"
            return wait()
        return self._overworld(s, mem)

    def _overworld(self, s, mem):
        self.menu_context = None
        self.intent = None
        self.shopping = False
        self.selling = False
        pos = (s.map, s.x, s.y)
        if needs_healing(s.party):
            self.heal_latch = True
        if self.heal_latch and all(p.hp == p.max_hp and not p.status for p in s.party) and not needs_healing(s.party):
            self.heal_latch = False
        league_rooms = {MAPS[n] for n in ("LORELEIS_ROOM", "BRUNOS_ROOM", "AGATHAS_ROOM", "LANCES_ROOM", "CHAMPIONS_ROOM")}
        in_league = s.map in league_rooms
        goal = healing_goal(s) if self.heal_latch and not in_league else self.goal
        if not s.box_full and not self.heal_latch and not goal.key.startswith(('party_', 'teach_', 'catch_', 'collect_')) and 'Pokecenter' in WORLD.get(s.map, {}).get('name', '') and WORLD[s.map]['width'] == 14:
            weakest = reserve_to_deposit(s)
            if weakest is not None:
                p = s.party[weakest]
                upgrades = [(potential(sid, s.party) + level * 10, sid) for sid, level in s.boxed_pokemon
                            if level >= max(mon.level for mon in s.party) * 0.5
                            and not any(mon.species == sid for mon in s.party)]
                if upgrades and max(upgrades)[0] > potential(p.species, [mon for i, mon in enumerate(s.party) if i != weakest]) + p.level * 10 + 80:
                    self.storage_species = max(upgrades)[1]
                    self.storage_map = s.map
                    goal = Goal('party_upgrade', 'Bring a stronger reserve onto the team',
                                'Swap an underused reserve for a useful Pokémon already in storage', ((s.map, 13, 4),), 'up', True)
        if in_league:
            for target in sorted(range(len(s.party)), key=lambda i: s.party[i].level, reverse=True):
                mon = s.party[target]
                if mon.level < 35:
                    continue
                for item, qty in s.items:
                    if qty and mon.hp == 0 and item in (ITEMS["REVIVE"], ITEMS["MAX_REVIVE"]):
                        return self._use_item(s, item, target)
                if mon.hp > 0:
                    depleted = any(move and not pp and MOVES.get(move, {}).get("power")
                                   for move, pp in zip(mon.moves, mon.pp))
                    if depleted:
                        for item, qty in s.items:
                            if qty and item in (ITEMS["ELIXER"], ITEMS["MAX_ELIXER"]):
                                return self._use_item(s, item, target)
                    choices = [(min(mon.max_hp - mon.hp, amount), item) for item, amount in HEALING.items()
                               if any(mid == item and qty for mid, qty in s.items)
                               and (mon.hp < mon.max_hp * 0.8 or mon.status & CURES.get(item, 0))]
                    if choices:
                        return self._use_item(s, max(choices)[1], target)
        if self.collection.project and len(s.items) >= 18:
            for item,qty in s.items:
                if item not in {ITEMS[n] for n in ('RARE_CANDY','HP_UP','PROTEIN','IRON','CARBOS','CALCIUM')}:
                    continue
                candidates = [i for i,p in enumerate(s.party) if p.level<100]
                if not candidates:
                    continue
                parent = self.collection.project.get('parent')
                target = next((i for i in candidates if s.party[i].species==parent),max(candidates,key=lambda i:s.party[i].level))
                signature = (item,qty,s.party[target].species,s.party[target].level)
                if signature not in self.supply_attempts:
                    self.supply_attempts.add(signature)
                    return self._use_item(s,item,target)
        ball_count = sum(qty for item, qty in s.items if item in BALLS)
        medicine = sum(qty for item, qty in s.items if item in HEALING)
        bag_full = len(s.items) >= 18 and self._sale_index(s) is not None
        if ball_count < 2 or (medicine == 0 and (s.map in (2, 56) or WORLD.get(s.map, {}).get('name', '').endswith('Gym'))) or bag_full:
            self.stock_latch = True
        elif ball_count >= 2 and medicine and not bag_full:
            self.stock_latch = False
        if s.map == MAPS["INDIGO_PLATEAU_LOBBY"]:
            self.stock_latch = medicine < 10 or dict(s.items).get(ITEMS["REVIVE"], 0) < 5
        if self.stock_latch and not self.heal_latch and not in_league and goal.key != 'party_box' and self.completed.get("pokedex"):
            targets = []
            for m, world in WORLD.items():
                if s.map == MAPS["INDIGO_PLATEAU_LOBBY"] and m != s.map:
                    continue
                stock = DATA["marts"].get(world["name"], [])
                if bag_full or shopping_item(s.items, stock, s.money, s.map == MAPS["INDIGO_PLATEAU_LOBBY"]) is not None:
                    clerk = next((o for o in world["objects"] if o[2] == "SPRITE_CLERK"), None)
                    if clerk and clerk[0] == 0:
                        targets.append((m, 2, clerk[1]))
            if targets:
                goal = Goal("restock", "Restock supplies", "Buy useful balls and medicine with a cash reserve", tuple(targets), "left", True)
            else:
                self.stock_latch = False
        if self.heal_latch:
            # Medicine is useful when no known route to a center can be followed.
            for target, mon in enumerate(s.party):
                index = healing_item(s.items, mon)
                if index is not None and (mon.status & 8 or mon.hp < mon.max_hp * 0.25):
                    self.intent = Decision("item", index, target, "Treat the party before walking farther")
                    self.intent_since = s.frame
                    return tap("start")
        if goal.key == "thunder" and not event_set(s.event_flags, "EVENT_2ND_LOCK_OPENED"):
            goal = self._trash_goal(s)
        if not self.heal_latch and not in_league and goal.key not in ('restock','party_box'):
            collection_goal = self.collection.choose(s, self.nav, self.rng, goal)
            if collection_goal:
                self.next_goal = goal.to_dict() if not goal.key.startswith(('collect_', 'party_collection')) else self.next_goal
                goal = collection_goal
        if s.map in (MAPS["ROCKET_HIDEOUT_ELEVATOR"], MAPS["CELADON_MART_ELEVATOR"], MAPS["SILPH_CO_ELEVATOR"]):
            rocket_lift = s.map == MAPS["ROCKET_HIDEOUT_ELEVATOR"]
            if self.elevator_exit and not rocket_lift:
                self.mode = "leaving the elevator"
                return tap("left" if s.x > 1 else "down", 8, 12)
            if self.elevator_exit:
                self.mode = "leaving the elevator"
                return tap("left" if s.x > 2 else "right" if s.x < 2 else "up", 8, 12)
            self.elevator_floor = "B4F" if goal.key == "hideout_elevator" else "B1F"
            goal = Goal("hideout_elevator", "Use the Rocket Hideout elevator", f"Select {self.elevator_floor} and leave the lift",
                        ((s.map, 1, 2) if rocket_lift else (s.map, 3, 1),), "up", True)
        else:
            self.elevator_exit = False
        self.goal = goal
        if self.next_goal and self.next_goal['id'] == goal.key:
            next_badge = next((row['title'] for row in self.journey if not row['done']), 'Celebrate the Champion victory')
            self.next_goal = {'id': 'milestone', 'title': next_badge}
        self.reason = goal.reason
        if self.progress_goal != goal.key:
            self.progress_goal = goal.key
            self.progress_frame = s.frame
            self.goal_distance = None
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
            target = next((i for i,p in enumerate(s.party) if p.species==project['parent']),None)
            if target is not None:
                return self._use_item(s,ITEMS[project['evolution']['requirement']],target) or tap('b')
        if goal.key == 'collect_train' and project:
            target = next((i for i,p in enumerate(s.party) if p.species==project['parent']),None)
            if target and s.party[target].hp:
                self.order_species = s.party[target].species
                self.order_stage = 'source'
                self.intent = Decision('reorder',target,reason='Train a partner toward its next evolution')
                self.intent_since = s.frame
                return tap('start')
        if goal.key == 'collect_hunt' and project and pos in goal.targets:
            if project['method']=='fish':
                direction = goal.facing_at(pos)
                if mem[W_FACING] != FACING[direction]:
                    return tap(direction,4,12)
                return self._use_item(s,ITEMS[project['rod']]) or tap('b')
        if goal.key.startswith("teach_"):
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
                self.order_species = s.party[target].species
                self.order_stage = 'source'
                self.intent = Decision('reorder', target, reason='Lead with the best available matchup')
                self.intent_since = s.frame
                return tap('start')
        if not goal.key.startswith(("collect_", "party_collection")) and (goal.key == "train_league_partner" or self.development_index is not None and s.frame < self.development_until):
            target = league_partner(s) if goal.key == 'train_league_partner' else self.development_index
            if target is not None and target != 0:
                self.intent = Decision("reorder", target, reason="Give the partner the lead position while training")
                self.order_species = s.party[target].species
                self.order_stage = "source"
                self.intent_since = s.frame
                return tap("start")
        if s.map in VICTORY_MAPS:
            task = boulder_task(s)
            if task:
                if not mem[0xD728] & 1:
                    target = next((i for i, p in enumerate(s.party) if 70 in p.moves), None)
                    if target is not None:
                        self.field_move = "STRENGTH"
                        self.intent = Decision("field", target, reason="Use Strength to move the boulder")
                        self.intent_since = s.frame
                        self.mode = "using Strength"
                        self.watch.begin('field', 'Wait for Strength to take effect', s,
                                         ActionWatch.value('field', s, '', mem[0xD700] | ((mem[0xD728] & 1) << 2)))
                        return tap("start")
                direction = self.boulders.route(s, self.nav, task)
                if direction:
                    self.mode = "moving a boulder onto the switch"
                    self.reason = "Find legal pushes and keep room to walk around the boulder"
                    self.progress_frame = s.frame
                    return tap(direction, 16, 16)
            if s.map == MAPS["VICTORY_ROAD_2F"] and not event_set(s.event_flags, "EVENT_VICTORY_ROAD_3_BOULDER_ON_SWITCH2"):
                goal = Goal("victory_ascent", "Reach the upper boulder puzzle", "Climb to the third floor", ((MAPS["VICTORY_ROAD_3F"], 23, 7),))
            elif s.map == MAPS["VICTORY_ROAD_3F"] and not event_set(s.event_flags, "EVENT_VICTORY_ROAD_2_BOULDER_ON_SWITCH2"):
                goal = Goal("victory_drop", "Follow the boulder downstairs", "Drop through the hole to reach the final switch", ((MAPS["VICTORY_ROAD_2F"], 22, 16),))
        if pos in goal.targets:
            if goal.key == "snorlax":
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
            if goal.key not in ("heal", "restock"):
                social = None if goal.key.startswith(("collect_", "party_collection")) else self._purposeful_detour(s, mem, goal)
                if social:
                    return social
                social = self._social_interaction(s, mem)
                if social:
                    return social
            curiosity = 0 if goal.key in ("heal", "restock") else self.exploration
            if s.map in MANSION_MAPS:
                direction = self.mansion.route(s, goal.targets, self.nav)
                if direction == "switch":
                    self.mode = "using the statue switch"
                    return tap("up", 4, 12) if mem[W_FACING] != FACING["up"] else tap("a")
            else:
                direction = self.nav.guided(pos, goal.targets, s.frame, self.rng, curiosity) if goal.targets else None
            self.mode = "following objective"
            path = self.mansion.path if s.map in MANSION_MAPS else self.nav.path
            remaining = len(path) if path else None
            if remaining is not None and (self.goal_distance is None or remaining < self.goal_distance):
                self.goal_distance = remaining
                self.progress_frame = s.frame
            if direction is None:
                self.mode = "exploring obstacle"
                self.reason = "The route is blocked or unknown, explore and learn a reachable path"
                direction = self.nav.explore(pos, s.frame, self.rng)
            if s.frame - self.progress_frame > 2400:
                return self._recover(s)
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
            self.field_move = "SURF"
            self.intent = Decision("field", target, reason="Use Surf to cross the water")
            self.intent_since = s.frame
            self.mode = "using Surf"
            self.watch.begin('field', 'Enter the water with Surf', s,
                             ActionWatch.value('field', s, '', mem[0xD700] | ((mem[0xD728] & 1) << 2)))
            return tap("start")
        if self.nav.can_cut and ((world.get("tileset") == "OVERWORLD" and tree == 0x3D)
                                 or (world.get("tileset") == "GYM" and tree == 0x50)):
            # Read the visible tile so a tree removed on this visit is not cut repeatedly.
            live_tile = mem[W_TILEMAP + (9 + dy * 2) * 20 + 8 + dx * 2]
            if live_tile == tree:
                if mem[W_FACING] != FACING[direction]:
                    return tap(direction, 4, 12)
                target = next(i for i, p in enumerate(s.party) if 15 in p.moves)
                self.field_move = "CUT"
                self.intent = Decision("field", target, reason="Use Cut to open the route")
                self.intent_since = s.frame
                self.mode = "using Cut"
                self.watch.begin('field', 'Clear the tree and continue through the opening', s,
                                 ActionWatch.value('field', s, '', mem[0xD700] | ((mem[0xD728] & 1) << 2)))
                return tap("start")
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

    def _shopping_item(self, s, stock):
        p = self.collection.project
        if self.goal.key == 'collect_stone' and p and s.map == MAPS['CELADON_MART_4F']:
            item = ITEMS[p['evolution']['requirement']]
            return item if item in stock and not dict(s.items).get(item) and s.money >= 2500 and len(s.items)<20 else None
        return shopping_item(s.items, stock, s.money, s.map == MAPS['INDIGO_PLATEAU_LOBBY'], collecting=self.collection.pace!='focused' or self.collection.completed_champion)

    def _pc_target(self, snapshot):
        if self.pc_operation == "deposit":
            return reserve_to_deposit(snapshot) if len(snapshot.party) >= 6 and not snapshot.box_full else None
        if self.goal.key == 'party_collection_space':
            return None
        if self.goal.key == 'party_collection' and self.collection.project:
            sid = self.collection.project['parent']
            return next((i for i,(species,level) in enumerate(snapshot.boxed_pokemon) if species==sid),None) if len(snapshot.party)<6 else None
        move = {"party_cut": 15, "party_surf": 57, "party_strength": 70}.get(self.goal.key)
        candidates = [(level, i) for i, (species, level) in enumerate(snapshot.boxed_pokemon)
                      if (species == self.storage_species if self.goal.key == 'party_upgrade' else move in SPECIES.get(species, {}).get("hms", []))]
        return max(candidates)[1] if candidates and len(snapshot.party) < 6 else None

    @staticmethod
    def _sale_index(snapshot):
        return next((i for i, (item, qty) in enumerate(snapshot.items)
                     if qty and (item == ITEMS["NUGGET"] or 201 <= item <= 250)), None)

    def _use_item(self, snapshot, item, target=0):
        index = next((i for i, (mid, qty) in enumerate(snapshot.items) if mid == item and qty), None)
        if index is None:
            return None
        self.intent = Decision("item", index, target, self.goal.reason)
        self.intent_since = snapshot.frame
        self.mode = "using an item"
        self.watch.begin('item', 'Verify the item changes the inventory or its recipient', snapshot,
                         ActionWatch.value('item', snapshot, '', 0))
        return tap("start")

    def _recover(self, snapshot):
        self.recoveries += 1
        self.intent = None
        blocked = self.nav.blocked.copy()
        self.nav.restore()
        self.nav.blocked.update(blocked)
        self.goal_distance = None
        self.progress_frame = snapshot.frame
        self.recovery_until = snapshot.frame + 180
        return self._recovery_step(snapshot)

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

    def _purposeful_detour(self, s, mem, main_goal):
        pos = (s.map, s.x, s.y)
        if self.heal_latch or main_goal.key.startswith(('heal', 'restock', 'train_', 'catch_', 'party_', 'teach_', 'league', 'collect_')) or s.map in MANSION_MAPS | VICTORY_MAPS:
            self.excursion = None
            return None
        if self.excursion:
            goal, expires, key = self.excursion
            if s.frame >= expires or s.map != goal.targets[0][0]:
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
        if s.frame < self.next_conversation or not self.exploration or self.rng.random() > self.exploration * 0.15:
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
                        f'Train {s.party[trainee].nick or s.party[trainee].name} in nearby manageable encounters', grass)
            self.development_until = s.frame + 2400
            self.development_cooldown = s.frame + 18000
            self.development_index = trainee
            self.excursion = (goal, self.development_until, 'development')
            if trainee != 0:
                self.order_species = s.party[trainee].species
                self.order_stage = 'source'
                self.intent = Decision('reorder', trainee, reason=goal.reason)
                self.intent_since = s.frame
                return tap('start')
            return self._purposeful_detour(s, mem, main_goal)
        positions = self.nav.live_positions if self.nav.live_map == s.map else []
        candidates = []
        for i, o in enumerate(w.get('objects', [])):
            if o[2] in ('SPRITE_NURSE', 'SPRITE_CLERK', 'SPRITE_BOULDER', 'SPRITE_SNORLAX', 'SPRITE_BLUE', 'SPRITE_OAK') or (s.map, o[0], o[1]) in self.nav.cleared_objects:
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
