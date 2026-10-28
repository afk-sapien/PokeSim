"""Gen II journal entries that Red, Blue and Yellow also write: sightings, faints, trainers and milestones."""
from __future__ import annotations

from ..events import HIGH, LOW, MINIMAL, MONEY_MILESTONES, NORMAL, PLAYTIME_MILESTONE_HOURS, URGENT

# The legendary birds, Mewtwo and Mew, then Raikou, Entei, Suicune, Lugia, Ho-Oh and Celebi.
LEGENDARY_DEX = frozenset({144, 145, 146, 150, 151, 243, 244, 245, 249, 250, 251})

# pret constants/trainer_constants.asm, the same in Gold, Silver and Crystal up to Mysticalman.
TRAINER_NAMES = (
    None, 'Falkner', 'Whitney', 'Bugsy', 'Morty', 'Pryce', 'Jasmine', 'Chuck', 'Clair', 'Rival', 'Pokémon Prof.',
    'Will', 'Cal', 'Bruno', 'Karen', 'Koga', 'Lance', 'Brock', 'Misty', 'Lt. Surge', 'Scientist', 'Erika',
    'Youngster', 'Schoolboy', 'Bird Keeper', 'Lass', 'Janine', 'Cooltrainer', 'Cooltrainer', 'Beauty',
    'PokéManiac', 'Rocket Grunt', 'Gentleman', 'Skier', 'Teacher', 'Sabrina', 'Bug Catcher', 'Fisher', 'Swimmer',
    'Swimmer', 'Sailor', 'Super Nerd', 'Rival', 'Guitarist', 'Hiker', 'Biker', 'Blaine', 'Burglar', 'Firebreather',
    'Juggler', 'Blackbelt', 'Rocket Executive', 'Psychic', 'Picnicker', 'Camper', 'Rocket Executive', 'Sage',
    'Medium', 'Boarder', 'Pokéfan', 'Kimono Girl', 'Twins', 'Pokéfan', 'Red', 'Blue', 'Officer', 'Rocket Grunt',
    'Mysticalman')
RIVALS = frozenset({9, 42})
ELITE_FOUR = frozenset({11, 13, 14, 15, 16})        # Will, Bruno, Karen, Koga and the Champion, Lance
NOTABLE_TRAINERS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 17, 18, 19, 21, 26, 35, 46, 64, 51, 55, 63}) | RIVALS
# Entries that say nothing about progress, so the watchdog's no-progress clock ignores them, as in Red, Blue and Yellow.
NOT_PROGRESS = frozenset({'seen', 'faint', 'blackout', 'money', 'playtime', 'name'})
UNNAMED = frozenset({'', '???'})                     # the cartridge names the rival ??? until the player does


def _label(mon):
    return mon.nick if mon.nick and mon.nick.upper() != mon.name.upper() else mon.name


def _species(data, dex):
    return data.species.get(dex, {}).get('name') or f'#{dex}'


def catch(data, dex, before, snapshot, event):
    """The Pokédex entry for a new catch, at the Red, Blue and Yellow wording when it is a legendary."""
    battle = snapshot.in_battle == 1 or before is not None and before.in_battle == 1
    name = _species(data, dex)
    if dex in LEGENDARY_DEX and battle:
        level = snapshot.enemy_level or (before.enemy_level if before else 0)
        return event('catch', f'Caught the legendary {name}!',
                     f'A level {level} {name} on {snapshot.map_name}. Pokédex: {len(snapshot.owned)} owned.',
                     priority=URGENT)
    return event('catch', f'{name} joined the Pokédex', priority=HIGH)


def _key_items(data, snapshot):
    pockets = getattr(snapshot, 'pockets', None) or {}
    hms = {data.items.get(f'HM{i:02d}') for i in range(1, 8)} - {None}
    return [item for item, _ in pockets.get('key', ())] + [item for item, _ in pockets.get('machines', ()) if item in hms]


def events(before, snapshot, history, data, event):
    """Compare two consecutive snapshots, the way pokesim.events.diff does for Red, Blue and Yellow.

    ``history`` keeps the money and play time milestones across restarts. Nothing is reported
    without an earlier snapshot, so a boot or a reload never repeats old news.
    """
    if before is None or not before.valid or not before.started or not snapshot.valid or not snapshot.started:
        return []
    out = []
    for dex in sorted(snapshot.seen - before.seen - (snapshot.owned - before.owned)):
        out.append(event('seen', f'Saw {_species(data, dex)} for the first time', priority=MINIMAL, notable=False))

    if len(before.party) == len(snapshot.party):
        for old, mon in zip(before.party, snapshot.party):
            if ((old.species, old.trainer_id, old.dvs) == (mon.species, mon.trainer_id, mon.dvs) and not mon.egg
                    and old.hp > 0 and mon.hp == 0 and not snapshot.all_fainted):
                out.append(event('faint', f'{_label(mon)} fainted', priority=MINIMAL, notable=False))
    if snapshot.all_fainted and not before.all_fainted:
        foe = f' fighting a {_species(data, snapshot.enemy_species)}' if snapshot.in_battle == 1 else ''
        out.append(event('blackout', 'Blacked out!', f'The whole party fainted on {snapshot.map_name}{foe}.',
                         priority=LOW))

    if before.in_battle == 2 and snapshot.in_battle == 0 and not (before.all_fainted or snapshot.all_fainted):
        tc = before.trainer_class
        name = TRAINER_NAMES[tc] if 0 < tc < len(TRAINER_NAMES) else f'trainer #{tc}'
        if tc in RIVALS:
            name = 'the rival' if snapshot.rival_name in UNNAMED else f'rival {snapshot.rival_name}'
        priority = URGENT if tc in ELITE_FOUR else HIGH if tc in NOTABLE_TRAINERS else MINIMAL
        out.append(event('trainer', f'Defeated {name}', f'On {snapshot.map_name}.', priority=priority,
                         notable=priority > MINIMAL))

    held = set(_key_items(data, before))
    for item in dict.fromkeys(_key_items(data, snapshot)):
        if item not in held:
            out.append(event('item', f'Got the {data.item_names.get(item, f"item #{item}")}',
                             f'On {snapshot.map_name}.', priority=HIGH))

    reached = history.setdefault('money_milestones', [])
    for mark in MONEY_MILESTONES:
        if snapshot.money >= mark > before.money and mark not in reached:
            reached.append(mark)
            out.append(event('money', f'Wallet passed ${mark:,}', priority=NORMAL if mark >= 100_000 else MINIMAL,
                             notable=mark >= 100_000))

    if snapshot.rival_name not in UNNAMED and before.rival_name in UNNAMED:
        out.append(event('name', f'The rival is named {snapshot.rival_name}'))

    hours = snapshot.playtime[0]
    played = history.setdefault('playtime_milestones', [])
    if hours and hours % PLAYTIME_MILESTONE_HOURS == 0 and hours not in played and before.playtime[0] != hours:
        played.append(hours)
        out.append(event('playtime', f'{hours} hours of play time',
                         f'{len(snapshot.owned)} owned, {bin(snapshot.badges).count("1")} badges, on {snapshot.map_name}.',
                         priority=LOW))
    return out
