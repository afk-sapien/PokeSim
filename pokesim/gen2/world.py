"""Persistent map changes derived from cartridge event flags."""
from pokesim_core.gen2.maps import event_changes


def update(regions, snapshot):
    """Show every map's flag-dependent walls and doors to ``regions``, as Core reads them."""
    for mid, grid in event_changes(snapshot.data, snapshot, regions.live).items():
        regions.observe(mid, grid)
