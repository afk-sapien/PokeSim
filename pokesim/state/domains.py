"""Every kv key, kv key prefix and adventure table, declared once with what a reload and a restart do to it.

The lives (docs/design/adventure-state-store.md section 3.3):

- ``rewinds``: a reload takes it back with the save, and a restart starts it empty.
- ``resets_on_restart``: a reload keeps it, and an owner restart resets it.
- ``survives``: a reload and a restart both keep it.

An owner restart (the ``restart`` command in ``emulator.py`` and ``gen2/emulator.py``) calls
``Store.restart``, which empties every domain ``restarted`` names for that generation in one
transaction. A key that only one generation keeps names only that generation.

``policy_reads`` marks the keys a policy decision can read: through what ``Store.attach`` hands the
policy, through a value an emulator sets on the policy, or because the key decides whether and how
the policy steps. ``cached`` marks the keys ``Store.get`` may keep for the rest of one observation.

tests/test_state_domains.py fails on a kv key the package uses that is not declared here. A new
ledger needs one line below.
"""
from dataclasses import dataclass

REWINDS = 'rewinds'
RESETS_ON_RESTART = 'resets_on_restart'
SURVIVES = 'survives'
LIVES = (REWINDS, RESETS_ON_RESTART, SURVIVES)

KEY = 'key'
PREFIX = 'prefix'
TABLE = 'table'

# The custom reward that is staged or committed but not yet recovered, from runtime.reward_delivery.
PENDING_REWARD = 'custom-reward-pending-v1'
# Set by the restart's transaction and cleared once the old game's autosaves are gone.
RESTART_PENDING = 'restart-pending-v1'


@dataclass(frozen=True)
class Domain:
    key: str
    owner: str
    life: str
    generations: tuple = (1, 2)
    policy_reads: bool = False
    cached: bool = False
    kind: str = KEY


def _prefix(key, owner, life, generations=(1, 2), **fields):
    return Domain(key, owner, life, generations, kind=PREFIX, **fields)


def _table(name, owner, life, generations=(1, 2), **fields):
    return Domain(name, owner, life, generations, kind=TABLE, **fields)


GEN1 = (1,)
GEN2 = (2,)

DOMAINS = (
    # The last kv copies of checkpoint manifest fields. The autosaves stopped writing them when boot and
    # reload began to read the manifest alone (docs/design/adventure-state-store.md section 3.5). A Gen I
    # save with no manifest reads the policy copy, and a Gen II boot reads the history copy for a manifest
    # from before it carried one. A restart drops both.
    Domain('policy_state', 'pokesim.emulator', REWINDS),
    Domain('gen2-history', 'pokesim.gen2.emulator', REWINDS, GEN2),

    # The playtime hours Gen I has announced, which a reload keeps so the same hour is not announced twice.
    Domain('playtime-milestones-v1', 'pokesim.emulator', RESETS_ON_RESTART, GEN1),

    # Reset by the restart in both generations.
    Domain(PENDING_REWARD, 'pokesim.runtime.reward_delivery', RESETS_ON_RESTART),
    Domain('league-rewards-v1', 'pokesim.rewards', RESETS_ON_RESTART, policy_reads=True),
    Domain('play_clock', 'pokesim.emulator', RESETS_ON_RESTART),
    Domain('capture-statistics-v1', 'pokesim.catches', RESETS_ON_RESTART),
    Domain('pokedex-milestones-v1', 'pokesim.milestones', RESETS_ON_RESTART, cached=True),
    Domain('adventure-records-v1', 'pokesim.adventure_records', RESETS_ON_RESTART),
    _prefix('trade_offer:', 'pokesim.trade.preferences', RESETS_ON_RESTART, policy_reads=True),
    Domain('shiny-statistics-v1', 'pokesim.shiny', RESETS_ON_RESTART, GEN1, cached=True),
    Domain('gen2-shiny-statistics-v1', 'pokesim.shiny', RESETS_ON_RESTART, GEN2),

    # Reset only by the Gen II restart.
    Domain('gen2-mythical-gift-v1', 'pokesim.gen2.rewards', RESETS_ON_RESTART, GEN2),
    Domain('gen2-gs-ball-distribution-v1', 'pokesim.gen2.celebi', RESETS_ON_RESTART, GEN2),
    Domain('gen2-league-partners-v1', 'pokesim.gen2.league', RESETS_ON_RESTART, GEN2),
    Domain('gen2-mew-returns-v1', 'pokesim.gen2.steps', RESETS_ON_RESTART, GEN2, policy_reads=True),
    Domain('gen2-clock-v1', 'pokesim.gen2.emulator', RESETS_ON_RESTART, GEN2),

    # Reset only by the Gen I restart, as the Gen II restart resets its own copies.
    Domain('league-partners-v2', 'pokesim.league_partners', RESETS_ON_RESTART, GEN1),
    # Read once, to move a Gen I file from before league-partners-v2. A new game must not inherit
    # its partners through that move.
    Domain('league-partners-v1', 'pokesim.league_partners', RESETS_ON_RESTART, GEN1),
    Domain('mew-returns-v1', 'pokesim.mew_returns', RESETS_ON_RESTART, GEN1, policy_reads=True, cached=True),
    # The Mew gift's marker. The Pokedex of the new game sets it again once Mew is owned.
    Domain('pokesim-mew-v1', 'pokesim.runtime.reward_delivery', RESETS_ON_RESTART, GEN1, cached=True),

    # Reset by both restarts, so the new game's stall counts and goal times start empty.
    Domain('loop-guard-reloads-v1', 'pokesim.stalls', RESETS_ON_RESTART),
    Domain('goal-time-v1', 'pokesim.goal_time', RESETS_ON_RESTART),

    Domain(RESTART_PENDING, 'pokesim.store', SURVIVES),

    # The trade and reward barriers, and the trade journal.
    Domain('trade_hold', 'pokesim.runtime.participant', SURVIVES, policy_reads=True),
    Domain('trade_barrier', 'pokesim.runtime.participant', SURVIVES),
    Domain('custom-reward-barrier-v1', 'pokesim.runtime.reward_delivery', SURVIVES),
    Domain('interaction_preparation', 'pokesim.runtime.preparation', SURVIVES, policy_reads=True),
    _prefix('managed_interaction:', 'pokesim.runtime.participant', SURVIVES),
    # One marker per trade the journal already tells.
    _prefix('managed_journal:', 'pokesim.runtime.participant', SURVIVES),
    Domain('trade_partners', 'pokesim.trade.partners', SURVIVES, policy_reads=True),
    Domain('trade_settings_v1', 'pokesim.trade.preferences', SURVIVES),

    # What the owner and the policy keep about the collection.
    Domain('release_requests', 'pokesim.store', SURVIVES, policy_reads=True),
    Domain('pc_favor', 'pokesim.store', SURVIVES, policy_reads=True),
    Domain('pc_deadlock_logged', 'pokesim.pcvalue', SURVIVES),
    Domain('boss_losses', 'pokesim.planning.losses', SURVIVES, policy_reads=True),
    Domain('boss_aces', 'pokesim.planning.losses', SURVIVES, policy_reads=True),
    Domain('fair-wild-dvs-v1', 'pokesim.fair_dvs', SURVIVES),
    # The seed every bot choice is drawn from. A restart draws a new one for the new game.
    Domain('adventure-seed-v1', 'pokesim.seeds', RESETS_ON_RESTART, policy_reads=True),

    # Walking, returns and the Champion shops.
    Domain('cartridge-steps-v1', 'pokesim.gen2.steps', SURVIVES, policy_reads=True, cached=True),
    Domain('step-events-v1', 'pokesim.step_events', SURVIVES, GEN1, cached=True),
    Domain('legendary-returns-v1', 'pokesim.legendary_returns', SURVIVES, GEN1, cached=True),
    Domain('champion-shop-v1', 'pokesim.champion_shop', SURVIVES, GEN1, policy_reads=True),
    Domain('gen2-champion-shop-v1', 'pokesim.gen2.champion_shop', SURVIVES, GEN2, policy_reads=True),
    Domain('gen2-legendary-returns-v1', 'pokesim.gen2.returns', SURVIVES, GEN2, policy_reads=True),
    Domain('gen2-event-returns-v1', 'pokesim.gen2.returns', SURVIVES, GEN2, policy_reads=True),
    Domain('gen2-legendary-retry-notices-v1', 'pokesim.gen2.legendary', SURVIVES, GEN2),

    # Lifetime tallies, and markers of one-time moves.
    Domain('activity-ledger-v1', 'pokesim.activity_ledger', SURVIVES),
    Domain('adventure-counters-v1', 'pokesim.adventure_counters', SURVIVES),
    Domain('adventure-statistics-v1', 'pokesim.statistics', SURVIVES),
    Domain('trade-statistics-v1', 'pokesim.trade_statistics', SURVIVES),
    Domain('capture-gift-backfill-v1', 'pokesim.catches', SURVIVES, GEN1),

    # Tables. The restart empties the capture and shiny receipts, the encounter rows and the claims.
    # A reload keeps the claims but sends a gift delivered after the save back to open (rewards.rewound).
    _table('claims', 'pokesim.state.claims', RESETS_ON_RESTART, policy_reads=True),
    _table('capture_receipts', 'pokesim.catches', RESETS_ON_RESTART),
    _table('progress_events', 'pokesim.progress_events', RESETS_ON_RESTART),
    _table('encounter_counts', 'pokesim.progress_events', RESETS_ON_RESTART),
    _table('shiny_receipts', 'pokesim.shiny', RESETS_ON_RESTART, GEN1),
    _table('gen2_shiny_receipts', 'pokesim.shiny', RESETS_ON_RESTART, GEN2),
    _table('events', 'pokesim.store', SURVIVES),
    _table('progress', 'pokesim.progress', SURVIVES),
    _table('statistics_history', 'pokesim.statistics', SURVIVES),
    _table('activity_counts', 'pokesim.activity_ledger', SURVIVES),
    _table('activity_receipts', 'pokesim.activity_ledger', SURVIVES),
    _table('pokemon_trade_receipts', 'pokesim.trade_statistics', SURVIVES),
    _table('stall_truth', 'pokesim.stall_truth', SURVIVES),
    # The legacy pair trade's applied transactions.
    _table('completed_trades', 'pokesim.trade.pair', SURVIVES),
    _table('completed_events', 'pokesim.trade.event', SURVIVES),
)

KEYS = {domain.key: domain for domain in DOMAINS if domain.kind == KEY}
PREFIXES = {domain.key: domain for domain in DOMAINS if domain.kind == PREFIX}
TABLES = {domain.key: domain for domain in DOMAINS if domain.kind == TABLE}
CACHED = frozenset(key for key, domain in KEYS.items() if domain.cached)
POLICY_READS = tuple(domain.key for domain in DOMAINS if domain.policy_reads)


def restarted(generation):
    """The domains a restart of this generation empties: the ones it resets and the ones a reload rewinds."""
    return tuple(domain for domain in DOMAINS if generation in domain.generations
                 and domain.life in (REWINDS, RESETS_ON_RESTART))


def find(key):
    """The domain a kv key belongs to: its own declaration, or the prefix it starts with. None if neither."""
    if key in KEYS:
        return KEYS[key]
    return next((domain for prefix, domain in PREFIXES.items() if key.startswith(prefix)), None)
