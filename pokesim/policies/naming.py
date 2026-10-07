"""Enter random, readable names using the game's normal naming menus."""
import random
from pokesim_core.naming import name_step

from .base import Action
from ..textmatch import ScreenText


from ..nicknames import (
    POKEMON_NAMES as POKEMON_NAMES, CURATED_NAMES as CURATED_NAMES,
    NAME_LIMIT as NAME_LIMIT, NAME_PREFIXES as NAME_PREFIXES, NAME_SUFFIXES as NAME_SUFFIXES,
    TRAINER_NAMES, configured_pool,
)


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
        text = ScreenText(scr.text.upper())
        if not scr.naming:
            self.target = self.subject = None
            if scr.cursor and ((scr.yes_no and "NICKNAME" in text) or
                               (not snapshot.started and "NEW NAME" in text)):
                return Action("up" if scr.menu_index else "a", 6, 24)
            return None

        subject = "pokemon" if "NICKNAME" in text else "rival" if "RIVAL" in text else "player"
        if self.target is None or self.subject != subject:
            pool = configured_pool() if subject == "pokemon" else TRAINER_NAMES
            occupied = self.used | {snapshot.player_name, snapshot.rival_name}
            occupied.update(p.nick for p in snapshot.party)
            from .. import config
            occupied.update((getattr(config, 'TRAINER_NAME', ''), getattr(config, 'RIVAL_NAME', '')))
            choices = [name for name in pool if name not in occupied]
            preferred = (getattr(config, 'TRAINER_NAME', '') if subject == 'player' else
                         getattr(config, 'RIVAL_NAME', '') if subject == 'rival' else '')
            self.target = preferred or self.rng.choice(choices or pool)
            self.used.add(self.target)
            self.subject = subject

        action = name_step(scr.rows, scr.cursor, self.target,
                           limit=10 if subject == "pokemon" else 7)
        return Action(*action) if action else None
