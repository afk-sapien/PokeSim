"""The part of a Gold, Silver or Crystal observation that an adventure store keeps: the walked steps, the
Champion counter's offers and purchases, the legendary and event returns and the legendary retries, with
the policy inputs read back from them.

The application (Emulator._observe) and a headless run (adapter.py) both observe through ``shop`` and
``observe``, so a headless run plays the offers and returns the application would, from a store of its own.
"""
from __future__ import annotations

from . import champion_shop


def catalogue(host):
    """The planned Champion counter item for the clerk who opens the BUY list, as ``host`` holds it."""
    plan = host.policy.collection.get(champion_shop.PLAN)
    return champion_shop.catalogue(host.data, plan, champion_shop.ready(host.store, host.data, host.steps.value))


def shop(host, snapshot):
    """Keep the walked steps, start the offers' walking countdowns, spend the purchases that landed and
    share the ready offers with the policy. Returns the purchases, each ``(item, count, price)``."""
    host.steps.flush()
    walking = host.steps.value
    champion_shop.observe(host.store, snapshot, walking)
    stock = getattr(host, 'store_stock', None)
    purchases = list(stock.purchases) if stock else []
    if stock:
        stock.purchases.clear()
    for item, _, _ in purchases:
        champion_shop.consume(host.store, host.data, item, walking)
        plan = host.policy.collection.get(champion_shop.PLAN)
        if plan and plan['item'] == item:
            plan['bought'] = True
    host.policy.shop_offers = champion_shop.ready(host.store, host.data, walking)
    return purchases


def observe(host, snapshot, now):
    """Observe the returns and the legendary retries for the store of ``host``, an application emulator
    or a headless run, at PlayClock frame ``now``.

    Returns ``(events, changed)``. A return or retry that restores an encounter writes the cartridge,
    so ``changed`` says the snapshot must be read again."""
    from . import returns
    from .emulator import Event
    from .legendary import first_notice
    from .release import keeps_another
    store, policy, memory, walking = host.store, host.policy, host.pb.memory, host.steps.value
    events, changed = returns.observe(store, snapshot, memory, walking)
    activity, reopened = returns.observe_events(store, snapshot, memory, walking,
                                                lambda dex: keeps_another(policy, snapshot, dex))
    events = events + activity
    declined = getattr(policy, 'declined', None)
    if isinstance(declined, set):
        for dex in declined:
            returns.decline(store, dex)
        policy.declined = set()
    ready, closed = returns.claims(store)
    policy.returned = ready | returns.returned_events(store)
    retries = host.legendary_recovery
    for species in retries.observe(snapshot, memory, now, repeat=ready, blocked=closed):
        changed = True
        if first_notice(store, species, retries.attempts.get(str(species), 0)):
            events.append(Event('legendary_retry', f'{host.data.species[species]["name"]} can be encountered again',
                                'The encounter ended without a catch. Used supplies and adventure progress '
                                'are preserved.'))
    return events, changed or reopened
