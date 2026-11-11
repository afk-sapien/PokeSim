"""Judge the Generation II policy's errands, boss checks and stalled conversations."""
from __future__ import annotations

from ...planning import league
from ..navigation import DIRS
from ..readiness import BOSS_TABLE, aces
from .state import Goal


class ErrandPart:
    """Fishing, shops, boss checks, healing and conversation stalls."""

    def fishing(self, snapshot, move=None):
        move = self.needed_move(snapshot) if move is None else move
        map_name = 'BLACKTHORN_CITY' if move == 127 else 'OLIVINE_CITY'
        mid = self.data.map_ids[map_name]
        entry = self.data.maps[mid]
        choices = []
        for y in range(1, entry['height'] - 1):
            for x in range(1, entry['width'] - 1):
                if not self.nav.passable(entry['collision'][y * entry['width'] + x]):
                    continue
                for face, (dx, dy) in DIRS.items():
                    if entry['collision'][(y + dy) * entry['width'] + x + dx] not in (0x21, 0x29):
                        continue
                    path = self.nav.local(snapshot, [(x, y)]) if snapshot.map == mid else []
                    # An unreachable shore ranks last instead of leaving nothing to choose from.
                    choices.append((len(path) if path is not None else 1_000_000, x, y, face))
        _, x, y, face = min(choices)
        return Goal('fish_surf', 'Catch a partner for field moves', map_name, x, y, face)

    # Shop scripts that check an event and skip the pokemart once it is set, in all three games.
    CLOSED_SHOPS = {'MahoganyMart1FPharmacistScript': 'EVENT_DECIDED_TO_HELP_LANCE'}

    def clerk_present(self, snapshot, entry, shop):
        """Whether a clerk running this shop's script is on the map.

        A set event flag hides its object, so a shop whose every clerk is hidden cannot be used:
        Mahogany Mart's Team Rocket pharmacist leaves for good once the hideout is cleared, and
        the grandmother at the other counter takes over the shop.

        A clerk can also stay on the map and stop selling. Once the player agrees to help Lance,
        the pharmacist only talks about him until he leaves, so his counter is closed too.
        """
        closed_by = self.CLOSED_SHOPS.get(shop['script'])
        if closed_by and snapshot.event(closed_by):
            return False
        return any(obj['script'] == shop['script']
                   and (obj['event'] not in self.data.events or not snapshot.event(obj['event']))
                   for obj in entry['objects'])

    def in_league(self, snapshot):
        return self.constant(snapshot) in BOSS_TABLE.league

    def in_transmitter_room(self, snapshot):
        return (snapshot.map == self.data.map_ids['TEAM_ROCKET_BASE_B2F']
                and snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEF_2')
                and not snapshot.event('EVENT_CLEARED_ROCKET_HIDEOUT'))

    def errand_allowed(self, snapshot, mem):
        """Whether a heal or supply errand may break off the current goal."""
        well_item = (self.goal.key == 'collection_trade_item'
                     and self.constant(snapshot) in {'SLOWPOKE_WELL_B1F', 'SLOWPOKE_WELL_B2F'})
        return (not self.goal.key.startswith('push_') and not well_item
                and (not self.collection.get('contest') or not mem.byte('wStatusFlags2') & 4))

    def league_boss(self, snapshot):
        """The League as the oracle judges a postgame run (collection.league_run), its scores read."""
        return league.boss(BOSS_TABLE, BOSS_TABLE.league_row, self.constant(snapshot), self.matchup(snapshot),
                           aces(self.data))

    def boss_training(self, snapshot, goal):
        """A walk that trains before the boss or story goal ``goal`` (planning/league.training), or None
        once the oracle finds the team ready."""
        from ...planning.readiness import LOSS
        plan = league.training(BOSS_TABLE, snapshot, getattr(goal, 'key', None), self.constant(snapshot),
                               self.move_power, self.losses, self.matchup(snapshot), aces(self.data))
        if plan is None:
            return None
        row, level = plan.row, plan.verdict.target
        if row is None:
            label = f'Train the team to level {level} before another try at: {goal.label}'
        elif plan.verdict.reason == LOSS:
            label = f'Train the team to level {level} before {row.name}'
        elif row.league:
            label = f'Prepare for the Pokémon League: train until the team matches up or reaches level {level}'
        else:
            label = f'Prepare for {row.name}: train until the team matches up or reaches level {level}'
        from ..training import walk_goal
        return walk_goal(self, snapshot, Goal, lambda: label, map_name=plan.where)

    def note_boss_loss(self, snapshot):
        """Remember the best fighter level that lost to the boss the goal names (planning/league.note_loss).

        A boss goal's loss counts on its goal's map or anywhere in the League."""
        league.note_loss(BOSS_TABLE, self.losses, getattr(self.goal, 'key', None), self.constant(snapshot),
                         snapshot, self.move_power, rooms=BOSS_TABLE.league | {getattr(self.goal, 'map_name', None)})

    def heal_blocked(self, snapshot):
        """Whether healing stands down here: the League, the transmitter room, Ice Path, the Goldenrod
        warehouse, or Burned Tower before the beasts run."""
        if (self.in_transmitter_room(snapshot) or self.in_league(snapshot)
                or self.constant(snapshot).startswith('ICE_PATH_')
                or self.constant(snapshot) in {
                    'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES'}):
            return True
        return (snapshot.map == self.data.map_ids['BURNED_TOWER_B1F']
                and (not snapshot.event('EVENT_RELEASED_THE_BEASTS') or self.data.game == 'crystal'
                     and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER')))

    def boss_ready(self, snapshot, blocked):
        """The boss check before the goal under way (planning/league.check): READY, HEAL or UNREADY.

        HEAL needs a Pokémon Center the heal walk can reach, or, between League rooms, an item in the bag
        that treats a short fighter (league_items). A collection survey writes nothing to the journal.
        """
        from ..ledger import fighters, league_treatment
        goal = self.goal
        verdict, rows = league.check(
            BOSS_TABLE, self, goal, fighters(self.data, snapshot), lambda: not blocked and self.center(snapshot) is not None,
            where=snapshot.map, inside=self.in_league(snapshot), center=self.constant(snapshot).endswith('POKECENTER_1F'),
            treatment=lambda: league_treatment(self.data, snapshot) is not None, title=lambda: goal.label,
            names=lambda: [mon.name for mon in snapshot.party if not mon.egg], quiet=getattr(self, 'ladder_survey', False))
        if rows:
            from ..collection import pin_events
            pin_events(self).extend(rows)
        return verdict

    def center(self, snapshot):
        """The Pokémon Center the heal walk goes to, as (map, nurse), or None when none is reachable."""
        cut = bool(snapshot.badges & 2) and any(15 in mon.moves for mon in snapshot.party)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        choices = []
        for mid, entry in self.data.maps.items():
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            if entry['region'] != self.travel_region(snapshot):
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.walk(snapshot, mid)
            if route is None:
                continue
            nurse =next(obj for obj in entry['objects'] if obj['sprite'] == 'SPRITE_NURSE')
            # The walk from Route 44 to Blackthorn City goes through Ice Path, where healing stands down.
            # The trip would step into the cave, hand back to the main goal, step out and choose the same
            # center again. So a known walk must stay out of Ice Path. With no walk known yet, the map
            # walk decides alone.
            walk = self.nav.regions.route(snapshot, mid, [(nurse['x'], nurse['y'] + 2)], cut=cut, surf=surf)
            if walk is None or not any(
                    self.data.maps[step[1][0]]['constant'].startswith('ICE_PATH_') for step in walk):
                choices.append((len(route), mid, nurse))
        if not choices:
            return None
        # Keep to the center already chosen while it stays reachable, so the trip does not switch halfway.
        _, mid, nurse = next((choice for choice in choices if choice[1] == self.heal.map), min(choices))
        return mid, nurse

    TALK_STALL_FRAMES = 80
    TALK_FAIL_FRAMES = 110

    def talk_progress(self, snapshot):
        """Count conversation decisions in which nothing the player owns or stands on has changed.

        A long run means A is repeating a dialogue loop, such as a clerk offering the same purchase
        again. Drop any shopping errand, back out with B, and in the end report the failure.
        """
        key = (snapshot.map, snapshot.x, snapshot.y, snapshot.money, tuple(snapshot.items))
        if key != self.talk_key:
            self.talk_key, self.talk_frames = key, 0
            return False
        self.talk_frames += 1
        if self.talk_frames < self.TALK_STALL_FRAMES:
            return False
        if self.talk_frames == self.TALK_STALL_FRAMES:
            self.shop.drop()
            if self.interaction in ('buy_balls', 'sell_supplies'):
                self.interaction = None
        if self.talk_frames >= self.TALK_FAIL_FRAMES:
            self.talk_frames = 0
            self.fail(f'A conversation in {snapshot.map_name} made no progress')
            return False
        return True
