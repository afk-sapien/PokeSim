"""Story prerequisites and concrete short-term destinations."""
from dataclasses import asdict, dataclass, replace
from functools import lru_cache

from .battle import replacement_slot
from ..battle_power import battler, moveset_score
from ..ram import PartyMon
from ..planning.stance import HUNT, STORY, TRAIN
from .team import readiness

from .. import story
from ..game_data import current_variant
from ..planning import league
from ..planning.losses import ace_slot
from ..planning.readiness import LOSS, PARTNER, band
from ..strategy_data import ITEMS, MAPS, MOVES, SPECIES, WORLD, event_set, object_hidden


def power(move):
    return MOVES.get(move, {}).get('power')


@dataclass(frozen=True)
class Goal:
    key: str
    title: str
    reason: str
    targets: tuple[tuple[int, int, int], ...] = ()
    facing: str | None = None
    interact: bool = False
    help: str = ""
    approaches: tuple[tuple[int, int, int, str], ...] = ()
    # The goal kind the battle stance follows (planning/stance.py): story, travel, train or hunt.
    kind: str = STORY

    def facing_at(self, pos):
        return next((direction for m, x, y, direction in self.approaches if (m, x, y) == pos), self.facing)

    def to_dict(self):
        return {"id": self.key, "title": self.title, "reason": self.reason,
                "targets": self.targets[:8], "target_count": len(self.targets), "facing": self.facing}


def at(key, title, reason, map_name, x, y, facing=None):
    return Goal(key, title, reason, ((MAPS[map_name], x, y),), facing, facing is not None)


def object_goal(key, title, reason, map_name, text_fragment):
    m = MAPS[map_name]
    world = WORLD.get(m)
    if world:
        obj = next((o for o in world["objects"] if text_fragment in o[4]), None)
        if obj:
            x, y = obj[:2]
            # A tile under another standing object cannot be reached. The Fighting Dojo's two balls sit
            # side by side, so walking toward the far side of one ended below the other, and the A press
            # there took the gift that was not wanted.
            occupied = {(o[0], o[1]) for o in world["objects"] if o is not obj and o[3] == "STAY"}
            approaches, blocked = [], []
            for dx, dy, facing in ((0, 1, "up"), (1, 0, "left"), (0, -1, "down"), (-1, 0, "right")):
                tx, ty = x + dx, y + dy
                if 0 <= ty < world["height"] and 0 <= tx < world["width"] and world["tiles"][ty][tx] in world["passable"]:
                    (blocked if (tx, ty) in occupied else approaches).append((m, tx, ty, facing))
            # A standing object can be hidden, so its tile is a last resort rather than never used.
            approaches = approaches or blocked
            if approaches:
                return Goal(key, title, reason, tuple(p[:3] for p in approaches), approaches[0][3], True,
                            approaches=tuple(approaches))
        targets = tuple((m, x, y) for x, y, *_ in world["warps"])
        return Goal(key, title, reason, targets)
    return Goal(key, title, reason)


def milestones(snapshot):
    flags = snapshot.event_flags
    out = {"starter": bool(snapshot.party), "parcel": event_set(flags, "EVENT_GOT_OAKS_PARCEL"),
           "pokedex": event_set(flags, "EVENT_GOT_POKEDEX")}
    for i, name in enumerate(("boulder", "cascade", "thunder", "rainbow", "soul", "marsh", "volcano", "earth")):
        out[name] = bool(snapshot.badges & (1 << i))
    out["champion"] = (snapshot.hall_of_fame_count > 0 or snapshot.map == MAPS["HALL_OF_FAME"]
                       or event_set(flags, "EVENT_BEAT_CHAMPION_RIVAL"))
    return out


STARTERS = ("bulbasaur", "charmander", "squirtle")
# Yellow hands every player Pikachu. The adventure never chooses a starter there.
YELLOW = current_variant() == "yellow"
GAME_STARTERS = ("pikachu",) if YELLOW else STARTERS
# The story rows of pokesim/story/gen1.json. Red and Blue share theirs.
GAME = "yellow" if YELLOW else "red"


def step(key, title, reason, help="", row=None, **choices):
    """The goal for story step ``key`` at the place gen1.json gives it, or at ``row`` of that key."""
    row = row or story.row(1, GAME, key)
    if "object" in row:
        goal = object_goal(key, title, reason, row["map"], story.fill(row["object"], **choices))
    else:
        goal = at(key, title, reason, row["map"], row["x"], row["y"], row.get("face"))
    return replace(goal, help=help) if help else goal


def open_row(s, key):
    """The first place row of ``key`` whose done_when flags are not all set, or None once all are."""
    return next((row for row in story.rows(1, GAME, key) if "map" in row
                 and not all(event_set(s.event_flags, flag) for flag in row["done_when"].get("flags", ()))), None)


def story_goal(snapshot, starter="bulbasaur", fossil="HELIX_FOSSIL", room=True):
    """The next story step. ``room`` off leaves out the PC visit that makes bag room (bicycle_goal)."""
    flags = snapshot.event_flags
    has = lambda name: any(item == ITEMS[name] and qty for item, qty in snapshot.items)
    if not event_set(flags, "EVENT_FOLLOWED_OAK_INTO_LAB") and not snapshot.party:
        # Yellow's Oak stops the player one row further north, at the edge of the grass.
        return step("meet_oak", "Meet Professor Oak", "A starter is needed before leaving town")
    if not snapshot.party and YELLOW:
        # The rival snatches the only Poké Ball on the table and Oak hands over Pikachu instead.
        return step("starter", "Receive Pikachu", "Oak has one Pokémon left for this adventure")
    if not snapshot.party:
        return step("starter", "Choose " + starter.title(), "Meet this adventure's first partner", starter=starter.upper())
    if not event_set(flags, "EVENT_GOT_POKEDEX"):
        if has("OAKS_PARCEL") or event_set(flags, "EVENT_GOT_OAKS_PARCEL"):
            return step("pokedex", "Deliver Oak’s parcel", "Obtain the Pokédex and open the northward route")
        return step("parcel", "Collect Oak’s parcel", "The Viridian clerk has a delivery for Oak")
    if not snapshot.badges & 1:
        return step("boulder", "Challenge Brock", "Earn the Boulder Badge to continue east")
    return campaign_goal(snapshot, fossil, room)


GYMS = (
    (1, "boulder", "Brock", "PEWTER_GYM", "BROCK", 13, ("ROUTE_2", "VIRIDIAN_FOREST")),
    (2, "cascade", "Misty", "CERULEAN_GYM", "MISTY", 18, "ROUTE_24"),
    (4, "thunder", "Lt. Surge", "VERMILION_GYM", "LT_SURGE", 22, "ROUTE_11"),
    (8, "rainbow", "Erika", "CELADON_GYM", "ERIKA", 28, "ROUTE_7"),
    (16, "soul", "Koga", "FUCHSIA_GYM", "KOGA", 37, "ROUTE_15"),
    (32, "marsh", "Sabrina", "SAFFRON_GYM", "SABRINA", 40, "ROUTE_15"),
    (64, "volcano", "Blaine", "CINNABAR_GYM", "BLAINE", 44, "POKEMON_MANSION_1F"),
    (128, "earth", "Giovanni", "VIRIDIAN_GYM", "GIOVANNI", 47, "ROUTE_21"),
)
if YELLOW:
    # Yellow's later leaders are several levels stronger than in Red and Blue.
    GYMS = tuple(g[:5] + ({4: 26, 8: 31, 16: 44, 32: 47, 64: 51, 128: 52}.get(g[0], g[5]),) + g[6:] for g in GYMS)
GYM_HELP = {
    "cascade": "Clear the gym trainers and approach Misty. Grass or Electric attacks help against her Water team.",
    "thunder": "Use Cut from a party Pokémon outside the gym. Inside, find the first trash-can switch, then an adjacent second switch. Hand back to the AI after opening the electric barriers.",
    "rainbow": "Use Cut to enter the Celadon gym and clear the central tree. Fire and Flying attacks help against Erika.",
    "soul": "Follow the outer edge of Koga’s gym around the invisible walls, then approach him from the south.",
    "marsh": "Use the Saffron gym teleport pads to reach Sabrina. Hand control back when you reach her room.",
    "volcano": "Surf south from Pallet to Cinnabar. Use the Secret Key to enter the gym, then beat each quiz trainer or answer their question to open the doors.",
    "earth": "Use the Viridian gym’s arrow tiles to reach Giovanni. Water and Grass attacks help against his Ground team.",
}


GRASS_TILES = {'OVERWORLD': 0x52, 'FOREST': 0x20, 'PLATEAU': 0x45}


def training_goal(key, title, reason, map_name):
    """Training on the grass of ``map_name``, one map name or a tuple of them."""
    targets = []
    for name in (map_name,) if isinstance(map_name, str) else map_name:
        m = MAPS[name]
        w = WORLD[m]
        # Outdoor grass and indoor encounter floors are navigated using the same graph. Each tileset
        # draws grass with its own tile: Route 23 had no targets at all under the overworld's, and a run
        # told to prepare for the League there drifted along Route 21 for seventeen hours of game time.
        grass = GRASS_TILES.get(w["tileset"])
        targets.extend((m, x, y) for y, row in enumerate(w["tiles"]) for x, tile in enumerate(row)
                       if tile == grass or (name == "POKEMON_MANSION_1F" and tile in w["passable"]))
    return Goal("train_" + key, title, reason, tuple(targets), kind=TRAIN)


LEAGUE_TRAINERS = (("league_lorelei", "Lorelei"), ("league_bruno", "Bruno"), ("league_agatha", "Agatha"),
                   ("league_lance", "Lance"), ("league_rival", "the Champion"))
LEAGUE_ROOMS = frozenset(MAPS[story.row(1, GAME, key)["map"]] for key, _ in LEAGUE_TRAINERS)
# Red, Blue and Yellow's bosses for planning/league.py: the gyms in badge order, then the League. The
# matchup scorer (team.readiness) reads a gym by its badge bit and each League room by a bit from 256.
# The League rooms share one loss bar, measured against the Champion's ace, and train on Route 23. The
# boss check guards a boss goal whose title starts with "Challenge", and 'league_entrance' leads into
# the League's rooms. Before the League a sturdy partner, chosen by its base HP, trains beside the
# strongest (league.partner).
BOSS_TABLE = league.Table(
    generation=1,
    rows=(*(league.Row(key, name, ace, route, frozenset({MAPS[room]}), bit, scores=(bit,))
            for bit, key, name, room, _, ace, route in GYMS),
          league.Row(league.LEAGUE, "the Pokémon League", 65, "ROUTE_23", LEAGUE_ROOMS, 0, scores=tuple(range(256, 261)))),
    goals=frozenset((*(gym[1] for gym in GYMS), 'league_lorelei', 'league_bruno', 'league_agatha', 'league_lance',
                     'league_rival', 'league_entrance')),
    league=LEAGUE_ROOMS, challenge='Challenge',
    partner=lambda species: SPECIES.get(species, {}).get("stats", [0])[0])


def gain_band(snapshot, key, species, losses=None):
    """The levels a gain by ``species``, a Pokédex number, counts toward as progress while the goal
    ``key`` runs (readiness.band), or None.

    Before the Champion it is the next boss's band. After it no boss is left, so the band comes from
    the goal: a League rematch counts gains toward the League's target, raised once after a loss
    there, and a goal that evolves a Pokémon counts that Pokémon's gains toward the evolution."""
    parts = (key or '').split(':')
    method = parts[1] if len(parts) > 1 else ''
    if method == 'evolve':
        level = evolve_level(parts[0], species)
        if level is not None:
            return 0, level
    if method == 'rematch':
        return band(league.row_target(BOSS_TABLE.league_row, losses=losses), league.top_level(snapshot))
    return league.gain_band(BOSS_TABLE, snapshot, losses=losses)


def evolve_level(target, species):
    """The level a Pokémon of Pokédex number ``species`` trains to while a goal evolves it into
    ``target``, the internal species id an evolve goal's key starts with, or None when it does not
    evolve into ``target``. A level evolution trains to its level. A stone evolution may wait for a
    move first (move_development.evolution_wait), so it trains up to the last level its learnset teaches."""
    from .collection import EVOS
    for sid, rows in EVOS.items():
        if SPECIES.get(sid, {}).get('dex') != species:
            continue
        for row in rows:
            if str(row['species']) != target:
                continue
            if row['method'] == 'level':
                return int(row['requirement'])
            if row['method'] == 'item':
                return max((level for level, _ in SPECIES[sid].get('learnset', ())), default=None)
    return None


def story_loss(s, key, losses):
    """The goal key whose loss bar the story goal ``key`` trains to: its own, or else that of the first story
    step not yet done that a loss was noted on.

    The way back to a boss is made of story steps of its own. A Red run that lost to Giovanni rode the
    Rocket Hideout lift down to him, the step for the ride had no loss, and on B4F the loss turned the run
    back into the lift for training. The two took turns for 51,206 frames of a gate rung."""
    levels = losses.levels()
    if key is None or not levels or key in levels or key in BOSS_TABLE.goals:
        return key
    return next((row['key'] for row in story.steps(1, GAME) if row['key'] in levels
                 and row['key'] not in BOSS_TABLE.goals and open_row(s, row['key'])), key)


def boss_training(s, goal, losses):
    """Training before the boss or story goal ``goal`` (planning/league.training), or None once the team is ready.

    A story goal trains to the loss of the story step it leads up to (story_loss). It also trains on the
    ground of the last boss won, and the walk takes the nearer ground it reaches. The next boss's ground can
    lie past the story goal: Koga's Route 15 is behind the Snorlax the Poké Flute wakes, which needs the
    Silph Scope from Giovanni. A Red run that lost to him in the Rocket Hideout found no route to Route 15
    and stood down until the stall watch fired."""
    key = story_loss(s, getattr(goal, 'key', None), losses)
    plan = league.training(BOSS_TABLE, s, key, s.map, power, losses, lambda bit: readiness(s, bit)['score'])
    if plan is None:
        return None
    row, level = plan.row, plan.verdict.target
    if row is None:
        last = next((r for r in reversed(BOSS_TABLE.rows) if league.won(r, s)), None)
        grounds = (plan.where, *((last.training,) if last else ()))
        names = dict.fromkeys(name for where in grounds for name in ((where,) if isinstance(where, str) else where))
        return training_goal(key, "Train before another try",
                             f"Train the best fighter to level {level} after a loss on the way to: {goal.title}", tuple(names))
    if plan.verdict.reason == LOSS:
        return training_goal(row.key, f"Prepare for {row.name}",
                             f"Train the best fighter to level {level} after a loss to {row.name}", plan.where)
    if plan.verdict.reason == PARTNER:
        return training_goal('league_partner', 'Prepare a second League battler',
                             'Build coverage for the League matchups that remain difficult', 'POKEMON_MANSION_1F')
    if row.league:
        return training_goal(row.key, 'Prepare for the Pokémon League',
                             'Improve damage and survival across the final matchups', plan.where)
    return training_goal(row.key, f"Prepare for {row.name}",
                         f"Build usable damage and survival against {row.name}, then reassess the team", plan.where)


def gym_goal(s, bit):
    _, key, trainer, gym, obj, *_ = next(g for g in GYMS if g[0] == bit)
    # Each locked door opens after beating the quiz trainer whose text follows the one before, and
    # gen1.json names the trainer for each door, so the first locked door names the trainer to face.
    door = open_row(s, key) if key == "volcano" else None
    if door is not None:
        return step(key, "Open Blaine's gym doors", "Beat the quiz trainer guarding the next locked door", GYM_HELP[key], row=door)
    return replace(object_goal(key, f"Challenge {trainer}", f"Use the team's best available matchup against {trainer}", gym, obj),
                   help=GYM_HELP.get(key, "Approach the gym leader and start the battle."))


def pc_visit(key, title, reason):
    """Goal ``key`` at the PC of any Pokémon Center."""
    pc = story.place(1, GAME, "party_pc")
    targets = tuple((m, pc["x"], pc["y"]) for m, w in WORLD.items() if pc["named"] in w["name"] and w["width"] == pc["width"])
    return Goal(key, title, reason, targets, pc["face"], True)


def partner_withdraw(name):
    """The PC visit that brings a stored partner for field move ``name`` onto the team."""
    return pc_visit("party_" + name, "Bring a field-move partner onto the team",
                    "Use Bill’s PC to store a reserve and withdraw a compatible partner")


def teaching_goal(key, title, reason, s):
    move = {"teach_cut": 15, "teach_surf": 57, "teach_strength": 70}[key]
    if not any(move in SPECIES.get(p.species, {}).get("hms", [])
               and (0 in p.moves or replacement_slot(p, move) is not None) for p in s.party):
        # Every box counts: the PC can change boxes, and the gift Lapras is rarely in the open one.
        held = [species for _, species, _, _ in s.stored_pokemon] or [species for species, _ in s.boxed_pokemon]
        if any(move in SPECIES.get(species, {}).get("hms", []) for species in held):
            return partner_withdraw(key.removeprefix("teach_"))
        lapras = next((sid for sid, d in SPECIES.items() if d.get('name') == 'LAPRAS'), 0)
        # The worker gives one Lapras. A registered Lapras that is no longer held was traded or released.
        if (move in SPECIES.get(lapras, {}).get('hms', []) and SPECIES.get(lapras, {}).get('dex') not in s.owned
                and event_set(s.event_flags, 'EVENT_BEAT_SILPH_CO_GIOVANNI')):
            worker = story.place(1, GAME, "lapras")
            return object_goal("lapras", "Meet the rescued Silph worker", "Accept an accessible Lapras for the missing field move",
                               worker["map"], worker["object"])
        name = key.removeprefix('teach_')
        # A carrier hunt, as in Gold, Silver and Crystal: it catches a partner for the move and runs
        # from every other wild battle (planner design S5).
        return Goal('catch_' + name, f'Find a {name.title()} partner',
                    f'Search reachable habitats for a Pokémon that can learn {name.title()}',
                    partner_habitats(move, max((p.level for p in s.party), default=5)), kind=HUNT)
    return Goal(key, title, reason, ((s.map, s.x, s.y),), help=reason)


@lru_cache(maxsize=300)
def partner_habitats(move, level):
    targets = []
    for m, w in WORLD.items():
        if w['name'].startswith(('Safari', 'CeruleanCave')):
            continue
        if not any(move in SPECIES.get(sid, {}).get('hms', []) and wild_level <= level + 5
                   for sid, wild_level in w.get('encounters', [])):
            continue
        for y, row in enumerate(w['tiles']):
            for x, tile in enumerate(row):
                if tile == 0x52 or (w['tileset'] == 'FOREST' and tile == 0x20) or (w['tileset'] in ('CAVERN', 'MANSION') and tile in w['passable']):
                    targets.append((m, x, y))
    return tuple(targets)


FLASH = 148
# Oak's aide in the Route 2 gate gives HM05 to a player who owns this many species (hOaksAideRequirement).
AIDE_REQUIREMENT = 10
# The road into Rock Tunnel from the north. A run standing here never walks back for the HM.
ROCK_TUNNEL_ROAD = frozenset(MAPS[name] for name in ('ROUTE_10', 'ROCK_TUNNEL_POKECENTER', 'ROCK_TUNNEL_1F', 'ROCK_TUNNEL_B1F'))
# The bag's distinct entries.
BAG_SLOTS = 20
LAPRAS_DEX = 131
# The key items whose use is over once these facts hold: event flags set, and Pokédex numbers owned.
# Nothing else in the game reads them after that. Every other key item keeps a use: an HM teaches
# again, the Bicycle, the rods, the Coin Case, the Itemfinder and the Exp. All have no last use, the
# Silph Scope still unmasks the Pokémon Tower ghosts for a catch, the lab revives a fossil at any time,
# and the Poké Flute wakes the Route 12 Snorlax each walking return puts back (step_events).
SPENT_KEY_ITEMS = {
    # Once the S.S. Anne has sailed, the sailor at the dock turns everyone back, ticket or not.
    'S_S_TICKET': (('EVENT_SS_ANNE_LEFT',), ()),
    # Only the hideout's lift reads it, and the boss it leads to does not return.
    'LIFT_KEY': (('EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI',), ()),
    # Silph Co.'s doors stay open once opened. The rescued worker's Lapras gift waits behind one of them.
    'CARD_KEY': (('EVENT_BEAT_SILPH_CO_GIOVANNI',), (LAPRAS_DEX,)),
    # Only the Cinnabar Gym's door reads it.
    'SECRET_KEY': (('EVENT_BEAT_BLAINE',), ()),
}


def spent_items(s):
    """The bag's key items whose use is over (SPENT_KEY_ITEMS), in that table's order."""
    bag = {item for item, qty in s.items if qty}
    return tuple(ITEMS[name] for name, (flags, owned) in SPENT_KEY_ITEMS.items() if ITEMS[name] in bag
                 and all(event_set(s.event_flags, flag) for flag in flags) and all(dex in s.owned for dex in owned))


def bag_room(s, needed):
    """The PC visit that stores spent key items until the bag has ``needed`` free entries, or None when
    storing every one of them would still leave too few and the item waits. Nothing is tossed, and the
    item PC gives each one back."""
    if len(s.items) + needed - BAG_SLOTS > len(spent_items(s)):
        return None
    return pc_visit('bag_room', 'Make room in the bag', 'Store key items whose use is over in the PC to make room')


def flash_learner(party):
    """The party slot to teach Flash, or None when only the ace can learn it.

    An HM move cannot be forgotten in Gen I, so Flash on the ace would hold one of its four battle
    slots for the rest of the game. Of the others, the highest level learns it.
    """
    ace = ace_slot(party, power)
    return max((i for i, mon in enumerate(party) if i != ace and FLASH in SPECIES.get(mon.species, {}).get('hms', [])
                and (0 in mon.moves or replacement_slot(mon, FLASH) is not None)),
               key=lambda i: party[i].level, default=None)


def past_rock_tunnel(s):
    """True once the run has entered Lavender or stands on the road into Rock Tunnel."""
    return bool(s.towns_visited >> MAPS['LAVENDER_TOWN'] & 1) or s.map in ROCK_TUNNEL_ROAD


def flash_goal(s):
    """HM05 from Oak's aide and its teaching, on the way to Rock Tunnel, or None to walk the cave dark.

    Rock Tunnel is Kanto's only dark cave, and before the Rainbow Badge it is the only road to Lavender.
    So a run that has entered Lavender never walks back for the HM, and neither does one already on the
    road into the tunnel. Below the aide's ten species, or with no partner but the ace able to learn
    Flash, the run walks the cave dark as before rather than make the trip for nothing.
    """
    if (past_rock_tunnel(s) or any(FLASH in mon.moves for mon in s.party) or flash_learner(s.party) is None):
        return None
    if not any(item == ITEMS['HM05'] and qty for item, qty in s.items):
        if event_set(s.event_flags, 'EVENT_GOT_HM05') or len(s.owned) < AIDE_REQUIREMENT:
            return None
        return step('flash', 'Visit Oak’s aide on Route 2', 'Show ten owned species to receive Flash for the dark Rock Tunnel',
                    'Take Diglett’s Cave from Route 11 to Route 2 and talk to the aide in the gate. Answer yes.')
    reason = 'Teach HM05 to a partner, never the best fighter, to light Rock Tunnel'
    return Goal('teach_flash', 'Teach Flash to a partner', reason, ((s.map, s.x, s.y),), help=reason)


FLY = 19


@lru_cache(maxsize=1024)
def fly_free(mon):
    """True when ``mon``, a party member or a stored record, learns Fly at no cost to its battle moves.

    That is into an empty slot, or over the move the teach replaces (battle.replacement_slot) when the
    moveset scores no lower with Fly in its place (battle_power.moveset_score). Gen I Fly is a 70 power
    move that spends two turns, so it seldom scores higher than what it replaces. Agility, Leer or
    Whirlwind score nothing, and Fly over one of them costs nothing. A stored record's stats come from
    its DVs and stat experience, as the PC computes them on the way out.
    """
    if FLY not in SPECIES.get(mon.species, {}).get('hms', []):
        return False
    fighter = mon if isinstance(mon, PartyMon) else battler(asdict(mon))
    if fighter is None or FLY in fighter.moves:
        return False
    if 0 in fighter.moves:
        return True
    slot = replacement_slot(fighter, FLY)
    return slot is not None and (moveset_score(fighter, fighter.moves[:slot] + (FLY,) + fighter.moves[slot + 1:])
                                 >= moveset_score(fighter))


def fly_learner(party):
    """The party slot to teach Fly, or None.

    An HM move cannot be forgotten in Gen I, so Fly holds a battle slot for the rest of the game. It
    goes only to a member it costs no battle move (fly_free), and never to the ace. Of those the
    lowest level learns it, the member the League leans on least.
    """
    ace = ace_slot(party, power)
    return min((i for i, mon in enumerate(party) if i != ace and fly_free(mon)),
               key=lambda i: (party[i].level, i), default=None)


def fly_goal(s, room=True):
    """HM02 from the girl in the Route 16 house and its teaching, for a run past the League, or None.

    The learner is fly_learner's. With none in the party, the strongest stored Pokémon that Fly costs
    no battle move is withdrawn (storage.field_partners) and takes the slot of the reserve the PC
    deposits. With neither, the run goes without Fly rather than spend a League battler's move on it.
    A full bag makes an entry for HM02 first (bag_room), and ``room`` is as in bicycle_goal.
    """
    if any(FLY in mon.moves for mon in s.party):
        return None
    held = any(item == ITEMS['HM02'] and qty for item, qty in s.items)
    if not held and event_set(s.event_flags, 'EVENT_GOT_HM02'):
        return None
    learner = fly_learner(s.party)
    if learner is None and not any(fly_free(mon) for mon in s.stored_details):
        return None
    if not held and len(s.items) >= BAG_SLOTS:
        return bag_room(s, 1) if room else None
    if not held:
        return step('fly', 'Visit the house on Route 16', 'The girl there gives HM02 so the team can fly to any visited town',
                    'Take Route 16 west from Celadon by the north path, through the gate, to the house beyond it.',
                    row=story.place(1, GAME, 'fly'))
    if learner is None:
        return partner_withdraw('fly')
    reason = 'Teach HM02 to a partner, never the best fighter, to fly to any visited town'
    return Goal('teach_fly', 'Teach Fly to a partner', reason, ((s.map, s.x, s.y),), help=reason)


def bicycle_goal(s, room=True):
    """The Bike Voucher from the Fan Club chairman, then the Bicycle for it in Cerulean, or None once owned.

    A stored voucher is the only way to lose it, and the bike shop wants it in the bag, so a run with the
    voucher flag but no voucher goes without the Bicycle rather than wait for one that never comes back.
    Both gifts are refused into a full bag, and the shop hands over the Bicycle before it takes the voucher,
    so the voucher wants two free entries and the Bicycle one. A fuller bag stores spent key items to make
    them (bag_room) unless ``room`` is off, as after a stall set that visit aside. Without the room the run
    goes on foot.
    """
    has = lambda name: any(item == ITEMS[name] and qty for item, qty in s.items)
    if has('BICYCLE') or event_set(s.event_flags, 'EVENT_GOT_BICYCLE'):
        return None
    free = BAG_SLOTS - len(s.items)
    if has('BIKE_VOUCHER'):
        if free < 1:
            return bag_room(s, 1) if room else None
        return step('bicycle', 'Collect the Bicycle', 'Trade the Bike Voucher at the Cerulean bike shop',
                    'Talk to the clerk at the Cerulean bike shop with the voucher in the bag.')
    if event_set(s.event_flags, 'EVENT_GOT_BIKE_VOUCHER'):
        return None
    if free < 2:
        return bag_room(s, 2) if room else None
    return step('bike_voucher', 'Hear out the Fan Club chairman', 'He gives a Bike Voucher to anyone who listens',
                'Talk to the chairman at the back of the Vermilion Fan Club and answer yes.')


def campaign_goal(s, fossil="HELIX_FOSSIL", room=True):
    done = lambda name: event_set(s.event_flags, name)
    has = lambda name: any(item == ITEMS[name] and qty for item, qty in s.items)
    knows = lambda move: any(move in p.moves for p in s.party)
    if not s.badges & 2:
        # Everywhere that can be reached before Mt. Moon is cleared. A side project that led back to
        # Viridian Forest used to swap this goal for training on Route 24, which lies beyond the
        # mountain, and the run wandered between Route 1 and Route 22 for hours of game time.
        west = {m for name, m in MAPS.items() if name in ("ROUTE_1", "ROUTE_2", "ROUTE_3") or name.startswith(
            ("PALLET", "REDS_HOUSE", "BLUES_HOUSE", "OAKS_LAB", "VIRIDIAN_", "PEWTER_", "MUSEUM", "MT_MOON", "ROUTE_2_", "ROUTE_22"))}
        if (s.map in west or (s.map == MAPS["ROUTE_4"] and s.x < 21)) and not (done("EVENT_GOT_DOME_FOSSIL") or done("EVENT_GOT_HELIX_FOSSIL")):
            if not done("EVENT_BEAT_MT_MOON_EXIT_SUPER_NERD"):
                return step("moon_trainer", "Find a way through Mt. Moon", "Defeat the Super Nerd guarding the fossils")
            return step("fossil", "Choose " + fossil.replace('_', ' ').title(), "Collect a fossil to clear the exit toward Cerulean", fossil=fossil)
        return gym_goal(s, 2)
    if not s.badges & 4:
        if not (has("S_S_TICKET") or done("EVENT_GOT_SS_TICKET") or has("HM01") or knows(15)):
            if done("EVENT_USED_CELL_SEPARATOR_ON_BILL"):
                return step("ticket", "Collect Bill’s ticket", "Speak to the restored Bill for passage on the S.S. Anne")
            if done("EVENT_BILL_SAID_USE_CELL_SEPARATOR"):
                return step("bill_pc", "Help Bill out of the machine", "Activate the PC on the left side of Bill’s house")
            return step("bill", "Help Bill", "Cross Nugget Bridge and follow Route 25 to Bill’s house")
        if not done("EVENT_BEAT_CERULEAN_ROCKET_THIEF"):
            return step("rocket_thief", "Open the road south", "Go through the robbed house and defeat the Rocket behind it", "Leave the robbed house through its rear exit and battle the Rocket. Continue south through the underground path toward Vermilion.")
        if not (has("HM01") or knows(15)):
            return step("cut", "Visit the ship’s captain", "Board the S.S. Anne and help its captain to receive Cut")
        if not knows(15):
            return teaching_goal("teach_cut", "Teach Cut to a partner", "Teach HM01 to a compatible partner to open routes blocked by trees.", s)
        return gym_goal(s, 4)
    if not s.badges & 8:
        # Vermilion's Fan Club and Cerulean's bike shop both lie on the road from Route 2 to Rock Tunnel.
        # A run already past the tunnel gets the Bicycle after the League instead of walking back.
        errand = flash_goal(s) or (None if past_rock_tunnel(s) else bicycle_goal(s, room))
        if errand is not None:
            return errand
        return replace(gym_goal(s, 8), help="Reach Lavender through Rock Tunnel, then go west through the Route 8 underground path to Celadon. Use Cut at Erika’s gym. " + GYM_HELP["rainbow"])
    if not s.badges & 16:
        if not (has("POKE_FLUTE") or done("EVENT_GOT_POKE_FLUTE")):
            if not has("SILPH_SCOPE") and not done("EVENT_RESCUED_MR_FUJI"):
                if not done("EVENT_FOUND_ROCKET_HIDEOUT"):
                    # The poster's guard leaves the Game Corner once beaten, which hides his object.
                    guard = story.row(1, GAME, "poster_guard")["done_when"]["hidden"]
                    if not all(object_hidden(s, MAPS[name], index) for name, index in guard):
                        return step("poster_guard", "Investigate the guarded poster", "Talk to the Rocket guarding the Game Corner poster")
                    return step("hideout", "Investigate the Game Corner", "Defeat the Rocket and inspect the poster behind him", "Battle the Rocket in front of the poster, then inspect the poster to reveal the stairs.")
                if not has("LIFT_KEY") and not done("EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"):
                    if not done("EVENT_ROCKET_DROPPED_LIFT_KEY"):
                        return step("lift_rocket", "Find the Lift Key", "Defeat the B4F Rocket and speak to him again so he drops the key", "Navigate the hideout’s spin tiles to B4F. Defeat the Rocket in the northwest room and speak to him again.")
                    return step("lift_key", "Pick up the Lift Key", "Collect the key dropped by the Rocket")
                if not done("EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"):
                    if s.map != MAPS["ROCKET_HIDEOUT_B4F"] or s.x < 22:
                        return step("hideout_elevator", "Take the lift to Giovanni’s floor", "Use the Lift Key and choose B4F")
                    # Yellow's Jessie and James step out to guard the door when the player reaches their row.
                    guard = open_row(s, "boss_guard")
                    if guard is not None:
                        return step("boss_guard", "Open Giovanni’s door", "Defeat Jessie and James in front of the door"
                                    if YELLOW else "Defeat both Rockets guarding the door", row=guard)
                    return step("rocket_boss", "Confront Giovanni", "Take the hideout elevator to B4F and defeat Giovanni", "Use the Lift Key and elevator to reach B4F. Defeat both door guards, then approach Giovanni.")
                if s.map != MAPS['ROCKET_HIDEOUT_B4F'] or s.x < 22:
                    return step('hideout_elevator', 'Return for the Silph Scope', 'Take the lift to B4F before collecting the Scope')
                return step("scope", "Collect the Silph Scope", "Pick up the Silph Scope left behind Giovanni")
            if not done("EVENT_RESCUED_MR_FUJI"):
                return step("fuji", "Rescue Mr. Fuji", "Climb Pokémon Tower, resolve the Marowak encounter, and clear the Rockets")
            return step("flute", "Collect the Poké Flute", "Speak to Mr. Fuji in his Lavender house")
        if not done("EVENT_BEAT_ROUTE12_SNORLAX") and s.map != MAPS["FUCHSIA_CITY"]:
            return step("snorlax", "Wake the sleeping roadblock", "Reach Snorlax on Route 12 and play the Poké Flute", "Stand next to Snorlax, use the Poké Flute from the bag, then let the AI handle the battle.")
        return gym_goal(s, 16)
    if not s.badges & 32:
        if not s.saffron_open:
            if not any(has(n) for n in ("FRESH_WATER", "SODA_POP", "LEMONADE")):
                return step("guard_drink", "Bring a drink for the Saffron guards", "Buy Fresh Water from a vending machine on the Celadon department store roof", "Use the rooftop vending machine and buy Fresh Water. Keep it in the bag for the Saffron guard.")
            return step("saffron_gate", "Open the way into Saffron", "Offer the guard a drink by walking through the gate")
        if not done("EVENT_BEAT_SILPH_CO_GIOVANNI"):
            if not has("CARD_KEY"):
                return step("card_key", "Find Silph’s Card Key", "Collect the key in the south corridor on the fifth floor", "Reach the fifth floor’s south corridor. Step onto the nearby warp pad and back to get around the blocking Rocket, then collect the Card Key.")
            return step("silph", "Free Silph Co.", "Use the Card Key and warp pads to reach Giovanni on the eleventh floor", "Open the third-floor central door, take its warp to the rival on 7F, then the next pad to 11F. Open the president’s door and defeat Giovanni.")
        return gym_goal(s, 32)
    if not (s.badges & 64 and s.badges & 128):
        if not (has("HM03") or knows(57)):
            return step("surf", "Find the Safari Zone’s secret house", "Reach the secret house in the west area to receive Surf", "Enter the Safari Zone with room in the bag. Travel east, north, then west to the secret house before the step limit expires.")
        if not knows(57):
            return teaching_goal("teach_surf", "Teach Surf to a partner", "Teach HM03 to a compatible partner so the team can cross water.", s)
        if not (has("HM04") or knows(70)):
            if not has("GOLD_TEETH"):
                return step("teeth", "Find the warden’s Gold Teeth", "Pick up the Gold Teeth near the Safari Zone’s secret house")
            return step("strength", "Return the warden’s teeth", "Bring the Gold Teeth to the warden in Fuchsia to receive Strength")
        if not knows(70):
            return teaching_goal("teach_strength", "Teach Strength to a partner", "Teach HM04 to a compatible partner for the boulders on Victory Road.", s)
    if not s.badges & 64:
        if not has("SECRET_KEY"):
            return step("secret_key", "Unlock the Cinnabar gym", "Surf south from Pallet and explore the Pokémon Mansion for the Secret Key", "Surf from Pallet to Cinnabar. In the mansion, use the statue switches and the third-floor drop to reach the basement and collect the Secret Key.")
        return gym_goal(s, 64)
    if not s.badges & 128:
        return gym_goal(s, 128)
    if done("EVENT_BEAT_CHAMPION_RIVAL") or s.map == MAPS["HALL_OF_FAME"]:
        return Goal("champion", "Kanto Champion", "The team made it to the Hall of Fame", help="You won. Take a moment with the team.")
    if s.map not in LEAGUE_ROOMS:
        if s.map != MAPS[story.row(1, GAME, 'league_entrance')['map']]:
            return step('league_entrance', 'Return to the Pokémon League',
                        'Begin a new challenge through the lobby, where the game resets the previous attempt')
        return step('league_lorelei', 'Challenge Lorelei', 'Start the next League attempt with Lorelei')
    rooms = [(key, title, story.row(1, GAME, key)) for key, title in LEAGUE_TRAINERS]
    current = next(i for i, (*_, row) in enumerate(rooms) if MAPS[row["map"]] == s.map)
    for i, (key, title, row) in enumerate(rooms):
        if i < current:
            continue
        if i > current or not all(done(flag) for flag in row["done_when"]["flags"]):
            return step(key, f"Challenge {title}", "Advance through the League one battle at a time",
                        "Use Surf through Route 23 and Strength on Victory Road’s boulder switches. Heal and stock up at Indigo Plateau before entering. Inside the League, continue north after each battle.")


def journey(snapshot, current):
    rows = [{"title": f"{trainer} · {key.title()} Badge", "done": bool(snapshot.badges & bit),
             "current": current in (key, "train_" + key)} for bit, key, trainer, *_ in GYMS]
    rows.append({"title": "Elite Four and Champion", "done": milestones(snapshot)["champion"],
                 "current": current.startswith("league") or current == "train_league"})
    return rows


def healing_goal(snapshot, preferred_map=None):
    candidates = [m for m, w in WORLD.items() if any(o[2] == "SPRITE_NURSE" for o in w["objects"])]
    if event_set(snapshot.event_flags, "EVENT_BEAT_SILPH_CO_GIOVANNI"):
        # Once Silph Co is freed its nurse only says thank you. She no longer heals anyone.
        candidates = [m for m in candidates if m != MAPS["SILPH_CO_9F"]]
    if preferred_map in candidates:
        candidates = [preferred_map]
    elif snapshot.map in candidates:
        candidates = [snapshot.map]
    # Multiple targets let the navigator select a reachable center by path length.
    targets = []
    for m in candidates:
        w = WORLD[m]
        nurse = next((o for o in w["objects"] if o[2] == "SPRITE_NURSE"), None)
        if nurse:
            # A Center nurse is spoken to across her counter. The one in Silph Co stands on open floor,
            # where two squares away only faces an empty tile.
            below = nurse[1] + 1
            open_floor = below < w["height"] and w["tiles"][below][nurse[0]] in w["passable"]
            targets.append((m, nurse[0], below if open_floor else nurse[1] + 2))
    return Goal("heal", "Heal the party", "Restore HP, status, and PP before continuing", tuple(targets), "up", True)
