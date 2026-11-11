"""Rate the PC and choose what the Generation II policy releases or stores."""
from __future__ import annotations

from pokecore.gen2.ram import Memory
from ..menus import Release
from .state import Goal


class StoragePart:
    """PC ratings, releases and the storage goal."""

    def storage_units(self, snapshot):
        """The ledger's next box unit and the next one that can go straight from the box. Kept until
        storage or the plans change."""
        from ..ledger import storage_unit
        key = (self.rating_key(snapshot), snapshot.pockets.get('items', ()),
               tuple(self.collection.get('prerequisites', ())), self.decisions // 600)
        if self.release_cache[0] != key:
            self.release_cache = (key, (storage_unit(self, snapshot), storage_unit(self, snapshot, direct=True)))
        return self.release_cache[1]

    def release_owners(self):
        """The original trainers whose Pokémon a release may let go: the player and the linked adventures.
        None before the cartridge's memory is attached, which leaves the trainer out of the rules."""
        from ...trade.partners import owners
        player = Memory(self.memory, self.data).word('wPlayerID') if self.memory is not None else None
        return owners(player, self.trade_partners())

    def rating_key(self, snapshot):
        """Everything the PC values read: the Pokémon, the plans, the trade settings, the linked
        adventures, the League rewards, the owner's release requests, the Favor setting, the team
        seen at this PC visit, the Pokédex and the open hunt."""
        from ..release import hunt_focus, plan_partners
        preferences = self.trade_preferences()
        return (snapshot.party, snapshot.stored, snapshot.active_box, tuple(sorted(self.demand.items())), self.visit_team.keys,
                frozenset(getattr(snapshot, 'owned', ()) or ()), hunt_focus(self.collection),
                tuple(sorted(map(str, plan_partners(self.collection)))), self.release_owners(),
                tuple(sorted((key, (value or {}).get('state')) for key, value in preferences.items())),
                frozenset(self.league_marks()) if hasattr(self, 'league_marks') else frozenset(),
                tuple(sorted(self.release_requests().items())) if hasattr(self, 'release_requests') else (),
                self.pc_favor() if hasattr(self, 'pc_favor') else None)

    def pc_rated(self, snapshot, marks=frozenset(), extra=()):
        """Every Pokémon scored as the next release scores it (pcvalue.py), for the PC tab, the ledger
        and the owner's requests. Kept until rating_key changes, so a waiting request does not rate the
        whole PC on every decision. Extra League reward ``marks`` or ``extra`` rows give a one-off rating."""
        from ..release import release_rated
        if marks or extra:
            return release_rated(self, snapshot, marks=marks, extra=extra)
        key = self.rating_key(snapshot)
        if self.rated_cache[0] != key:
            self.rated_cache = (key, release_rated(self, snapshot))
        return self.rated_cache[1]

    def release_target(self, snapshot):
        """The spare duplicate to release next straight from the box, or None."""
        unit = self.storage_units(snapshot)[1]
        return unit.detail if unit else None

    def storage_target(self, snapshot):
        """The ledger's next box unit: a spare to release, or one whose item comes off first. None when
        nothing can free a slot."""
        return self.storage_units(snapshot)[0]

    def trade_spare(self, snapshot, protect=(), wished=()):
        """The spare to release so a trade can be prepared with every box full, or None.

        It is the lowest-value Pokémon that may go (pcvalue.py). The ``protect`` trade keys, hand-picked
        for a trade, stay as if set to Keep, and a ``wished`` species counts as stock.
        """
        from ...pcvalue import queue
        from ..release import _keys, release_rated
        from pokecore.identity import same
        preferences = dict(self.trade_preferences())
        if protect:
            # A key from an older release names its Pokémon by trainer and DVs only.
            for mon in snapshot.stored:
                own = _keys(mon)[0]
                if any(same(own, key) for key in protect):
                    preferences[own] = {'state': 'locked'}
        return next((row.entry.record for row in queue(release_rated(self, snapshot, wished, preferences))
                     if self.allowed(Release(row.entry.record.box, row.entry.record.position), snapshot)), None)

    def no_room(self, snapshot):
        """Every box is full and nothing can be released, so a catch has nowhere to go."""
        return (not snapshot.can_catch and all(count >= 20 for count in snapshot.box_counts)
                and self.storage_target(snapshot) is None)

    def release_goal(self, snapshot, mem, releasing=False):
        """Visit a PC to let spare duplicates go while the ledger wants box slots freed.

        Without this a full PC leaves every catch, one-time encounter and field-move errand
        walking to a PC that has nowhere to put anything. A visit under way (``releasing``) frees
        slots up to the refill mark.
        """
        from ...planning.ledger import box_wanted
        from ..release import headroom, pending
        # A spare whose item is coming off keeps the visit going until it is gone, even past the refill
        # mark, and an owner's release request starts a visit of its own.
        unequipping = bool(self.collection.get('unequip')) or pending(self, snapshot)
        # A catch goes to a free party slot first, so a new visit counts those as room. Without this a PC
        # errand that deposits one partner before it withdraws another started a release visit in between.
        room = headroom(snapshot) + (0 if releasing else max(6 - len(snapshot.party), 0))
        if (not (box_wanted(room, releasing) or unequipping) or self.in_league(snapshot) or self.in_transmitter_room(snapshot)
                or snapshot.map == self.data.map_ids['POKECENTER_2F'] or self.collection.get('time_capsule_restore')
                or self.collection.get('tower') or mem.byte('wStatusFlags2') & 4):
            return None
        if self.storage_target(snapshot) is None and not unequipping:
            return None
        goal = self.storage_goal(snapshot)
        if goal.key != 'storage':
            return None
        return Goal('collection_release', 'Make room in storage',
                    goal.map_name, goal.x, goal.y, goal.face)

    def storage_goal(self, snapshot):
        choices, unreachable = [], []
        region = self.travel_region(snapshot)
        for mid, entry in self.data.maps.items():
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            pcs = [(index % entry['width'], index // entry['width'] + 1)
                   for index, tile in enumerate(entry['collision']) if tile == 0x93]
            # Kept for a cartridge restored somewhere no route is known, such as a cable room.
            unreachable.extend((entry['region'] != region, mid, x, y) for x, y in pcs)
            if entry['region'] != region:
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.walk(snapshot, mid)
            if route is None:
                continue
            choices.extend((len(route), mid, x, y) for x, y in pcs)
        if not choices:
            if snapshot.map == self.data.map_ids['POKECENTER_2F']:
                return Goal('return_from_cable', 'Return downstairs after the Cable Club', 'POKECENTER_2F', 0, 7)
            # Aim at the nearest known Pokémon Center by id and let navigation and stall recovery sort it out.
            _, mid, x, y = min(unreachable)
        else:
            nearest = min(choices)[0]
            tied = [choice[1:] for choice in choices if choice[0] == nearest]
            # Two Pokémon Centers the same number of maps away can swap places as the player crosses a
            # warp, as Rock Tunnel and Route 10 do. Keeping the earlier pick stops the walk turning back.
            kept = getattr(self, 'storage_pick', None)
            mid, x, y = kept if kept in tied else min(tied)
            self.storage_pick = (mid, x, y)
        return Goal('storage', 'Prepare a place for a field move partner', self.data.maps[mid]['constant'], x, y, 'up')
