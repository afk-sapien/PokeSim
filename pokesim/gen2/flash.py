"""Light a dark cave with Flash so viewers can see it.

pret's map headers give a dark cave PALETTE_DARK, and the snapshot's ``flash`` is on once Flash lights
it. It stays on for the next cave floor and goes off outdoors (ResetFlashIfOutOfCave), so one use
lights a whole cave. A party without Flash, or without the Zephyr Badge, walks the cave dark.
"""
from .menus import FieldMove

FLASH = 148


def dark(data, map_id):
    """Whether pret's header gives this map the dark palette."""
    return data.maps.get(map_id, {}).get('palette') == 'PALETTE_DARK'


def task(policy, snapshot):
    """The Flash to use on entering a dark map, or None.

    It is offered once per map entered, so a refusal never holds up the walk. A map left and entered
    again is offered again.
    """
    if not dark(policy.data, snapshot.map):
        policy.flash_map = None
        return None
    if policy.flash_map == snapshot.map or snapshot.flash or not snapshot.badges & 1:
        return None
    slot = next((i for i, mon in enumerate(snapshot.party) if not mon.egg and FLASH in mon.moves), None)
    if slot is None:
        return None
    use = FieldMove(slot, 'FLASH')
    if not policy.allowed(use, snapshot):
        return None
    policy.flash_map = snapshot.map
    return use
