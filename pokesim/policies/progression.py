"""Story prerequisites and concrete short-term destinations."""
from dataclasses import dataclass, replace
from functools import lru_cache

from .battle import replacement_slot
from .team import readiness

from ..strategy_data import ITEMS, MAPS, SPECIES, WORLD, event_set, object_hidden


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
            approaches = []
            for dx, dy, facing in ((0, 1, "up"), (1, 0, "left"), (0, -1, "down"), (-1, 0, "right")):
                tx, ty = x + dx, y + dy
                if 0 <= ty < world["height"] and 0 <= tx < world["width"] and world["tiles"][ty][tx] in world["passable"]:
                    approaches.append((m, tx, ty, facing))
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
    out["champion"] = snapshot.map == MAPS["HALL_OF_FAME"] or event_set(flags, "EVENT_BEAT_CHAMPION_RIVAL")
    return out


def story_goal(snapshot):
    flags = snapshot.event_flags
    has = lambda name: any(item == ITEMS[name] and qty for item, qty in snapshot.items)
    if not event_set(flags, "EVENT_FOLLOWED_OAK_INTO_LAB") and not snapshot.party:
        return at("meet_oak", "Meet Professor Oak", "A starter is needed before leaving town", "PALLET_TOWN", 10, 1)
    if not snapshot.party:
        return at("starter", "Choose Bulbasaur", "Build an early team suited to the first gyms", "OAKS_LAB", 8, 4, "up")
    if not event_set(flags, "EVENT_GOT_POKEDEX"):
        if has("OAKS_PARCEL") or event_set(flags, "EVENT_GOT_OAKS_PARCEL"):
            return at("pokedex", "Deliver Oak’s parcel", "Obtain the Pokédex and open the northward route", "OAKS_LAB", 5, 3, "up")
        return at("parcel", "Collect Oak’s parcel", "The Viridian clerk has a delivery for Oak", "VIRIDIAN_MART", 2, 5, "left")
    if not snapshot.badges & 1:
        if readiness(snapshot, 1)['score'] < 75 and max(p.level for p in snapshot.party) < 22:
            grass = []
            for name in ("ROUTE_2", "VIRIDIAN_FOREST"):
                m = MAPS[name]
                w = WORLD[m]
                grass.extend((m, x, y) for y, row in enumerate(w["tiles"]) for x, tile in enumerate(row)
                             if tile == (0x52 if name == "ROUTE_2" else 0x20))
            return Goal("train_brock", "Prepare for Brock", "Build a useful matchup against Brock before entering the gym", tuple(grass))
        return at("boulder", "Challenge Brock", "Earn the Boulder Badge to continue east", "PEWTER_GYM", 4, 2, "up")
    return campaign_goal(snapshot)


GYMS = (
    (1, "boulder", "Brock", "PEWTER_GYM", "BROCK", 13, "ROUTE_2"),
    (2, "cascade", "Misty", "CERULEAN_GYM", "MISTY", 18, "ROUTE_24"),
    (4, "thunder", "Lt. Surge", "VERMILION_GYM", "LT_SURGE", 22, "ROUTE_11"),
    (8, "rainbow", "Erika", "CELADON_GYM", "ERIKA", 28, "ROUTE_7"),
    (16, "soul", "Koga", "FUCHSIA_GYM", "KOGA", 37, "ROUTE_15"),
    (32, "marsh", "Sabrina", "SAFFRON_GYM", "SABRINA", 40, "ROUTE_15"),
    (64, "volcano", "Blaine", "CINNABAR_GYM", "BLAINE", 44, "POKEMON_MANSION_1F"),
    (128, "earth", "Giovanni", "VIRIDIAN_GYM", "GIOVANNI", 47, "ROUTE_21"),
)
GYM_HELP = {
    "cascade": "Clear the gym trainers and approach Misty. Grass or Electric attacks help against her Water team.",
    "thunder": "Use Cut from a party Pokémon outside the gym. Inside, find the first trash-can switch, then an adjacent second switch. Hand back to the AI after opening the electric barriers.",
    "rainbow": "Use Cut to enter the Celadon gym and clear the central tree. Fire and Flying attacks help against Erika.",
    "soul": "Follow the outer edge of Koga’s gym around the invisible walls, then approach him from the south.",
    "marsh": "Use the Saffron gym teleport pads to reach Sabrina. Hand control back when you reach her room.",
    "volcano": "Surf south from Pallet to Cinnabar. Use the Secret Key to enter the gym, then beat each quiz trainer or answer their question to open the doors.",
    "earth": "Use the Viridian gym’s arrow tiles to reach Giovanni. Water and Grass attacks help against his Ground team.",
}


def training_goal(key, title, reason, map_name):
    m = MAPS[map_name]
    w = WORLD[m]
    # Outdoor grass and indoor encounter floors are navigated using the same graph.
    targets = tuple((m, x, y) for y, row in enumerate(w["tiles"]) for x, tile in enumerate(row)
                    if tile == 0x52 or (map_name == "POKEMON_MANSION_1F" and tile in w["passable"]))
    return Goal("train_" + key, title, reason, targets)


def gym_goal(s, bit):
    _, key, trainer, gym, obj, level, route = next(g for g in GYMS if g[0] == bit)
    assessment = readiness(s, bit)
    if assessment['score'] < 75 and max(p.level for p in s.party) < level + 10 and s.map != MAPS[gym]:
        return training_goal(key, f"Prepare for {trainer}",
                             f"Build usable damage and survival against {trainer}, then reassess the team", route)
    return replace(object_goal(key, f"Challenge {trainer}", f"Use the team's best available matchup against {trainer}", gym, obj),
                   help=GYM_HELP.get(key, "Approach the gym leader and start the battle."))


def teaching_goal(key, title, reason, s):
    move = {"teach_cut": 15, "teach_surf": 57, "teach_strength": 70}[key]
    if not any(move in SPECIES.get(p.species, {}).get("hms", [])
               and (0 in p.moves or replacement_slot(p, move) is not None) for p in s.party):
        stored = any(move in SPECIES.get(species, {}).get("hms", []) for species, level in s.boxed_pokemon)
        if stored:
            targets = tuple((m, 13, 4) for m, w in WORLD.items() if "Pokecenter" in w["name"] and w["width"] == 14)
            return Goal("party_" + key.removeprefix("teach_"), "Bring a field-move partner onto the team",
                        "Use Bill’s PC to store a reserve and withdraw a compatible partner", targets, "up", True)
        if move in SPECIES.get(next((sid for sid, d in SPECIES.items() if d.get('name') == 'LAPRAS'), 0), {}).get('hms', []) and event_set(s.event_flags, 'EVENT_BEAT_SILPH_CO_GIOVANNI'):
            return object_goal("lapras", "Meet the rescued Silph worker", "Accept an accessible Lapras for the missing field move", "SILPH_CO_7F", "SILPH_WORKER_M1")
        name = key.removeprefix('teach_')
        return Goal('catch_' + name, f'Find a {name.title()} partner',
                    f'Search reachable habitats for a Pokémon that can learn {name.title()}',
                    partner_habitats(move, max((p.level for p in s.party), default=5)))
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


def campaign_goal(s):
    done = lambda name: event_set(s.event_flags, name)
    has = lambda name: any(item == ITEMS[name] and qty for item, qty in s.items)
    knows = lambda move: any(move in p.moves for p in s.party)
    def obj(key, title, reason, map_name, fragment, help=""):
        return replace(object_goal(key, title, reason, map_name, fragment), help=help)
    if not s.badges & 2:
        west = {MAPS[n] for n in ("PEWTER_CITY", "ROUTE_3", "MT_MOON_1F", "MT_MOON_B1F", "MT_MOON_B2F")}
        if (s.map in west or (s.map == MAPS["ROUTE_4"] and s.x < 21)) and not (done("EVENT_GOT_DOME_FOSSIL") or done("EVENT_GOT_HELIX_FOSSIL")):
            if not done("EVENT_BEAT_MT_MOON_EXIT_SUPER_NERD"):
                return obj("moon_trainer", "Find a way through Mt. Moon", "Defeat the Super Nerd guarding the fossils", "MT_MOON_B2F", "SUPER_NERD")
            return obj("fossil", "Choose a fossil", "Collect a fossil to clear the exit toward Cerulean", "MT_MOON_B2F", "HELIX_FOSSIL")
        return gym_goal(s, 2)
    if not s.badges & 4:
        if not (has("S_S_TICKET") or done("EVENT_GOT_SS_TICKET") or has("HM01") or knows(15)):
            if done("EVENT_USED_CELL_SEPARATOR_ON_BILL"):
                return obj("ticket", "Collect Bill’s ticket", "Speak to the restored Bill for passage on the S.S. Anne", "BILLS_HOUSE", "BILL_SS_TICKET")
            if done("EVENT_BILL_SAID_USE_CELL_SEPARATOR"):
                return at("bill_pc", "Help Bill out of the machine", "Activate the PC on the left side of Bill’s house", "BILLS_HOUSE", 1, 5, "up")
            return obj("bill", "Help Bill", "Cross Nugget Bridge and follow Route 25 to Bill’s house", "BILLS_HOUSE", "BILL_POKEMON")
        if not done("EVENT_BEAT_CERULEAN_ROCKET_THIEF"):
            return obj("rocket_thief", "Open the road south", "Go through the robbed house and defeat the Rocket behind it", "CERULEAN_CITY", "ROCKET", "Leave the robbed house through its rear exit and battle the Rocket. Continue south through the underground path toward Vermilion.")
        if not (has("HM01") or knows(15)):
            return obj("cut", "Visit the ship’s captain", "Board the S.S. Anne and help its captain to receive Cut", "SS_ANNE_CAPTAINS_ROOM", "CAPTAIN")
        if not knows(15):
            return teaching_goal("teach_cut", "Teach Cut to a partner", "Teach HM01 to a compatible partner to open routes blocked by trees.", s)
        return gym_goal(s, 4)
    if not s.badges & 8:
        return replace(gym_goal(s, 8), help="Reach Lavender through Rock Tunnel, then go west through the Route 8 underground path to Celadon. Use Cut at Erika’s gym. " + GYM_HELP["rainbow"])
    if not s.badges & 16:
        if not (has("POKE_FLUTE") or done("EVENT_GOT_POKE_FLUTE")):
            if not has("SILPH_SCOPE") and not done("EVENT_RESCUED_MR_FUJI"):
                if not done("EVENT_FOUND_ROCKET_HIDEOUT"):
                    if not object_hidden(s, MAPS["GAME_CORNER"], 10):
                        return obj("poster_guard", "Investigate the guarded poster", "Talk to the Rocket guarding the Game Corner poster", "GAME_CORNER", "ROCKET")
                    return replace(at("hideout", "Investigate the Game Corner", "Defeat the Rocket and inspect the poster behind him", "GAME_CORNER", 9, 5, "up"), help="Battle the Rocket in front of the poster, then inspect the poster to reveal the stairs.")
                if not has("LIFT_KEY") and not done("EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"):
                    if not done("EVENT_ROCKET_DROPPED_LIFT_KEY"):
                        return obj("lift_rocket", "Find the Lift Key", "Defeat the B4F Rocket and speak to him again so he drops the key", "ROCKET_HIDEOUT_B4F", "ROCKET3", "Navigate the hideout’s spin tiles to B4F. Defeat the Rocket in the northwest room and speak to him again.")
                    return obj("lift_key", "Pick up the Lift Key", "Collect the key dropped by the Rocket", "ROCKET_HIDEOUT_B4F", "LIFT_KEY")
                if not done("EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI"):
                    if s.map != MAPS["ROCKET_HIDEOUT_B4F"] or s.x < 22:
                        return at("hideout_elevator", "Take the lift to Giovanni’s floor", "Use the Lift Key and choose B4F", "ROCKET_HIDEOUT_ELEVATOR", 1, 2, "up")
                    for index in range(2):
                        if not done(f"EVENT_BEAT_ROCKET_HIDEOUT_4_TRAINER_{index}"):
                            return obj("boss_guard", "Open Giovanni’s door", "Defeat both Rockets guarding the door", "ROCKET_HIDEOUT_B4F", f"ROCKET{index + 1}")
                    return obj("rocket_boss", "Confront Giovanni", "Take the hideout elevator to B4F and defeat Giovanni", "ROCKET_HIDEOUT_B4F", "GIOVANNI", "Use the Lift Key and elevator to reach B4F. Defeat both door guards, then approach Giovanni.")
                if s.map != MAPS['ROCKET_HIDEOUT_B4F'] or s.x < 22:
                    return at('hideout_elevator', 'Return for the Silph Scope',
                              'Take the lift to B4F before collecting the Scope', 'ROCKET_HIDEOUT_ELEVATOR', 1, 2, 'up')
                return obj("scope", "Collect the Silph Scope", "Pick up the Silph Scope left behind Giovanni", "ROCKET_HIDEOUT_B4F", "SILPH_SCOPE")
            if not done("EVENT_RESCUED_MR_FUJI"):
                return obj("fuji", "Rescue Mr. Fuji", "Climb Pokémon Tower, resolve the Marowak encounter, and clear the Rockets", "POKEMON_TOWER_7F", "MR_FUJI")
            return obj("flute", "Collect the Poké Flute", "Speak to Mr. Fuji in his Lavender house", "MR_FUJIS_HOUSE", "MR_FUJI")
        if not done("EVENT_BEAT_ROUTE12_SNORLAX") and s.map != MAPS["FUCHSIA_CITY"]:
            return replace(obj("snorlax", "Wake the sleeping roadblock", "Reach Snorlax on Route 12 and play the Poké Flute", "ROUTE_12", "SNORLAX"), help="Stand next to Snorlax, use the Poké Flute from the bag, then let the AI handle the battle.")
        return gym_goal(s, 16)
    if not s.badges & 32:
        if not s.saffron_open:
            if not any(has(n) for n in ("FRESH_WATER", "SODA_POP", "LEMONADE")):
                return replace(at("guard_drink", "Bring a drink for the Saffron guards", "Buy Fresh Water from a vending machine on the Celadon department store roof", "CELADON_MART_ROOF", 10, 2, "up"), help="Use the rooftop vending machine and buy Fresh Water. Keep it in the bag for the Saffron guard.")
            return at("saffron_gate", "Open the way into Saffron", "Offer the guard a drink by walking through the gate", "ROUTE_7_GATE", 3, 3)
        if not done("EVENT_BEAT_SILPH_CO_GIOVANNI"):
            if not has("CARD_KEY"):
                return obj("card_key", "Find Silph’s Card Key", "Collect the key in the south corridor on the fifth floor", "SILPH_CO_5F", "CARD_KEY", "Reach the fifth floor’s south corridor. Step onto the nearby warp pad and back to get around the blocking Rocket, then collect the Card Key.")
            return obj("silph", "Free Silph Co.", "Use the Card Key and warp pads to reach Giovanni on the eleventh floor", "SILPH_CO_11F", "GIOVANNI", "Open the third-floor central door, take its warp to the rival on 7F, then the next pad to 11F. Open the president’s door and defeat Giovanni.")
        return gym_goal(s, 32)
    if not (s.badges & 64 and s.badges & 128):
        if not (has("HM03") or knows(57)):
            return obj("surf", "Find the Safari Zone’s secret house", "Reach the secret house in the west area to receive Surf", "SAFARI_ZONE_SECRET_HOUSE", "FISHING_GURU", "Enter the Safari Zone with room in the bag. Travel east, north, then west to the secret house before the step limit expires.")
        if not knows(57):
            return teaching_goal("teach_surf", "Teach Surf to a partner", "Teach HM03 to a compatible partner so the team can cross water.", s)
        if not (has("HM04") or knows(70)):
            if not has("GOLD_TEETH"):
                return obj("teeth", "Find the warden’s Gold Teeth", "Pick up the Gold Teeth near the Safari Zone’s secret house", "SAFARI_ZONE_WEST", "GOLD_TEETH")
            return obj("strength", "Return the warden’s teeth", "Bring the Gold Teeth to the warden in Fuchsia to receive Strength", "WARDENS_HOUSE", "WARDEN")
        if not knows(70):
            return teaching_goal("teach_strength", "Teach Strength to a partner", "Teach HM04 to a compatible partner for the boulders on Victory Road.", s)
    if not s.badges & 64:
        if not has("SECRET_KEY"):
            return obj("secret_key", "Unlock the Cinnabar gym", "Surf south from Pallet and explore the Pokémon Mansion for the Secret Key", "POKEMON_MANSION_B1F", "SECRET_KEY", "Surf from Pallet to Cinnabar. In the mansion, use the statue switches and the third-floor drop to reach the basement and collect the Secret Key.")
        return gym_goal(s, 64)
    if not s.badges & 128:
        return gym_goal(s, 128)
    rooms = (
        ("LORELEIS_ROOM", "LORELEI", "EVENT_BEAT_LORELEIS_ROOM_TRAINER_0", "Lorelei"),
        ("BRUNOS_ROOM", "BRUNO", "EVENT_BEAT_BRUNOS_ROOM_TRAINER_0", "Bruno"),
        ("AGATHAS_ROOM", "AGATHA", "EVENT_BEAT_AGATHAS_ROOM_TRAINER_0", "Agatha"),
        ("LANCES_ROOM", "LANCE", "EVENT_BEAT_LANCE", "Lance"),
        ("CHAMPIONS_ROOM", "RIVAL", "EVENT_BEAT_CHAMPION_RIVAL", "the Champion"),
    )
    if done("EVENT_BEAT_CHAMPION_RIVAL") or s.map == MAPS["HALL_OF_FAME"]:
        return Goal("champion", "Kanto Champion", "The team made it to the Hall of Fame", help="You won. Take a moment with the team.")
    league_maps = {MAPS[r[0]] for r in rooms}
    if s.map not in league_maps:
        assessments = [readiness(s, bit) for bit in range(256, 261)]
        partner = league_partner(s)
        if partner is not None and s.party[partner].level < 55 and any(a['score'] < 75 for a in assessments):
            return training_goal('league_partner', 'Prepare a second League battler',
                                 'Build coverage for the League matchups that remain difficult', 'POKEMON_MANSION_1F')
        if max(p.level for p in s.party) < 65 and any(a['score'] < 60 for a in assessments):
            return training_goal('league', 'Prepare for the Pokémon League',
                                 'Improve damage and survival across the final matchups', 'ROUTE_23')
        if s.map != MAPS['INDIGO_PLATEAU_LOBBY']:
            return at('league_entrance', 'Return to the Pokémon League',
                      'Begin a new challenge through the lobby, where the game resets the previous attempt',
                      'INDIGO_PLATEAU_LOBBY', 8, 10)
        return obj('league_lorelei', 'Challenge Lorelei', 'Start the next League attempt with Lorelei',
                   'LORELEIS_ROOM', 'LORELEI')
    current = next(i for i, row in enumerate(rooms) if MAPS[row[0]] == s.map)
    for i, (room, trainer, flag, title) in enumerate(rooms):
        if i < current:
            continue
        if i > current or not done(flag):
            return obj("league_" + trainer.lower(), f"Challenge {title}", "Advance through the League one battle at a time", room, trainer,
                       "Use Surf through Route 23 and Strength on Victory Road’s boulder switches. Heal and stock up at Indigo Plateau before entering. Inside the League, continue north after each battle.")


def league_partner(snapshot):
    strongest = max(range(len(snapshot.party)), key=lambda i: snapshot.party[i].level)
    candidates = [i for i, p in enumerate(snapshot.party) if i != strongest
                  and SPECIES.get(p.species, {}).get("stats", [0])[0] >= 90]
    return max(candidates, key=lambda i: snapshot.party[i].max_hp + snapshot.party[i].attack) if candidates else None


def journey(snapshot, current):
    rows = [{"title": f"{trainer} · {key.title()} Badge", "done": bool(snapshot.badges & bit),
             "current": current in (key, "train_" + key)} for bit, key, trainer, *_ in GYMS]
    rows.append({"title": "Elite Four and Champion", "done": milestones(snapshot)["champion"],
                 "current": current.startswith("league") or current == "train_league"})
    return rows


def healing_goal(snapshot, preferred_map=None):
    candidates = [m for m, w in WORLD.items() if any(o[2] == "SPRITE_NURSE" for o in w["objects"])]
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
            targets.append((m, nurse[0], nurse[1] + 2))
    return Goal("heal", "Heal the party", "Restore HP, status, and PP before continuing", tuple(targets), "up", True)
