"""Collection investment decisions, separate from shared DV probability math."""
import hashlib
import logging
import os
from functools import lru_cache

from pokecore.dvs import dv_probabilities

from .game_data import load
from .pokemon import experience_at_level, stored_strength
from .rarity import SELF_KO, Families, RatingUnavailable
from .strategy_data import MOVES, SPECIES

log = logging.getLogger(__name__)

GOOD_TAIL = 0.05
RARE_TAIL = 0.005
MIN_UPGRADE = 0.02
SEARCH_BUDGET = 3


def families():
    """Gen I final forms per internal species id, for rarity.py. Loaded once, as SPECIES is.

    Raises RatingUnavailable when the configured cartridge's TMs cannot be read (cartridge_machines)."""
    pool, problem = _pool()
    if pool is None:
        raise RatingUnavailable(problem)
    return pool


def rating_problem():
    """Why this run cannot rate its PC, or None. Only a rating already tried knows, so this never
    loads the tables itself."""
    return _pool()[1] if _pool.cache_info().currsize else None


@lru_cache(maxsize=1)
def _pool():
    """(Families, None), or (None, the reason) when the cartridge's TMs could not be read. The answer
    holds for the process, so a failed read is logged once and a restart tries again."""
    try:
        machines = taught_machines()
    except RatingUnavailable as error:
        log.error('The PC will not rate or release Pokémon until a restart reads the cartridge. %s', error)
        return None, str(error)
    rows = load('collection.json')['evolutions']
    after = {int(key): [row['species'] for row in evolutions] for key, evolutions in rows.items()}
    species = {key: (entry['stats'], entry['types'],
                     [*entry.get('initial_moves', []), *(move for _, move in entry.get('learnset', []))],
                     after.get(key, []))
               for key, entry in SPECIES.items() if entry.get('dex')}
    moves = {key: (move['power'], move['accuracy'], move['type']) for key, move in MOVES.items()
             if move.get('effect') not in SELF_KO}
    return Families(species, moves, machines), None


# HM01 Cut, HM03 Surf and HM04 Strength, the HMs the bot teaches (progression.py, move_development.py).
TAUGHT_HMS = frozenset({15, 57, 70})


def rom_configured():
    """Whether this run names a cartridge: ROM_PATH is set, or its default path holds a file."""
    from . import config
    return bool(os.environ.get('ROM_PATH')) or config.ROM_PATH.is_file()


def cartridge_machines():
    """(TM item to move id, TM items per internal species id) from the cartridge at ROM_PATH.

    Empty when no cartridge is configured, as in CI, or when it is not a Gen I cartridge PokeSim reads,
    since the bot then teaches no TM either. A configured Gen I cartridge whose TMs cannot be read
    raises RatingUnavailable, because a pool without them would re-rank every copy in the PC."""
    from . import config
    from .catches import TRACKED
    from .game_data import current_variant
    from .yellow import YELLOW_SHA1
    if not rom_configured():
        return {}, {}
    try:
        rom = config.ROM_PATH.read_bytes()
    except OSError as error:
        raise RatingUnavailable(f'The cartridge at ROM_PATH could not be read ({error.strerror or error}).') from error
    sha1 = hashlib.sha1(rom).hexdigest()
    if sha1 not in TRACKED:
        return {}, {}
    if (sha1 == YELLOW_SHA1) != (current_variant() == 'yellow'):
        raise RatingUnavailable('The cartridge at ROM_PATH is another version than the game data loaded.')
    from .tm_shop import cartridge_data
    try:
        return cartridge_data(rom)
    except ValueError as error:
        raise RatingUnavailable(f'{error}.') from error


def taught_machines():
    """The move ids of the TMs and HMs the bot teaches, per internal species id that can learn them.

    The bot teaches only the one-time TMs the Champion counter sells (tm_shop.LIMITED), bought or found,
    and TAUGHT_HMS. TM compatibility comes from the cartridge, so a run without one counts only the HMs.
    Raises RatingUnavailable when a configured cartridge cannot be read (cartridge_machines)."""
    from . import policies  # noqa: F401  (tm_shop imports through the policies package)
    from .tm_shop import LIMITED
    tm_moves, compatible = cartridge_machines()
    return {key: {tm_moves[item] for item in compatible.get(key, ()) if item in LIMITED and item in tm_moves}
            | TAUGHT_HMS.intersection(entry.get('hms', ()))
            for key, entry in SPECIES.items() if entry.get('dex')}


@lru_cache(maxsize=1)
def _internal():
    return {entry['dex']: key for key, entry in SPECIES.items() if entry.get('dex')}


def potential_power(mon):
    """The copy's battle power as its family's final form, at Lv 100 with full stat experience, or None,
    as when the PC cannot rate (rating_problem)."""
    try:
        return families().score(mon.get('species'), mon.get('dvs'))
    except RatingUnavailable:
        return None


def rarity(mon):
    """The chance a random copy of the family scores at least as well (rarity.py), or None."""
    try:
        return families().tail(mon.get('species'), mon.get('dvs'))
    except RatingUnavailable:
        return None


def dex_rarity(dex, dvs):
    """``rarity`` by Pokédex number, the shape pcvalue.Inputs takes. It raises RatingUnavailable when
    the PC cannot rate, so pcvalue.rate releases nothing."""
    return families().rarity(_internal().get(dex), dvs)


def assessment(mon):
    odds = dv_probabilities(mon.get('dvs'))
    return {'dv_top_percent': odds['at_least_probability'] * 100 if odds else None,
            'dv_better_percent': odds['better_probability'] * 100 if odds else None,
            'potential_power': potential_power(mon)}


def current_power(mon):
    dvs, training = mon.get('dvs'), mon.get('stat_exp')
    if (not isinstance(dvs, (list, tuple)) or not isinstance(training, (list, tuple))
            or len(dvs) != 5 or len(training) != 5
            or any(type(v) is not int or not 0 <= v <= 15 for v in dvs)
            or any(type(v) is not int or not 0 <= v <= 65535 for v in training)):
        return None
    return _current(mon.get('species'), mon.get('level'), tuple(dvs), tuple(training))


@lru_cache(maxsize=8192)
def _current(species, level, dvs, training):
    return stored_strength({'species': species, 'level': level, 'dvs': dvs, 'stat_exp': training})['power']


def rare_find(mon):
    """Whether the copy is in the rarest RARE_TAIL of its family, as the PC rates it (rarity)."""
    tail = rarity(mon)
    return tail is not None and tail <= RARE_TAIL


def veteran(copies):
    known = [(current_power(mon), mon) for mon in copies]
    known = [(power, mon) for power, mon in known if power is not None]
    return max(known, key=lambda row: (row[0], potential_power(row[1]) or 0,
                                     row[1]['level']))[1] if known else None


def automatic_trade_protected(mon, copies):
    """Preserve rare finds and a developed battler while a replacement catches up."""
    if rare_find(mon) or rating_problem():
        # A PC that cannot rate keeps every copy out of automatic trades too.
        return True
    peers = [other for other in copies if other['species'] == mon['species']]
    if SPECIES.get(mon['species'], {}).get('dex') in (144, 145, 146, 150, 151) and len(peers) == 1:
        return True
    champion = veteran(peers)
    if champion is mon and mon['level'] >= 80:
        return True
    if champion and champion['level'] >= 80:
        ceiling = potential_power(mon)
        incumbent = potential_power(champion)
        return bool(ceiling and incumbent and ceiling >= incumbent * (1 + MIN_UPGRADE)
                    and ceiling == max(potential_power(other) or 0 for other in peers))
    return False


def training_investment(mon, copies, *, hunt_available=False, searches=0):
    """Select useful upgrades and bound the search before optional level-100 training."""
    odds = dv_probabilities(mon.get('dvs'))
    tail = odds['at_least_probability'] if odds else None
    perfect = tail == 1 / 65536
    peers = [other for other in copies if other['species'] == mon['species'] and other is not mon]
    completed = [other for other in peers if other['level'] >= 100]
    ceiling = potential_power(mon)
    previous = max((potential_power(other) or 0 for other in completed), default=0)
    gain = (ceiling / previous - 1) if ceiling and previous else None
    if completed and gain is not None and gain < MIN_UPGRADE and not perfect:
        return {'eligible': False, 'priority': 0, 'reason': 'Existing level-100 partner is close in potential'}
    if (tail is not None and tail > GOOD_TAIL and hunt_available
            and searches < SEARCH_BUDGET and mon['level'] < 80):
        return {'eligible': False, 'priority': 0, 'reason': 'Search for a better candidate first'}
    priority = 3 if tail is not None and tail <= RARE_TAIL else 2 if tail is not None and tail <= GOOD_TAIL else 1
    growth = SPECIES.get(mon['species'], {}).get('growth')
    remaining = max(0, experience_at_level(100, growth) - experience_at_level(mon['level'], growth))
    # Quality leads, while remaining training and any replacement gain shape choices within a tier.
    weight = (1 + min(1, max(0, gain or 0)) * 10) / (0.1 + remaining / max(1, experience_at_level(100, growth)))
    return {'eligible': True, 'priority': priority, 'weight': weight,
            'reason': 'Exceptional DVs' if priority == 3 else 'Strong DVs' if priority == 2 else 'Best available candidate'}
