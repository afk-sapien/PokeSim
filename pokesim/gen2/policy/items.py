"""Use healing and cure items for the Generation II policy."""
from __future__ import annotations

from ..menus import Remedy, UseOn


class ItemPart:
    """League treatments, field cures and remedies."""

    def league_items(self, snapshot):
        """Use the next item between League rooms (planning/boss.py treatment): a Revive for a fainted
        fighter, a restore up to the boss check's bar, or an Ether or Elixir for spent strong moves."""
        from ..ledger import league_treatment
        found = league_treatment(self.data, snapshot)
        if found is None:
            return False
        slot, item, move = found
        count = dict(snapshot.items)[item]
        task = UseOn(item, slot, count, move) if move is not None else Remedy(item, slot, count)
        if not self.allowed(task, snapshot):
            return False
        self.menu = task
        return True

    def field_cure(self, snapshot):
        """Cure a status outside battle and outside the League with the cheapest cure in the bag
        (ledger.field_cure). The heal check leaves such a status out (ledger.cured)."""
        from ..ledger import field_cure
        items = dict(snapshot.items)
        for slot, mon in enumerate(snapshot.party):
            name = field_cure(self.data, items, mon)
            if name is None:
                continue
            item = self.data.items[name]
            if self.allowed(task := Remedy(item, slot, items[item]), snapshot):
                self.menu = task
                return True
        return False

    def remedy(self, snapshot, *, active=None, cures=False):
        """Use a remedy on a party member, or on the one in battle when ``active`` is set. With ``cures``
        only status cures, which league_items leaves to it."""
        items = dict(snapshot.items)
        for slot, mon in enumerate(snapshot.party):
            if mon.egg or active is not None and slot != active or cures and (mon.hp == 0 or not mon.status):
                continue
            names = ()
            from ..champion_shop import elixir
            restore = None if cures else elixir(self.data, snapshot, mon)
            # A remedy the game refused recently is skipped like any other refused shortcut, or the
            # battle would rebuild it every decision and never press a button.
            if restore and self.allowed(task := Remedy(restore, slot, items[restore]), snapshot):
                self.menu = task
                return True
            if mon.hp == 0:
                names = ('MAX_REVIVE', 'REVIVE')
            elif not cures and mon.hp < mon.max_hp * (0.55 if snapshot.in_battle else 0.8):
                names = ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION', 'SUPER_POTION', 'POTION')
            elif mon.status:
                names = ('FULL_RESTORE', 'FULL_HEAL', 'ANTIDOTE' if mon.status & 8 else
                         'AWAKENING' if mon.status & 7 else 'PARLYZ_HEAL' if mon.status & 64 else
                         'BURN_HEAL' if mon.status & 16 else 'ICE_HEAL')
            task = next((task for name in names if items.get(item := self.data.items[name], 0)
                         and self.allowed(task := Remedy(item, slot, items[item]), snapshot)), None)
            if task:
                self.menu = task
                return True
        return False
