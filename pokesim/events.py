"""Turn consecutive RAM snapshots into game events."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from .game_data import load
from pathlib import Path
from typing import Callable

from .ram import (BADGES, DEX_NAMES, HALL_OF_FAME_MAP, ITEM_NAMES, KEY_ITEM_IDS, LEADERS, NOTABLE_TRAINERS,
                  SPECIES_NAMES, TRAINER_NAMES, Snapshot)

EVOLUTION_PAIRS = {(int(parent), row['species'])
                   for parent, rows in load('collection.json')['evolutions'].items()
                   for row in rows}

MONEY_MILESTONES = (10_000, 50_000, 100_000, 250_000, 500_000, 999_999)
PLAYTIME_MILESTONE_HOURS = 10

# Priority scale (same as ntfy's): 5 urgent, 4 high, 3 normal, 2 low, 1 minimal.
# Events at NOTABLE_PRIORITY or above are "notable": they get a save state, go to the feed by default
# and are pushed to ntfy (subject to NTFY_MIN_PRIORITY). MINIMAL ones only show on the timeline.
URGENT, HIGH, NORMAL, LOW, MINIMAL = 5, 4, 3, 2, 1
NOTABLE_PRIORITY = LOW
LEGENDARY_DEX = {144, 145, 146, 150, 151}       # the birds, Mewtwo, Mew
ELITE_FOUR = {33, 44, 46, 47}                    # Bruno, Lorelei, Agatha, Lance (trainer classes)


@dataclass
class Event:
    type: str
    title: str
    body: str = ""
    priority: int = NORMAL      # 1..5, see above
    tags: str = ""              # ntfy emoji tags
    notable: bool = None        # derived from priority unless set explicitly
    # If set, the event is only emitted when this still holds on the *next* snapshot. Guards against
    # half-written RAM during cutscenes (e.g. a party struct with species set but HP not yet filled in).
    still: Callable[[Snapshot], bool] | None = None

    def __post_init__(self):
        if self.notable is None:
            self.notable = self.priority >= NOTABLE_PRIORITY


@dataclass
class RunMemory:
    """Persisted per-run state the detector needs across restarts."""
    seen_maps: set[int] = field(default_factory=set)
    money_milestones: set[int] = field(default_factory=set)
    playtime_milestones: set[int] = field(default_factory=set)

    def to_dict(self):
        return {"seen_maps": sorted(self.seen_maps), "money_milestones": sorted(self.money_milestones),
                "playtime_milestones": sorted(self.playtime_milestones)}

    @classmethod
    def from_dict(cls, d):
        return cls(set(d.get("seen_maps", [])), set(d.get("money_milestones", [])),
                   set(d.get("playtime_milestones", [])))


def _mon_label(p) -> str:
    return p.nick if p.nick and p.nick.upper() != p.name.upper() else p.name


def diff(prev: Snapshot | None, cur: Snapshot, mem: RunMemory) -> list[Event]:
    """Compare two snapshots. Mutates `mem`. Safe to call with prev=None (only records state)."""
    events: list[Event] = []
    if not cur.started or not cur.valid:
        return events                       # title screen / intro / glitched: nothing to report
    if prev is None or not prev.started or not prev.valid:
        mem.seen_maps.add(cur.map)
        return events

    # Recognize actual evolution pairs and exclude party swaps.
    evolved_species: set[int] = set()
    removed = Counter(p.species for p in prev.party) - Counter(p.species for p in cur.party)
    added = Counter(p.species for p in cur.party) - Counter(p.species for p in prev.party)
    if len(prev.party) == len(cur.party):
        for a, b in zip(prev.party, cur.party):
            if ((a.species, b.species) in EVOLUTION_PAIRS and removed[a.species] and added[b.species]
                    and (a.nick == b.nick or a.nick.upper() == a.name.upper() and b.nick.upper() == b.name.upper())):
                removed[a.species] -= 1
                added[b.species] -= 1
                evolved_species.add(b.species)
                events.append(Event("evolve", f"{_mon_label(a)} evolved into {b.name}!",
                                    f"Level {b.level}, on {cur.map_name}.", priority=HIGH, tags="sparkles",
                                    still=lambda s, sp=b.species: any(p.species == sp for p in s.party)))

    # --- pokedex owned / catches ---
    new_owned = cur.owned - prev.owned
    for dex in sorted(new_owned):
        name = DEX_NAMES.get(dex, f"#{dex}")
        if any(SPECIES_NAMES.get(s) == name for s in evolved_species):
            continue
        if cur.in_battle == 1 or prev.in_battle == 1 or len(cur.party) > len(prev.party):
            lvl = cur.enemy_level or prev.enemy_level
            legendary = dex in LEGENDARY_DEX
            events.append(Event("catch", f"Caught {name}!" if not legendary else f"Caught the legendary {name}!",
                                f"A level {lvl} {name} on {cur.map_name}. Pokédex: {len(cur.owned)} owned.",
                                priority=URGENT if legendary else HIGH, tags="tada",
                                still=lambda s, d=dex: d in s.owned))
        else:
            events.append(Event("obtain", f"Got {name}!",
                                f"New Pokédex entry on {cur.map_name}. {len(cur.owned)} owned.", priority=HIGH,
                                tags="gift", still=lambda s, d=dex: d in s.owned))
    for dex in sorted(cur.seen - prev.seen - new_owned):
        events.append(Event("seen", f"Saw {DEX_NAMES.get(dex, f'#{dex}')} for the first time", priority=MINIMAL,
                            still=lambda s, d=dex: d in s.seen))

    # --- badges ---
    gained = cur.badges & ~prev.badges
    for i in range(8):
        if gained & (1 << i):
            events.append(Event("badge", f"Beat {LEADERS[i]}! Got the {BADGES[i]} Badge",
                                f"{bin(cur.badges).count('1')}/8 badges after {cur.playtime[0]}h of play.",
                                priority=URGENT, tags="trophy"))

    # --- levels / faints ---
    if len(prev.party) == len(cur.party):
        for a, b in zip(prev.party, cur.party):
            if a.species == b.species and b.level > a.level:
                events.append(Event("level", f"{_mon_label(b)} grew to level {b.level}",
                                    priority=HIGH if b.level in (50, 100) else NORMAL if b.level % 10 == 0 else MINIMAL,
                                    tags="arrow_up"))
            if a.species == b.species and a.hp > 0 and b.hp == 0 and not cur.all_fainted:
                events.append(Event("faint", f"{_mon_label(b)} fainted", priority=MINIMAL,
                                    still=lambda s, i=len(events): True))
    if cur.all_fainted and not prev.all_fainted:
        events.append(Event("blackout", "Blacked out!",
                            f"The whole party fainted on {cur.map_name}" +
                            (f" fighting a {SPECIES_NAMES.get(cur.enemy_species, '?')}." if cur.in_battle == 1 else "."),
                            priority=LOW, tags="skull", still=lambda s: s.all_fainted))

    # --- trainer battles ---
    if prev.in_battle == 2 and cur.in_battle == 0 and not cur.all_fainted and prev.trainer_class is not None:
        tc = prev.trainer_class
        name = TRAINER_NAMES.get(tc, f"trainer #{tc}")
        if name.startswith("Rival"):
            name = f"rival {cur.rival_name}" if cur.rival_name else "the rival"
        prio = URGENT if tc in ELITE_FOUR else HIGH if tc in NOTABLE_TRAINERS else MINIMAL
        events.append(Event("trainer", f"Defeated {name}", f"On {cur.map_name}.", priority=prio, tags="crossed_swords"))

    # --- new areas / hall of fame ---
    if cur.map not in mem.seen_maps:
        mem.seen_maps.add(cur.map)
        if cur.map == HALL_OF_FAME_MAP:
            events.append(Event("champion", "CHAMPION! Entered the Hall of Fame",
                                f"Party: {', '.join(f'{_mon_label(p)} L{p.level}' for p in cur.party)}. "
                                f"Play time {cur.playtime[0]}h.", priority=URGENT, tags="crown"))
        else:
            events.append(Event("map", f"Entered {cur.map_name}", f"Area #{len(mem.seen_maps)} discovered.",
                                priority=LOW, tags="world_map"))

    # --- key items ---
    prev_items = {i for i, _ in prev.items}
    for i, _ in cur.items:
        if i in KEY_ITEM_IDS and i not in prev_items:
            events.append(Event("item", f"Got the {ITEM_NAMES.get(i, f'item #{i}')}", f"On {cur.map_name}.",
                                priority=HIGH, tags="key"))

    # --- money ---
    for m in MONEY_MILESTONES:
        if cur.money >= m > prev.money and m not in mem.money_milestones:
            mem.money_milestones.add(m)
            events.append(Event("money", f"Wallet passed ${m:,}", priority=NORMAL if m >= 100_000 else MINIMAL,
                                tags="moneybag"))

    # --- names ---
    if cur.rival_name and not prev.rival_name:
        events.append(Event("name", f"The rival is named {cur.rival_name}", tags="speech_balloon"))

    # --- play time ---
    h = cur.playtime[0]
    if h and h % PLAYTIME_MILESTONE_HOURS == 0 and h not in mem.playtime_milestones and prev.playtime[0] != h:
        mem.playtime_milestones.add(h)
        events.append(Event("playtime", f"{h} hours of play time",
                            f"{len(cur.owned)} owned, {bin(cur.badges).count('1')} badges, on {cur.map_name}.",
                            priority=LOW, tags="hourglass"))
    return events
