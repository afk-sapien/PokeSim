"""Collection investment decisions, separate from shared DV probability math."""
from functools import lru_cache

from pokesim_core.dvs import dv_probabilities

from .pokemon import experience_at_level, stored_strength
from .strategy_data import SPECIES

GOOD_TAIL = 0.05
RARE_TAIL = 0.005
MIN_UPGRADE = 0.02
SEARCH_BUDGET = 3


@lru_cache(maxsize=8192)
def _potential(species, dvs):
    return stored_strength({'species': species, 'level': 100, 'dvs': dvs,
                            'stat_exp': (65535,) * 5})['power']


def potential_power(mon):
    dvs = mon.get('dvs')
    if (not isinstance(dvs, (list, tuple)) or len(dvs) != 5
            or any(type(v) is not int or not 0 <= v <= 15 for v in dvs)):
        return None
    return _potential(mon.get('species'), tuple(dvs))


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
    odds = dv_probabilities(mon.get('dvs'))
    return bool(odds and odds['at_least_probability'] <= RARE_TAIL)


def veteran(copies):
    known = [(current_power(mon), mon) for mon in copies]
    known = [(power, mon) for power, mon in known if power is not None]
    return max(known, key=lambda row: (row[0], potential_power(row[1]) or 0,
                                     row[1]['level']))[1] if known else None


def automatic_trade_protected(mon, copies):
    """Preserve rare finds and a developed battler while a replacement catches up."""
    if rare_find(mon):
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
