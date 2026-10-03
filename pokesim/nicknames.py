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

# Keep the original written names and append valid combinations for more variety.
# Pool order does not give written names extra weight during random selection.
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
    "TACO", "WAFFLE", "DONUT", "MUFFIN", "COOKIE", "PUDDLE", "JELLY", "JAM",
    "PLUM", "PEACH", "MELON", "KIWI", "OLIVE", "ONION", "GARLIC", "RADISH",
    "TURNIP", "SPUD", "LEMON", "LIME", "PEANUT", "CASHEW", "OAT", "RICE",
    "CEREAL", "KETTLE", "BUCKET", "BROOM", "DINO", "DUCK", "YAK", "MOOSE",
    "OTTER", "CRAB", "CLAM", "SQUID", "SLOTH", "BAT", "MOSS", "MUD",
    "RUST", "FUZZ", "FLUFF", "WIGGLE", "SQUISH", "WOOZY", "DIZZY", "SLEEPY",
    "TINY", "LOUD",
)
NAME_SUFFIXES = (
    "LORD", "BOSS", "CHIEF", "MAYOR", "WIZARD", "MAGE", "COP", "LAW", "CRIME",
    "TAX", "DEBT", "JURY", "COURT", "DEPT", "UNION", "GHOST", "DAD", "SMITH",
    "CEO", "FAX", "MATH", "MODE", "ALARM", "RIOT", "DRAMA", "THIEF", "BAIL",
    "WATER", "JUICE", "MAIL", "CLERK", "JUDGE", "FUND", "AUDIT",
    "BARON", "DUKE", "KING", "QUEEN", "KNIGHT", "WITCH", "MONK", "NINJA",
    "PIRATE", "ROBOT", "PILOT", "CHEF", "COACH", "SCOUT", "AGENT", "BARD",
    "POET", "HERO", "BEAST", "FIEND", "TROLL", "GNOME", "YETI", "GREMLIN",
    "GURU", "PAL", "BUD", "UNIT", "CREW", "SQUAD", "CLUB", "ZONE",
    "LAB", "DESK", "FILE", "VAULT",
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



NICKNAME_FIELDS = ('nickname_prefixes', 'nickname_suffixes', 'nickname_names',
                   'nickname_excluded_prefixes', 'nickname_excluded_suffixes', 'nickname_excluded_names')


def nickname_defaults():
    return {name: [] for name in NICKNAME_FIELDS}


def validate_parts(values):
    if (not isinstance(values, dict) or not {'nickname_prefixes', 'nickname_suffixes'} <= set(values)
            or set(values) - set(NICKNAME_FIELDS)):
        raise ValueError('Provide nickname_prefixes and nickname_suffixes with supported nickname settings')
    result = {}
    for field, parts in values.items():
        full_names = field.endswith('_names')
        maximum = 500 if full_names else 100
        limit = NAME_LIMIT if full_names else 7
        if not isinstance(parts, (list, tuple)) or len(parts) > maximum:
            raise ValueError(f'Use at most {maximum} entries per nickname list')
        cleaned = []
        for part in parts:
            if not isinstance(part, str):
                raise ValueError('Nickname entries must be text')
            part = part.strip().upper()
            if not 1 <= len(part) <= limit or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in part):
                raise ValueError(f'Each nickname entry must contain 1 to {limit} letters A to Z')
            if part not in cleaned:
                cleaned.append(part)
        result[field] = cleaned
    complete = {**nickname_defaults(), **result}
    if not name_pool(*(tuple(complete[key]) for key in NICKNAME_FIELDS)):
        raise ValueError('Keep at least one available nickname')
    return result


@lru_cache(maxsize=16)
def name_pool(prefixes=(), suffixes=(), full_names=(), excluded_prefixes=(), excluded_suffixes=(), excluded_names=()):
    if not any((prefixes, suffixes, full_names, excluded_prefixes, excluded_suffixes, excluded_names)):
        return POKEMON_NAMES
    names = dict.fromkeys((*CURATED_NAMES, *full_names))
    for prefix in (*NAME_PREFIXES, *prefixes):
        if prefix in excluded_prefixes:
            continue
        for suffix in (*NAME_SUFFIXES, *suffixes):
            if suffix not in excluded_suffixes and len(prefix + suffix) <= NAME_LIMIT:
                names[prefix + suffix] = None
    return tuple(name for name in names if name not in excluded_names)


def configured_pool():
    from . import config
    return name_pool(*(tuple(getattr(config, key.upper(), ())) for key in NICKNAME_FIELDS))


def nickname_catalog(values):
    complete = {**nickname_defaults(), **values}
    pool = name_pool(*(tuple(complete[key]) for key in NICKNAME_FIELDS))
    return {'prefixes': NAME_PREFIXES, 'suffixes': NAME_SUFFIXES, 'names': CURATED_NAMES,
            'available': len(pool), 'examples': list(pool[:8])}


def validate_trainer_name(value):
    """Empty names retain random selection for older adventures and clients."""
    if not isinstance(value, str):
        raise ValueError('Trainer and rival names must be text')
    value = value.strip()
    if not value.isascii() or len(value) > 7 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in value.upper()):
        raise ValueError('Trainer and rival names must use 1 to 7 letters A to Z')
    return value.upper()
