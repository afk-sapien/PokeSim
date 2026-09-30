"""Nickname vocabulary and bounded global customization without game-data imports."""
from functools import lru_cache

TRAINER_NAMES = (
    "ALEX", "ASH", "AVERY", "BLAIR", "CASEY", "CHARLIE", "DREW", "ELLIOT",
    "FINN", "HARPER", "JAMIE", "JORDAN", "JULES", "KAI", "KIT", "LANE",
    "MORGAN", "PARKER", "QUINN", "REESE", "RILEY", "ROBIN", "ROWAN", "SAGE",
    "SAM", "SKYE", "TAYLOR", "TOBY", "WREN", "ZIGGY",
)
# The naming screen only types A-Z and the cartridge keeps ten characters, so every name has to
# be upper case letters and no longer than that.
NAME_LIMIT = 10

# Hand-written names come first and are never dropped; the pair lists below extend the pool far
# past the number of Pokemon one adventure can hold, so an adventure stops running out and
# repeating itself once it has named a hundred of them.
CURATED_NAMES = (
    "TAXFRAUD", "MEATWIFI", "SOUPCRIME", "LORDHONK", "WETSOCK",
    "BEEFCHIEF", "HAMWIZARD", "EGGLORD", "SIRBURPS", "TOEMAYOR",
    "CRUMBOSS", "GOOSELAW", "BAGELCOP", "MILKTHIEF", "GRAVYBOAT",
    "TUBASOUP", "WIFIGOBLIN", "DIRTNAP", "BONGOWATER", "BEANCRIME",
    "MEATBALL", "SADNAPKIN", "WORMBOSS", "FLOORMILK", "CHEESELAW",
    "SCREAMBEAN", "SPOONLORD", "TOILETHAM", "PANTSDAWG", "HOTLETTUCE",
    "YELLNOODLE", "BURPSMITH", "FLATBREAD", "GASSTATION", "BEEFSTICK",
    "BONKJOVI", "ELBOWSOUP", "SOGGYJEFF", "CHONKWARD", "GRIMBISCUT",
    "HONKSAUCE", "FUNGBOSS", "DAMPSTEVE", "GOBLINMODE", "FISHJURY",
    "MEATDEPT", "TINYRIOT", "WORMLEASE", "WOBBLECOP", "FRIDGEHAM",
    "UNCLEBONK", "SHRIMPMODE", "NACHOMANCY", "YAWNATHAN", "BREADPITT",
    "FROGCOURT", "SOUPWIZARD", "BEEFJAM", "TROUSERBAT", "BLORBERT",
    "HONKCEO", "SPORKLORD", "GRAVYGHOST", "SNEEZEBAG", "GOBLINFAX",
    "SLOPMAYOR", "TOADDEBT", "MOPWATER", "DAMPBREAD", "CORNWIZARD",
    "BONGOBEAN", "SIRWOBBLE", "MEATPOCKET", "CRABRAVE", "CHEESEFEET",
    "GOOFJUICE", "FLOORLORD", "EGGSCANDAL", "MILKDRAMA", "BORKUS",
    "WETLASAGNA", "HAMCRIME", "YELLMAN", "BREADGHOST", "GRUNKLE",
    "SOUPTAX", "HONKDEPT", "DUSTBUNNY", "FISHFELONY", "SPAMWIZARD",
    "CHUNKMAIL", "BEEFALARM", "GOBLINMATH", "WORMUNION", "BONKSAUCE",
    "TOASTGHOST", "SMALLCLAIM", "SNAILBAIL", "FROGDAD", "CHEESEMAGE",
)
NAME_PREFIXES = (
    "MEAT", "SOUP", "HONK", "BEEF", "EGG", "HAM", "MILK", "BREAD", "GRAVY",
    "BEAN", "WORM", "FROG", "SNAIL", "TOAST", "CRUMB", "MOP", "SOCK", "SPOON",
    "FORK", "TUBA", "BONGO", "DIRT", "DUST", "FISH", "SHRIMP", "NACHO", "CORN",
    "PANTS", "ELBOW", "TOE", "BURP", "SNEEZE", "YAWN", "WOBBLE", "CHONK",
    "SLOP", "DAMP", "WET", "SOGGY", "FLOOR", "FRIDGE", "GOBLIN", "CHEESE",
    "GOOSE", "BAGEL", "NOODLE", "PICKLE", "GRUB", "SWAMP", "MOTH",
)
NAME_SUFFIXES = (
    "LORD", "BOSS", "CHIEF", "MAYOR", "WIZARD", "MAGE", "COP", "LAW", "CRIME",
    "TAX", "DEBT", "JURY", "COURT", "DEPT", "UNION", "GHOST", "DAD", "SMITH",
    "CEO", "FAX", "MATH", "MODE", "ALARM", "RIOT", "DRAMA", "THIEF", "BAIL",
    "WATER", "JUICE", "MAIL", "CLERK", "JUDGE", "FUND", "AUDIT",
)


def _paired_names():
    """Every prefix and suffix join that the cartridge can actually hold."""
    seen = set(CURATED_NAMES)
    names = []
    for prefix in NAME_PREFIXES:
        for suffix in NAME_SUFFIXES:
            name = prefix + suffix
            if len(name) <= NAME_LIMIT and name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


POKEMON_NAMES = CURATED_NAMES + _paired_names()



def validate_parts(values):
    if not isinstance(values, dict) or set(values) != {'nickname_prefixes', 'nickname_suffixes'}:
        raise ValueError('Provide nickname_prefixes and nickname_suffixes')
    result = {}
    for field, parts in values.items():
        if not isinstance(parts, (list, tuple)) or len(parts) > 100:
            raise ValueError('Use at most 100 nickname parts per list')
        cleaned = []
        for part in parts:
            if not isinstance(part, str):
                raise ValueError('Nickname parts must be text')
            part = part.strip().upper()
            if not 1 <= len(part) <= 7 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in part):
                raise ValueError('Each nickname part must contain 1 to 7 letters A to Z')
            if part not in cleaned:
                cleaned.append(part)
        result[field] = cleaned
    return result


@lru_cache(maxsize=16)
def name_pool(prefixes=(), suffixes=()):
    if not prefixes and not suffixes:
        return POKEMON_NAMES
    names = dict.fromkeys(POKEMON_NAMES)
    for prefix in (*NAME_PREFIXES, *prefixes):
        for suffix in (*NAME_SUFFIXES, *suffixes):
            if len(prefix + suffix) <= NAME_LIMIT:
                names[prefix + suffix] = None
    return tuple(names)


def configured_pool():
    from . import config
    return name_pool(tuple(getattr(config, 'NICKNAME_PREFIXES', ())),
                     tuple(getattr(config, 'NICKNAME_SUFFIXES', ())))
