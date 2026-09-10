"""Random-with-guardrails v2.

Still random at heart, but it reads the screen and RAM so it stops doing the obviously dumb
things: it explores tiles it hasn't stood on (curiosity), remembers walls, only throws balls it
actually has, picks moves that have PP, switches or runs when the active Pokémon is nearly dead,
walks back to a known Pokémon Center when the party is beat up, and breaks out of any loop by
mashing random buttons when the screen has not changed for a while.
"""
from __future__ import annotations

import logging
import random
from collections import deque

from ..ram import MAP_NAMES, MOVES, Snapshot
from ..screen import Screen, W_ENEMY_HP, W_ENEMY_MAX_HP, W_PLAYER_MON_NUMBER
from .base import Action, Policy, PolicyContext
from .naming import NamingController

log = logging.getLogger("pokesim.policy")

DIRS = ("up", "down", "left", "right")
DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
BALL_IDS = {1, 2, 3, 4, 8}            # master, ultra, great, poké, safari
LOOP_DECISIONS = 20                   # identical screen+position for this many decisions -> random burst
EPSILON = 0.04                        # chance of a completely random press on any decision, anywhere
LONG_BATTLE_TURNS = 25                # after this many menu visits in one battle, get increasingly random
BURST_LEN = 12
BLOCKED_TTL = 3000                    # decisions a wall is remembered for (NPCs move, so not forever)


def tap(b, hold=6, gap=6):
    return Action(b, hold, gap)


class SmartRandomPolicy(Policy):
    name = "smart_random"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.naming = NamingController(seed)
        self.mode = "boot"
        self.n = 0
        self.last_dir = "down"
        self.last_hash = None
        self.repeat = 0
        self.burst = 0
        self.loops_broken = 0
        # exploration memory
        self.visits: dict[tuple, int] = {}
        self.blocked: dict[tuple, int] = {}
        self.edges: dict[tuple, set] = {}
        self.last_pos = None
        self.last_move: tuple | None = None       # (pos, dir) of the last directional press
        self.fails: dict[tuple, int] = {}
        self.centers: set[int] = set()
        self.last_move_used: tuple | None = None    # (party index, move slot) chosen last turn
        self.battle_turns = 0
        self.heal_target: int | None = None
        self.path: deque = deque()

    # ---------------- persistence ----------------
    def state_dict(self) -> dict:
        return {
            "naming": self.naming.state_dict(),
            "visits": [[list(k), v] for k, v in self.visits.items()],
            "edges": [[list(k), [list(x) for x in v]] for k, v in self.edges.items()],
            "centers": sorted(self.centers), "loops_broken": self.loops_broken,
            "blocked": [[list(k[0]), k[1], v - self.n] for k, v in self.blocked.items() if v > self.n],
        }

    def load_state_dict(self, d: dict):
        self.naming.load_state_dict(d.get("naming", {}))
        self.visits = {tuple(k): v for k, v in d.get("visits", [])}
        self.edges = {tuple(k): {tuple(x) for x in v} for k, v in d.get("edges", [])}
        self.centers = set(d.get("centers", []))
        self.loops_broken = d.get("loops_broken", 0)
        self.blocked = {(tuple(pos), dr): self.n + ttl for pos, dr, ttl in d.get("blocked", [])}

    def reset(self):
        self.__init__(seed=self.rng.random())

    def describe(self) -> str:
        return f"smart_random ({self.mode})"

    # ---------------- main entry ----------------
    def step(self, ctx: PolicyContext) -> list[Action]:
        s = ctx.snapshot
        mem = ctx.mem
        self.n += 1
        scr = Screen(mem)
        naming_action = self.naming.step(scr, s)
        if naming_action is not None:
            self.mode = "naming"
            self.repeat = self.burst = 0
            return [naming_action]
        self._track(s)

        h = hash((s.map, s.x, s.y, scr.text))
        self.repeat = self.repeat + 1 if h == self.last_hash else 0
        self.last_hash = h
        if self.burst > 0:
            self.burst -= 1
            self.mode = "random burst"
            return [tap(self.rng.choice(DIRS + ("a", "b", "b", "start")), self.rng.randint(4, 12), 4)]
        if self.repeat >= LOOP_DECISIONS:
            self.loops_broken += 1
            self.burst = BURST_LEN
            self.repeat = 0
            log.info("loop detected on %s (%s), random burst #%d", s.map_name, self.mode, self.loops_broken)
            return [tap("b")]
        if self.rng.random() < EPSILON:
            self.mode = "random press"
            return [tap(self.rng.choice(DIRS + ("a", "b", "start")), self.rng.randint(4, 12), 4)]
        if not s.in_battle:
            self.battle_turns = 0

        if not s.started:
            return self._intro(scr)
        if s.in_battle:
            return self._battle(s, scr, mem)
        if scr.yes_no:
            self.mode = "yes/no"
            return [tap("a" if self.rng.random() < 0.7 else "b", 6, 8)]
        if scr.shop:
            self.mode = "shop"
            return self._shop(s)
        if scr.pc:
            self.mode = "pc"
            return [tap("b" if self.rng.random() < 0.6 else "a", 6, 8)]
        if scr.list_menu or scr.pause_menu or s.start_menu:
            self.mode = "menu"
            x = self.rng.random()
            if x < 0.7:
                return [tap("b", 6, 6)]
            if x < 0.9:
                return [tap(self.rng.choice(("up", "down")), 6, 4)]
            return [tap("a", 6, 8)]
        if s.textbox:
            self.mode = "text"
            return [tap("a" if self.rng.random() < 0.9 else "b", 6, 8)]
        return self._overworld(s, ctx)

    # ---------------- pieces ----------------
    def _intro(self, scr: Screen) -> list[Action]:
        self.mode = "intro"
        x = self.rng.random()
        if x < 0.8:
            return [tap("a", 6, 8)]
        if x < 0.9:
            return [tap("start", 6, 8)]
        return [tap(self.rng.choice(DIRS), 6, 4)]

    def _shop(self, s: Snapshot) -> list[Action]:
        # BUY is the first option; A-mashing buys one of whatever is first in the list (balls/potions
        # early on). With no money, back out.
        if s.money < 200 or self.rng.random() < 0.3:
            return [tap("b", 6, 8)]
        return [tap("a", 6, 10)]

    def _battle(self, s: Snapshot, scr: Screen, mem) -> list[Action]:
        r = self.rng
        if scr.battle_menu:
            self.mode = "battle"
            self.battle_turns += 1
            if self.battle_turns > LONG_BATTLE_TURNS and r.random() < min(0.6, (self.battle_turns - LONG_BATTLE_TURNS) / 30):
                # a battle that drags on is probably going nowhere: try random things, including running
                self.mode = "battle (long, random)"
                return [tap(r.choice(DIRS + ("a", "b")), 6, 8) for _ in range(r.randint(1, 3))]
            active = mem[W_PLAYER_MON_NUMBER]
            active = active if active < len(s.party) else 0
            me = s.party[active] if s.party else None
            enemy_hp = (mem[W_ENEMY_HP] << 8) | mem[W_ENEMY_HP + 1]
            enemy_max = max(1, (mem[W_ENEMY_MAX_HP] << 8) | mem[W_ENEMY_MAX_HP + 1])
            my_frac = (me.hp / me.max_hp) if me and me.max_hp else 1.0
            ball_idx = next((i for i, (item, _) in enumerate(s.items) if item in BALL_IDS), None)
            others = [i for i, p in enumerate(s.party) if p.hp > 0 and i != active]
            home = [tap("up", 4, 4), tap("left", 4, 4)]          # cursor -> FIGHT (top-left of the 2x2 menu)
            x = r.random()
            if x < 0.03:
                self.mode = "battle (random)"
                return [tap(r.choice(DIRS + ("a", "b")), 6, 8)]
            if s.in_battle == 1 and ball_idx is not None and (enemy_hp / enemy_max < 0.5 or x < 0.15) and x < 0.75:
                self.mode = "battle (throw)"
                n = len(s.items)
                return home + [tap("down", 4, 4), tap("a", 6, 20)] + [tap("up", 3, 3)] * n + \
                    [tap("down", 3, 3)] * ball_idx + [tap("a", 6, 20)]
            if my_frac < 0.25 and others and x < 0.55:
                self.mode = "battle (switch)"
                k = r.choice(others)
                return home + [tap("right", 4, 4), tap("a", 6, 20)] + [tap("up", 3, 3)] * 6 + \
                    [tap("down", 3, 3)] * k + [tap("a", 6, 12), tap("a", 6, 20)]
            if my_frac < 0.2 and s.in_battle == 1 and not others and x < 0.6:
                self.mode = "battle (run)"
                return home + [tap("down", 4, 4), tap("right", 4, 4), tap("a", 6, 20)]
            # fight: prefer damaging moves, never a status move twice in a row
            self.mode = "battle (fight)"
            k = self._pick_move(mem, active)
            self.last_move_used = (active, k)
            return home + [tap("a", 6, 12)] + [tap("up", 3, 3)] * 3 + [tap("down", 3, 3)] * k + [tap("a", 6, 20)]
        if scr.list_menu:
            self.mode = "battle (back out)"
            return [tap("b", 6, 8)]
        if s.textbox:
            self.mode = "battle (text)"
            return [tap("a", 6, 8)]
        self.mode = "battle (?)"
        return [tap(r.choice(("a", "a", "b")), 6, 8)]

    @staticmethod
    def _moves_with_pp(mem, active: int) -> list[tuple[int, int]]:
        """[(slot, move id)] for moves that still have PP."""
        from ..ram import PARTY_STRUCT, W_PARTY_MONS
        base = W_PARTY_MONS + active * PARTY_STRUCT
        out = []
        for i in range(4):
            move = mem[base + 8 + i]
            pp = mem[base + 0x1D + i] & 0x3F
            if move and pp:
                out.append((i, move))
        return out

    def _pick_move(self, mem, active: int) -> int:
        moves = self._moves_with_pp(mem, active)
        if not moves:
            return 0
        weights = []
        for slot, mid in moves:
            power = MOVES.get(mid, {}).get("power", 40)
            w = 1.0 + power                       # damaging moves dominate; status moves get a small share
            if self.last_move_used == (active, slot) and power == 0:
                w = 0.0                           # Barrier, Growl, ... never twice in a row
            weights.append(w)
        if sum(weights) == 0:
            weights = [1.0] * len(moves)
        return self.rng.choices([slot for slot, _ in moves], weights)[0]

    # ---------------- overworld: curiosity + wall memory + heal loop ----------------
    def _track(self, s: Snapshot):
        if not s.started or s.in_battle:
            return
        pos = (s.map, s.x, s.y)
        if pos != self.last_pos:
            self.visits[pos] = self.visits.get(pos, 0) + 1
            if self.last_pos is not None and (self.last_pos[0] == s.map or self.last_move):
                self.edges.setdefault(self.last_pos, set()).add(pos)
                self.edges.setdefault(pos, set()).add(self.last_pos)
            if "Pokecenter" in MAP_NAMES.get(s.map, "") or "Pokémon Center" in MAP_NAMES.get(s.map, ""):
                self.centers.add(s.map)
            self.last_pos = pos
        elif self.last_move and self.last_move[0] == pos:
            # A press can just turn the player; call it a wall after two failed tries from this tile.
            key = (pos, self.last_move[1])
            self.fails[key] = self.fails.get(key, 0) + 1
            if self.fails[key] >= 2:
                self.blocked[key] = self.n + BLOCKED_TTL
        self.last_move = None

    def _overworld(self, s: Snapshot, ctx: PolicyContext) -> list[Action]:
        r = self.rng
        pos = (s.map, s.x, s.y)
        hp = sum(p.hp for p in s.party)
        max_hp = max(1, sum(p.max_hp for p in s.party))
        # heal loop: beat up, know a Pokémon Center, and there is a learned path to it
        if s.party and hp / max_hp < 0.3 and self.centers and s.map not in self.centers:
            step = self._path_step(pos)
            if step:
                self.mode = "heading to heal"
                self.last_move = (pos, step)
                self.last_dir = step
                return [tap(step, 24, 2)]
        if s.map in self.centers and s.party and hp / max_hp < 0.9:
            self.mode = "at the center"      # wander + talk; the nurse heals on A
            if r.random() < 0.35:
                return [tap("a", 6, 10)]
        else:
            self.mode = "exploring"
        if ctx.stuck_seconds > 90:
            self.mode = "unstick"
            d = r.choice([d for d in DIRS if d != self.last_dir])
            self.last_move = (pos, d)
            self.last_dir = d
            return [tap("b", 4, 2), tap(d, r.randint(24, 60), 2)]
        x = r.random()
        if x < 0.12:
            return [tap("a", 6, 8)]
        if x < 0.14:
            return [tap("start", 6, 8)]
        if x < 0.16:
            return [tap("b", 4, 4)]
        d = None
        if x < 0.85:
            d = self._frontier_step(pos)
            if d:
                self.mode = "exploring (frontier)"
        if d is None:
            d = self._curious_dir(pos)
        self.last_move = (pos, d)
        self.last_dir = d
        return [tap(d, r.randint(22, 40), 1)]

    def _unexplored_dirs(self, pos) -> list[str]:
        m, x, y = pos
        return [d for d in DIRS if (m, x + DELTA[d][0], y + DELTA[d][1]) not in self.visits
                and self.blocked.get((pos, d), 0) <= self.n]

    def _frontier_step(self, pos) -> str | None:
        """Walk (over learned paths) to the nearest tile that still has an untried neighbour."""
        here = self._unexplored_dirs(pos)
        if here:
            return self.rng.choice(here)
        prev = {pos: None}
        q = deque([pos])
        goal = None
        n = 0
        while q and n < 4000:
            cur = q.popleft()
            n += 1
            if cur != pos and self._unexplored_dirs(cur):
                goal = cur
                break
            for nxt in self.edges.get(cur, ()):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        if goal is None:
            return None
        while prev[goal] != pos:
            goal = prev[goal]
        return self._dir_between(pos, goal)

    def _curious_dir(self, pos) -> str:
        m, x, y = pos
        weights = []
        for d in DIRS:
            dx, dy = DELTA[d]
            v = self.visits.get((m, x + dx, y + dy), 0)
            w = 1.0 / (1.0 + v) ** 1.5
            if self.blocked.get((pos, d), 0) > self.n:
                w *= 0.05
            if d == self.last_dir:
                w *= 1.6
            elif d == OPPOSITE[self.last_dir]:
                w *= 0.5
            weights.append(w + 0.01)
        return self.rng.choices(DIRS, weights)[0]

    def _path_step(self, pos) -> str | None:
        """BFS over learned edges to the nearest tile on a Pokémon Center map; return the first direction."""
        if self.path and self.path[0][0] == pos:
            self.path.popleft()
            if self.path:
                return self._dir_between(pos, self.path[0][0])
        prev = {pos: None}
        q = deque([pos])
        goal = None
        while q:
            cur = q.popleft()
            if cur[0] in self.centers:
                goal = cur
                break
            for nxt in self.edges.get(cur, ()):
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        if goal is None:
            return None
        chain = []
        while goal is not None:
            chain.append(goal)
            goal = prev[goal]
        chain.reverse()
        self.path = deque((p, None) for p in chain[1:])
        return self._dir_between(pos, chain[1]) if len(chain) > 1 else None

    @staticmethod
    def _dir_between(a, b) -> str | None:
        if a[0] != b[0]:
            return None                      # a warp: the step that took us there is unknown; let curiosity handle it
        dx, dy = b[1] - a[1], b[2] - a[2]
        for d, (ddx, ddy) in DELTA.items():
            if (dx, dy) == (ddx, ddy):
                return d
        return None
