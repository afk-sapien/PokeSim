"""Presentation data for the party, including the original game's XP curves."""
from .strategy_data import MOVES, SPECIES

TYPES = {0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison", 4: "Ground", 5: "Rock",
         6: "Bird", 7: "Bug", 8: "Ghost", 20: "Fire", 21: "Water", 22: "Grass",
         23: "Electric", 24: "Psychic", 25: "Ice", 26: "Dragon"}


def experience_at_level(level, growth):
    level = max(1, min(100, level))
    cube = level ** 3
    if growth == "FAST":
        return 4 * cube // 5
    if growth == "SLOW":
        return 5 * cube // 4
    if growth == "MEDIUM_SLOW":
        return max(0, 6 * cube // 5 - 15 * level ** 2 + 100 * level - 140)
    return cube


def party_details(mon):
    species = SPECIES.get(mon.species, {})
    growth = species.get("growth")
    xp = None
    if growth and mon.level > 0:
        floor = experience_at_level(mon.level, growth)
        ceiling = experience_at_level(mon.level + 1, growth)
        capped = mon.level >= 100
        span = max(1, ceiling - floor)
        earned = max(0, min(span, mon.experience - floor))
        xp = {"total": mon.experience, "earned": earned, "needed": span,
              "remaining": 0 if capped else max(0, ceiling - mon.experience),
              "percent": 100 if capped else round(100 * earned / span, 1), "max_level": capped}
    status = "Fainted" if mon.hp <= 0 else "Asleep" if mon.status & 7 else next(
        (label for bit, label in ((8, "Poisoned"), (16, "Burned"), (32, "Frozen"), (64, "Paralyzed"))
         if mon.status & bit), "Healthy")
    return {"dex": species.get("dex"), "experience": xp, "status_label": status,
            "type_names": list(dict.fromkeys(TYPES.get(t, "Unknown") for t in mon.types)),
            "stats": {"Attack": mon.attack, "Defense": mon.defense, "Speed": mon.speed, "Special": mon.special},
            "move_details": [{"name": MOVES.get(mid, {}).get("name", f"Move {mid}").replace("_", " ").title(),
                              "type": TYPES.get(MOVES.get(mid, {}).get("type"), "Unknown"),
                              "pp": pp, "max_pp": mon.max_pp[i] if i < len(mon.max_pp) else MOVES.get(mid, {}).get("pp", 0)}
                             for i, (mid, pp) in enumerate(zip(mon.moves, mon.pp)) if mid]}
