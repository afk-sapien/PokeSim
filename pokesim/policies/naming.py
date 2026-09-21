"""Enter random, readable names using the game's normal naming menus."""
import random

from .base import Action


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


class NamingController:
    def __init__(self, seed=None):
        # Naming draws do not consume the exploration or battle policy's RNG.
        self.rng = random.Random(seed)
        self.used = set()
        self.target = None
        self.subject = None

    def state_dict(self):
        return {"rng": self.rng.getstate(), "used": sorted(self.used),
                "target": self.target, "subject": self.subject}

    def load_state_dict(self, data):
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value, (list, tuple)) else value
        if "rng" in data:
            self.rng.setstate(tuples(data["rng"]))
        self.used = set(data.get("used", []))
        self.target = data.get("target")
        self.subject = data.get("subject")

    def step(self, scr, snapshot):
        """Return one observed menu action, or None when naming is not needed."""
        text = scr.text.upper()
        if not scr.naming:
            self.target = self.subject = None
            if scr.cursor and ((scr.yes_no and "NICKNAME" in text) or
                               (not snapshot.started and "NEW NAME" in text)):
                return Action("up" if scr.menu_index else "a", 6, 24)
            return None

        subject = "pokemon" if "NICKNAME" in text else "rival" if "RIVAL" in text else "player"
        if self.target is None or self.subject != subject:
            pool = POKEMON_NAMES if subject == "pokemon" else TRAINER_NAMES
            occupied = self.used | {snapshot.player_name, snapshot.rival_name}
            occupied.update(p.nick for p in snapshot.party)
            choices = [name for name in pool if name not in occupied]
            self.target = self.rng.choice(choices or pool)
            self.used.add(self.target)
            self.subject = subject

        # The entered text is at (10, 2). Read it back after every button press,
        # so missed inputs and restores partway through a name are recoverable.
        entered = scr.rows[2][10:20].strip()
        if not self.target.startswith(entered):
            return Action("b", 6, 24)
        if entered == self.target:
            return Action("start", 6, 24)
        if any(row[2:19:2] == "abcdefghi" for row in scr.rows):
            return Action("select", 6, 24)
        if scr.cursor is None:
            return Action(None, 0, 12)

        letter = self.target[len(entered)]
        offset = ord(letter) - ord("A")
        target_x, target_y = 1 + (offset % 9) * 2, 5 + (offset // 9) * 2
        x, y = scr.cursor
        if y != target_y:
            button = "down" if y < target_y else "up"
        elif x != target_x:
            button = "right" if x < target_x else "left"
        else:
            button = "a"
        return Action(button, 6, 24)
