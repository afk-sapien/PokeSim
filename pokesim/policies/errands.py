"""The heal errand and the social detour of Red, Blue and Yellow (planning/errand.py).

The shop errand is the ShoppingController (policies/shopping.py). None of their state is saved: a reload
starts with no heal, shop visit or detour under way, and only the detour's waits, which run on the play
clock, carry over.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pokecore.gen1 import W_FACING

from ..planning import boss
from ..planning.errand import Errand
from ..planning.ledger import PP
from ..planning.stance import TRAIN
from ..runtime.supervision import CHAT_REST, DETOUR_REST, LOOK_AROUND, PARTNER_TRAINING
from ..strategy_data import WORLD
from .battle import needs_healing
from .ledger import battle_room
from .menus import tap
from .navigation import DIRS, FACING
from .pickups import Pickups, ground_item
from .progression import Goal, healing_goal
from .puzzles import MANSION_MAPS, VICTORY_MAPS
from .team import development_candidate

EXPLORATION_CHANCE = 0.12
# A development excursion lasts until its partner gains a level. It ends sooner once this many frames
# pass without the partner gaining any experience, so grass without encounters cannot hold it.
DEVELOPMENT_STALL = 2400


@dataclass
class Heal(Errand):
    """The walk to a Pokémon Center while the party needs one.

    ``latched`` holds the heal from the step the party needs one until it is whole again, so a heal once
    started is finished. ``pp`` says the heal is for spent PP, which the journal notes once the nurse is
    done. ``before_boss`` says the boss check sends the party to heal before the boss, which holds the heal
    until a later check says otherwise. The nurse's talk is the usual arrival at a person."""
    key: ClassVar[str] = 'heal'
    latched: bool = False
    pp: bool = False
    before_boss: bool = False

    def update(self, policy, snapshot):
        """Hold the heal while the party needs one, and end it once the party is whole."""
        party = snapshot.party
        # A status the bag cures is cured in the field (_overworld), so it holds no heal.
        if needs_healing(party, snapshot.items):
            if not self.latched:
                # A heal its spent PP called for says so in the journal once the nurse is done.
                self.pp = battle_room(party)[PP] == 0
            self.latched = True
        if all(p.hp == p.max_hp and not p.status for p in party) and not needs_healing(party):
            if self.latched and self.pp:
                policy.collection.activity_events.append(boss.pp_heal_event(snapshot.map_name))
            self.pp = False
            self.latched = False
            policy.escape_attempted = False
        if self.before_boss:
            self.latched = True

    def offer(self, policy, snapshot):
        return (healing_goal(snapshot), None) if self.latched else (None, None)


@dataclass
class Detour(Errand):
    """A short walk off the goal under way: to a nearby item, person or sign that catches the player's
    interest, or a development excursion that trains a promising partner in nearby grass. Beside the path,
    a person or sign one step away may be talked to as well (``chat``).

    The detour is never offered to the decision. It runs on the walk at the same point of the step as
    before, so its random draws stay where they were. It notes the goal it runs and the goal behind it in
    ``ran``, and the step makes them the goal and the next goal once it ends (StrategicPolicy.step), so the
    walk itself never writes the goal.

    ``excursion`` is the detour under way as (goal, expiry frame, key), ``development`` the partner a
    development excursion trains, with its level and experience at the start and the frame it last gained
    experience, and ``development_index`` its party slot. ``social_target`` is the chat about to start and
    ``pending_social`` the talk or read that counts once its text shows. ``next_conversation`` and
    ``development_cooldown`` are the play clock frames the next detour and the next excursion wait for, so a
    reload neither restarts nor stretches them.
    """
    key: ClassVar[str] = 'detour'
    excursion: tuple | None = None
    development: dict | None = None
    development_index: int | None = None
    social_target: tuple | None = None
    pending_social: tuple | None = None
    next_conversation: int = 0
    development_cooldown: int = 0
    ran: tuple | None = None

    def reset(self):
        """Forget the detour under way. Its waits run on the play clock, so they stay."""
        self.excursion = self.development = self.development_index = None
        self.social_target = self.pending_social = None

    @property
    def developing(self):
        """Whether a development excursion is under way."""
        return self.excursion is not None and self.excursion[2] == 'development'

    def observe(self, policy, snapshot, kind):
        """Count a talk or read once its text shows, or forget it when none shows."""
        if self.pending_social:
            key, started = self.pending_social
            if kind == 'dialogue' or snapshot.in_battle:
                if key not in policy.interactions:
                    policy.interactions[key] = True
                    policy.interaction_count += 1
                self.pending_social = None
            elif snapshot.frame - started > 240:
                self.pending_social = None

    def development_done(self, s):
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

    def act(self, policy, s, mem, main_goal):
        """The press on the walk to ``main_goal`` that starts or follows a detour, or None to walk on."""
        pos = (s.map, s.x, s.y)
        if policy.heal.latched or main_goal.key.startswith(('heal', 'restock', 'train_', 'catch_', 'party_', 'teach_', 'league', 'collect_')) or s.map in MANSION_MAPS | VICTORY_MAPS:
            self.excursion = None
            return None
        if self.excursion:
            goal, expires, key = self.excursion
            ended = self.development_done(s) if key == 'development' else s.frame >= expires
            if ended or s.map != goal.targets[0][0]:
                self.excursion = None
                self.next_conversation = DETOUR_REST.until(policy.clock)
                return None
            self.ran = (goal, main_goal.to_dict())
            policy.reason = goal.reason
            if pos in goal.targets:
                if key == 'development':
                    choices = [(dr, q) for dr, q in policy.nav.neighbors(pos, s.frame) if q in goal.targets]
                    if not choices:
                        self.excursion = None
                        return None
                    direction = policy.rng.choice(choices)[0]
                else:
                    self.excursion = None
                    self.next_conversation = DETOUR_REST.until(policy.clock)
                    policy.mode = 'following a curiosity'
                    facing = goal.facing_at(pos)
                    if mem[W_FACING] != FACING[facing]:
                        self.excursion = (goal, expires, key)
                        return tap(facing, 4, 12)
                    self.pending_social = (key, s.frame)
                    return tap('a')
            else:
                direction = policy.nav.route(pos, goal.targets, s.frame)
                if not direction or len(policy.nav.path) > 20:
                    self.excursion = None
                    self.next_conversation = LOOK_AROUND.until(policy.clock)
                    return None
            policy.mode = 'training a partner' if key == 'development' else 'following a curiosity'
            policy.nav.issued(pos, direction, s.frame)
            return tap(direction, 8, 12)
        if policy.clock < self.next_conversation or policy.rng.random() > EXPLORATION_CHANCE * 0.15:
            return None
        w = WORLD.get(s.map, {})
        if any(p.status for p in s.party) or max((p.hp / max(1, p.max_hp) for p in s.party), default=0) < 0.8:
            return None
        encounters = w.get('encounters', [])
        # The cartridge's grass table prices a battle here. Gen I has no training site picker, so a trainee
        # this map cannot raise waits for a map on the way that can.
        wild = policy.collection.wild
        trainee = development_candidate(s, max((level for _, level in encounters), default=100),
                                        wild.battle_experience(s.map) if wild is not None else None)
        grass = tuple((s.map, x, y) for y, row in enumerate(w.get('tiles', [])) for x, tile in enumerate(row)
                      if tile == 0x52 and abs(x - s.x) + abs(y - s.y) <= 8)
        if trainee is not None and grass and policy.clock >= self.development_cooldown:
            goal = Goal('train_partner', 'Give a promising partner some experience',
                        f'Train {s.party[trainee].nick or s.party[trainee].name} in nearby manageable encounters', grass,
                        kind=TRAIN)
            mon = s.party[trainee]
            self.development = {'partner': (mon.species, mon.nick, mon.dvs), 'level': mon.level,
                                'experience': mon.experience, 'since': s.frame}
            self.development_cooldown = PARTNER_TRAINING.until(policy.clock)
            self.development_index = trainee
            self.excursion = (goal, None, 'development')
            if trainee != 0:
                actions = policy._reorder(s, trainee, goal.reason)
                if actions:
                    return actions
            return self.act(policy, s, mem, main_goal)
        positions = policy.nav.live_positions if policy.nav.live_map == s.map else []
        candidates = []
        for i, o in enumerate(w.get('objects', [])):
            if o[2] in ('SPRITE_NURSE', 'SPRITE_CLERK', 'SPRITE_BOULDER', 'SPRITE_SNORLAX', 'SPRITE_BLUE', 'SPRITE_OAK') or (s.map, o[0], o[1]) in policy.nav.cleared_objects:
                continue
            # An item the bag has no room for, including the Safari Zone's kept prize room, is left alone.
            item = ground_item(o)
            if item and not Pickups.has_space(s, item['item']):
                continue
            x, y = positions[i] if i < len(positions) else o[:2]
            key = f'{s.map}:{o[4]}'
            weight = 3 if (policy.personality == 'Collector') == (o[2] == 'SPRITE_POKE_BALL') else 1
            candidates.append((x, y, key, 'Investigate a nearby item' if o[2] == 'SPRITE_POKE_BALL' else 'Meet someone nearby', weight))
        candidates += [(x, y, f'{s.map}:{name}', 'Read a local sign', 3 if policy.personality == 'Explorer' else 1)
                       for x, y, name in w.get('backgrounds', []) if 'SIGN' in name or 'TRAINER_TIPS' in name]
        candidates = [c for c in candidates if c[2] not in policy.interactions and 1 < abs(c[0] - s.x) + abs(c[1] - s.y) <= 8]
        self.next_conversation = LOOK_AROUND.until(policy.clock)
        if candidates:
            x, y, key, title, _ = policy.rng.choices(candidates, weights=[c[4] for c in candidates])[0]
            approaches = tuple((s.map, x - dx, y - dy, dr) for dr, (dx, dy) in DIRS.items()
                               if policy.nav._tile(w, x - dx, y - dy) in w['passable'])
            if approaches:
                goal = Goal('curiosity', title, f'{policy.personality} detour, then return to {main_goal.title.lower()}',
                            tuple(p[:3] for p in approaches), approaches[0][3], True, approaches=approaches)
                direction = policy.nav.route(pos, goal.targets, s.frame)
                if direction and len(policy.nav.path) <= 16 and all(p[0][0] == s.map for p in policy.nav.path):
                    self.excursion = (goal, s.frame + 900, key)
                    return self.act(policy, s, mem, main_goal)
        return None

    def chat(self, policy, snapshot, mem):
        """The press that talks to a person or reads a sign one step from the path, or None to walk on."""
        pos = (snapshot.map, snapshot.x, snapshot.y)
        if self.social_target:
            origin, facing, key, label = self.social_target
            self.social_target = None
            if origin == pos and mem[W_FACING] == FACING[facing]:
                self.pending_social = (key, snapshot.frame)
                self.next_conversation = CHAT_REST.until(policy.clock)
                policy.mode = label
                policy.reason = "Take a moment to learn about the area before continuing"
                return tap("a")
        if policy.clock < self.next_conversation or policy.rng.random() > 0.15:
            return None
        world = WORLD.get(snapshot.map, {})
        positions = policy.nav.live_positions if policy.nav.live_map == snapshot.map else []
        candidates = [(*(positions[i] if i < len(positions) else o[:2]), o[4], "talking to locals")
                      for i, o in enumerate(world.get("objects", []))
                      if o[2] not in ("SPRITE_NURSE", "SPRITE_CLERK", "SPRITE_BOULDER", "SPRITE_SNORLAX")
                      and (snapshot.map, o[0], o[1]) not in policy.nav.cleared_objects]
        candidates += [(x, y, name, "reading a sign") for x, y, name in world.get("backgrounds", [])
                       if "SIGN" in name or "TRAINER_TIPS" in name]
        policy.rng.shuffle(candidates)
        for x, y, name, label in candidates:
            key = f"{snapshot.map}:{name}"
            if key in policy.interactions:
                continue
            direction = next((d for d, (dx, dy) in DIRS.items()
                              if (snapshot.x + dx, snapshot.y + dy) == (x, y)), None)
            if direction:
                self.social_target = (pos, direction, key, label)
                policy.mode = label
                policy.reason = "Notice someone or something along the way"
                if mem[W_FACING] == FACING[direction]:
                    return self.chat(policy, snapshot, mem)
                return tap(direction, 4, 12)
        return None
