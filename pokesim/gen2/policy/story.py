"""Pick the Generation II story goal and answer the prompts on the way."""
from __future__ import annotations

import re

from ..navigation import DIRS
from ..puzzles import push_plan
from ..kanto import journey as kanto_journey
from ..menus import menu_label
from .state import Goal


class StoryPart:
    """The journey and story goals, boulder puzzles and story prompts."""

    def journey(self, snapshot, mem):
        """The journey goal: the story goal, or the boss training it needs. Both are offered on the step's
        ballot, or outside a step on a ballot of their own, and the ballot's pick is the journey goal. Once
        the story is done, every collection rung offers its own goal (collection.Rungs)."""
        ballot = getattr(self, 'ballot', None)
        if ballot is None:
            from ..pipeline import Ballot
            ballot = Ballot()
        goal = self.story(snapshot, mem)
        if goal is not None:
            site = self.story_site(goal)
            if site == 'rung':
                ballot.extend(self.collection_offers, self.collection_pinned)
            else:
                ballot.offer(goal, site, self.story_candidate(goal, site))
        training = self.boss_training(snapshot, goal)
        if training is not None:
            ballot.offer(training, 'boss', self.story_candidate(training, 'boss'))
        return ballot.goal

    def story_site(self, goal):
        """The site of this decision's story goal ``goal``: an activity under way that holds the collection,
        the collection's rungs, or else the story."""
        if getattr(self, 'collection_decision', None) != self.decisions:
            return 'story'
        if getattr(self, 'ladder_hold', None) is not None:
            return 'holds'
        return 'rung' if goal is getattr(self, 'collection_goal', None) else 'story'

    def story_candidate(self, goal, kind):
        """``goal`` priced as a story goal, in the story tier until Red falls and in the progress tier
        after, as Gen I prices its story until the Champion falls."""
        from ...planning.arbiter import Tier
        from ..pipeline import story_candidate
        return story_candidate(goal, kind, Tier.PROGRESS if 'red' in self.completed else Tier.STORY)

    def story(self, snapshot, mem):
        # A saved postgame outing waits while an evolution, trade or other collection task takes
        # priority. Its battle rules resume only when the director chooses its hunting goal again.
        activity = (self.collection.get('postgame') or {}).get('activity')
        if activity:
            activity['suspended'] = True
        if snapshot.map == self.data.map_ids['POKECENTER_2F']:
            return Goal('return_from_cable', 'Return downstairs after the Cable Club', 'POKECENTER_2F', 0, 7)
        if self.collection.get('time_capsule_restore'):
            from ..teams import assemble
            goal = assemble(self, snapshot, self.collection['time_capsule_restore'], Goal,
                            'Restore the adventure team after the Time Capsule')
            if goal:
                return goal
            self.collection.pop('time_capsule_restore', None)
        if self.collection.get('tower'):
            from ..tower import journey
            goal = journey(self, snapshot, Goal)
            if goal:
                return goal
        if self.collection.get('contest'):
            from ..contest import journey
            goal = journey(self, snapshot, Goal)
            if goal:
                return goal
        if not snapshot.event('EVENT_GOT_A_POKEMON_FROM_ELM'):
            x = {'cyndaquil': 6, 'totodile': 7, 'chikorita': 8}[self.starter]
            return Goal('starter', f'Choose {self.starter.title()}', 'ELMS_LAB', x, 4, 'up')
        self.completed.setdefault('starter', snapshot.frame)
        if not snapshot.event('EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON'):
            return Goal('mystery_egg', 'Visit Mr. Pokémon', 'MR_POKEMONS_HOUSE', 3, 6, 'up')
        self.completed.setdefault('mystery_egg', snapshot.frame)
        if not snapshot.event('EVENT_GAVE_MYSTERY_EGG_TO_ELM'):
            if not snapshot.event('EVENT_COP_IN_ELMS_LAB'):
                return Goal('officer', 'Tell the officer about the rival', 'ELMS_LAB', 4, 5)
            return Goal('deliver_egg', 'Bring the mystery egg to Elm', 'ELMS_LAB', 5, 3, 'up')
        self.completed.setdefault('deliver_egg', snapshot.frame)
        if not snapshot.badges & 1:
            return Goal('zephyr', 'Challenge Falkner', 'VIOLET_GYM', 5, 2, 'up')
        self.completed.setdefault('zephyr', snapshot.frame)
        if not snapshot.event('EVENT_GOT_TOGEPI_EGG_FROM_ELMS_AIDE'):
            from ..quests import room_for_gift
            room = room_for_gift(self, snapshot, Goal)
            if room:
                return room
            return Goal('togepi', 'Receive Elm’s egg', 'VIOLET_POKECENTER_1F', 4, 4, 'up')
        self.completed.setdefault('togepi', snapshot.frame)
        if not snapshot.event('EVENT_CLEARED_SLOWPOKE_WELL'):
            if not snapshot.event('EVENT_AZALEA_TOWN_SLOWPOKETAIL_ROCKET'):
                return Goal('kurt', 'Help Kurt rescue the Slowpoke', 'KURTS_HOUSE', 3, 3, 'up')
            return Goal('slowpoke', 'Drive Team Rocket out of the well', 'SLOWPOKE_WELL_B1F', 5, 3, 'up')
        self.completed.setdefault('slowpoke', snapshot.frame)
        if not snapshot.badges & 2:
            return Goal('hive', 'Challenge Bugsy', 'AZALEA_GYM', 5, 8, 'up')
        self.completed.setdefault('hive', snapshot.frame)
        if not snapshot.event('EVENT_HERDED_FARFETCHD'):
            if 'wFarfetchdPosition' in self.data.symbols:
                position = mem.byte('wFarfetchdPosition') or 1
            else:
                forest = self.data.maps[self.data.map_ids['ILEX_FOREST']]
                position = next((int(obj['script'].removeprefix('FarfetchdPosition'))
                                 for obj in forest['objects'] if obj['script'].startswith('FarfetchdPosition')
                                 and not snapshot.event(obj['event'])), 1)
            points = {1: (14, 32, 'up'), 2: (15, 24, 'down'), 3: (20, 25, 'up'),
                      4: (29, 21, 'down'), 5: (29, 31, 'left'), 6: (24, 36, 'up'),
                      7: (22, 32, 'up'), 8: (15, 28, 'down'), 9: (11, 35, 'left')}
            x, y, face = points.get(position, points[1])
            return Goal(f'farfetchd_{position}', 'Return the lost Farfetch’d', 'ILEX_FOREST', x, y, face)
        if not snapshot.event('EVENT_GOT_HM01_CUT'):
            return Goal('cut', 'Receive Cut from the charcoal maker', 'ILEX_FOREST', 5, 29, 'up')
        self.completed.setdefault('cut', snapshot.frame)
        if not snapshot.badges & 4:
            if snapshot.event('EVENT_MADE_WHITNEY_CRY'):
                return Goal('whitney_cry', 'Give Whitney a moment', 'GOLDENROD_GYM', 8, 5)
            return Goal('plain', 'Challenge Whitney', 'GOLDENROD_GYM', 8, 4, 'up')
        self.completed.setdefault('plain', snapshot.frame)
        if not snapshot.event('EVENT_GOT_SQUIRTBOTTLE'):
            if self.data.game == 'crystal':
                if not snapshot.event('EVENT_MET_FLORIA'):
                    return self.person(snapshot, 'floria', 'Ask Floria about the moving tree', 'ROUTE_36', 'Route36FloriaScript')
                if not snapshot.event('EVENT_TALKED_TO_FLORIA_AT_FLOWER_SHOP'):
                    return self.person(snapshot, 'floria_shop', 'Visit Floria at the flower shop', 'GOLDENROD_FLOWER_SHOP', 'FlowerShopFloriaScript')
            return self.person(snapshot, 'squirtbottle', 'Borrow the SquirtBottle', 'GOLDENROD_FLOWER_SHOP', 'FlowerShopTeacherScript')
        # The tree also stands again after a fled battle or a walking return.
        if not snapshot.event('EVENT_FOUGHT_SUDOWOODO'):
            return Goal('sudowoodo', 'Investigate the moving tree', 'ROUTE_36', 35, 10, 'up')
        if not snapshot.event('EVENT_ROUTE_36_SUDOWOODO'):
            # The tree stands again after a fled battle or a walking return.
            goal = self.returned_encounter(snapshot, Goal, 'Sudowoodo')
            if goal is not None:
                return goal or Goal('sudowoodo', 'Investigate the moving tree', 'ROUTE_36', 35, 10, 'up')
        self.completed.setdefault('sudowoodo', snapshot.frame)
        if self.data.game == 'crystal' and not snapshot.event('EVENT_RELEASED_THE_BEASTS'):
            if not snapshot.event('EVENT_HOLE_IN_BURNED_TOWER'):
                return Goal('burned_tower', 'Explore the Burned Tower', 'BURNED_TOWER_1F', 11, 9)
            return Goal('beasts', 'Discover the tower’s sleeping Pokémon', 'BURNED_TOWER_B1F', 10, 6)
        if self.data.game == 'crystal' and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER'):
            return self.person(snapshot, 'eusine', 'Talk with Eusine after the beasts awaken',
                               'BURNED_TOWER_B1F', 'BurnedTowerB1FEusine')
        if not snapshot.event('EVENT_GOT_HM03_SURF'):
            for name in ('NAOKO', 'SAYO', 'ZUKI', 'KUNI', 'MIKI'):
                if not snapshot.event(f'EVENT_BEAT_KIMONO_GIRL_{name}'):
                    return self.person(snapshot, f'kimono_{name.lower()}', 'Challenge the Kimono Girls',
                                       'DANCE_THEATER', 'TrainerKimonoGirl' + name.title())
            return self.person(snapshot, 'surf', 'Receive Surf', 'DANCE_THEATER', 'DanceTheaterSurfGuy')
        self.completed.setdefault('surf', snapshot.frame)
        if not snapshot.badges & 8:
            return Goal('fog', 'Challenge Morty', 'ECRUTEAK_GYM', 5, 2, 'up')
        self.completed.setdefault('fog', snapshot.frame)
        if not snapshot.event('EVENT_GOT_HM04_STRENGTH'):
            return self.person(snapshot, 'strength', 'Receive Strength', 'OLIVINE_CAFE', 'OlivineCafeStrengthSailorScript')
        partner = self.partner_goal(snapshot, 57)
        if partner:
            return partner
        if not snapshot.event('EVENT_JASMINE_EXPLAINED_AMPHYS_SICKNESS'):
            return self.person(snapshot, 'amphy', 'Help Jasmine at the lighthouse', 'OLIVINE_LIGHTHOUSE_6F', 'OlivineLighthouseJasmine')
        if not snapshot.event('EVENT_GOT_SECRETPOTION_FROM_PHARMACY'):
            return self.person(snapshot, 'medicine', 'Get medicine for Amphy', 'CIANWOOD_PHARMACY', 'CianwoodPharmacist')
        if not snapshot.badges & 32:
            if snapshot.map == self.data.map_ids['CIANWOOD_GYM']:
                entry = self.data.maps[snapshot.map]
                live = {index: (x, y) for index, x, y in snapshot.objects}
                for point, stand, face in [((3, 7), (3, 8), 'up'), ((5, 7), (5, 8), 'up'), ((4, 7), (5, 7), 'left')]:
                    index = next(i for i, obj in enumerate(entry['objects'], 1)
                                 if obj['sprite'] == 'SPRITE_BOULDER' and (obj['x'], obj['y']) == point)
                    if live.get(index, point) == point:
                        return Goal(f'push_{point}', 'Move the gym boulders with Strength', 'CIANWOOD_GYM', *stand, face)
            return self.person(snapshot, 'storm', 'Challenge Chuck', 'CIANWOOD_GYM', 'CianwoodGymChuckScript')
        self.completed.setdefault('storm', snapshot.frame)
        if not snapshot.event('EVENT_GOT_HM02_FLY'):
            return self.person(snapshot, 'fly', 'Receive Fly from Chuck’s wife', 'CIANWOOD_CITY', 'CianwoodCityChucksWife')
        if not snapshot.event('EVENT_JASMINE_RETURNED_TO_GYM'):
            return self.person(snapshot, 'heal_amphy', 'Deliver Amphy’s medicine', 'OLIVINE_LIGHTHOUSE_6F', 'OlivineLighthouseJasmine')
        if not snapshot.badges & 16:
            return Goal('mineral', 'Challenge Jasmine', 'OLIVINE_GYM', 5, 4, 'up')
        self.completed.setdefault('mineral', snapshot.frame)
        if not snapshot.event('EVENT_LAKE_OF_RAGE_RED_GYARADOS'):
            return Goal('red_gyarados', 'Investigate the red Gyarados', 'LAKE_OF_RAGE', 18, 23, 'up')
        if not snapshot.event('EVENT_DECIDED_TO_HELP_LANCE'):
            return self.person(snapshot, 'lance', 'Help Lance investigate Team Rocket', 'LAKE_OF_RAGE', 'LakeOfRageLanceScript')
        if not snapshot.event('EVENT_UNCOVERED_STAIRCASE_IN_MAHOGANY_MART'):
            return Goal('hideout_entrance', 'Find Team Rocket’s hideout', 'MAHOGANY_MART_1F', 4, 5)
        if not snapshot.event('EVENT_CLEARED_ROCKET_HIDEOUT'):
            if not snapshot.event('EVENT_TURNED_OFF_SECURITY_CAMERAS'):
                return Goal('security', 'Disable the hideout security cameras', 'TEAM_ROCKET_BASE_B1F', 19, 12, 'up')
            for event, key, script in [('EVENT_LEARNED_SLOWPOKETAIL', 'password_one', 'SlowpokeTailGrunt'),
                                       ('EVENT_LEARNED_RATICATE_TAIL', 'password_two', 'RaticateTailGrunt')]:
                if not snapshot.event(event):
                    return self.person(snapshot, key, 'Find the hideout passwords', 'TEAM_ROCKET_BASE_B3F', script)
            if not snapshot.event('EVENT_OPENED_DOOR_TO_GIOVANNIS_OFFICE'):
                return Goal('office_door', 'Open the executive’s office', 'TEAM_ROCKET_BASE_B3F', 10, 10, 'up')
            if not snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEM_4'):
                return Goal('executive', 'Challenge the Rocket executive', 'TEAM_ROCKET_BASE_B3F', 10, 8)
            if not snapshot.event('EVENT_LEARNED_HAIL_GIOVANNI'):
                return self.person(snapshot, 'murkrow', 'Learn the transmitter password', 'TEAM_ROCKET_BASE_B3F', 'RocketBaseMurkrow')
            if not snapshot.event('EVENT_OPENED_DOOR_TO_ROCKET_HIDEOUT_TRANSMITTER'):
                return Goal('transmitter_door', 'Open the transmitter room', 'TEAM_ROCKET_BASE_B2F', 14, 13, 'up')
            for number in range(1, 4):
                if not snapshot.event(f'EVENT_TEAM_ROCKET_BASE_B2F_ELECTRODE_{number}'):
                    return self.person(snapshot, f'electrode_{number}', 'Stop the radio transmitter',
                                       'TEAM_ROCKET_BASE_B2F', f'RocketElectrode{number}')
            return Goal('hideout_done', 'Finish helping Lance', 'TEAM_ROCKET_BASE_B2F', 7, 10)
        self.completed.setdefault('rocket_hideout', snapshot.frame)
        if not snapshot.badges & 64:
            return Goal('glacier', 'Challenge Pryce', 'MAHOGANY_GYM', 5, 4, 'up')
        self.completed.setdefault('glacier', snapshot.frame)
        if not snapshot.event('EVENT_CLEARED_RADIO_TOWER'):
            if not snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEM_3'):
                return Goal('fake_director', 'Find the Radio Tower director', 'RADIO_TOWER_5F', 0, 3)
            if not snapshot.event('EVENT_USED_BASEMENT_KEY'):
                return Goal('basement_key', 'Unlock the underground passage', 'GOLDENROD_UNDERGROUND', 18, 7, 'up')
            if not snapshot.event('EVENT_RECEIVED_CARD_KEY'):
                if snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_WAREHOUSE']:
                    return self.person(snapshot, 'card_key', 'Rescue the Radio Tower director',
                                       'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GoldenrodUndergroundWarehouseDirectorScript')
                if (snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES']
                        and snapshot.x >= 20 and 7 <= snapshot.y < 14
                        and not snapshot.event('EVENT_EMERGENCY_SWITCH')):
                    return Goal('emergency_switch', 'Open the underground emergency exit',
                                'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
                for number, x in [(3, 2), (2, 10), (1, 16)]:
                    if not snapshot.event(f'EVENT_SWITCH_{number}'):
                        return Goal(f'switch_{number}', 'Open the underground shutters',
                                    'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', x, 2, 'up')
                return self.person(snapshot, 'card_key', 'Rescue the Radio Tower director',
                                   'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GoldenrodUndergroundWarehouseDirectorScript')
            if snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_WAREHOUSE']:
                return Goal('warehouse_exit', 'Leave the underground warehouse',
                            'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
            if (snapshot.map == self.data.map_ids['GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES']
                    and snapshot.x >= 20 and 7 <= snapshot.y < 14 and not snapshot.event('EVENT_EMERGENCY_SWITCH')):
                return Goal('emergency_exit', 'Open the underground exit',
                            'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES', 20, 12, 'up')
            if not snapshot.event('EVENT_USED_THE_CARD_KEY_IN_THE_RADIO_TOWER'):
                return Goal('card_key_slot', 'Open the Radio Tower shutter', 'RADIO_TOWER_3F', 14, 3, 'up')
            return Goal('radio_tower', 'Free the Radio Tower', 'RADIO_TOWER_5F', 16, 5)
        self.completed.setdefault('radio_tower', snapshot.frame)
        partner = self.partner_goal(snapshot, 250)
        if partner:
            return partner
        if not snapshot.event('EVENT_GOT_HM07_WATERFALL'):
            return self.person(snapshot, 'waterfall', 'Find Waterfall in the Ice Path', 'ICE_PATH_1F', 'IcePath1FHMWaterfall')
        for number in range(1, 5):
            if not snapshot.event(f'EVENT_BOULDER_IN_ICE_PATH_{number}'):
                if snapshot.map != self.data.map_ids['ICE_PATH_B1F']:
                    return Goal('ice_boulders', 'Clear a route through the Ice Path', 'ICE_PATH_B1F', 3, 14)
                goal = self.boulder(snapshot, mem, 'ICE_PATH_B1F', f'EVENT_BOULDER_IN_ICE_PATH_{number}', number + 2)
                if goal:
                    return goal
        if snapshot.map == self.data.map_ids['BLACKTHORN_CITY']:
            self.completed.setdefault('ice_path', snapshot.frame)
        if ('ice_path' not in self.completed or not snapshot.event('EVENT_BEAT_CLAIR')
                and self.constant(snapshot).startswith('ICE_PATH_')):
            name = self.constant(snapshot)
            if name == 'ICE_PATH_B2F_MAHOGANY_SIDE':
                return Goal('ice_crossing', 'Cross the frozen cavern', 'ICE_PATH_B3F', 3, 5)
            if name == 'ICE_PATH_B3F':
                return Goal('ice_lower', 'Continue toward Blackthorn', 'ICE_PATH_B2F_BLACKTHORN_SIDE', 3, 4)
            if name == 'ICE_PATH_B2F_BLACKTHORN_SIDE':
                return Goal('ice_climb', 'Climb toward the Ice Path exit', 'ICE_PATH_B1F', 11, 26)
            if name == 'ICE_PATH_B1F' and snapshot.y > 20:
                return Goal('ice_exit_corridor', 'Find the Ice Path exit', 'ICE_PATH_1F', 37, 14)
            if name == 'ICE_PATH_1F' and snapshot.x > 30 and snapshot.y >= 13:
                return Goal('blackthorn', 'Arrive in Blackthorn City', 'BLACKTHORN_CITY', 36, 10)
            if name == 'ICE_PATH_1F':
                return Goal('ice_stairs', 'Reach the frozen cavern stairs', 'ICE_PATH_B1F', 3, 14)
            return Goal('ice_descent', 'Descend into the frozen cavern', 'ICE_PATH_B2F_MAHOGANY_SIDE', 17, 2)
        if not snapshot.event('EVENT_BEAT_CLAIR'):
            for number, warp in [(3, 4), (2, 3), (1, 5)]:
                if not snapshot.event(f'EVENT_BOULDER_IN_BLACKTHORN_GYM_{number}'):
                    if snapshot.map != self.data.map_ids['BLACKTHORN_GYM_2F']:
                        return Goal('gym_boulders', 'Prepare a route to Clair', 'BLACKTHORN_GYM_2F', 7, 9)
                    goal = self.boulder(snapshot, mem, 'BLACKTHORN_GYM_2F', f'EVENT_BOULDER_IN_BLACKTHORN_GYM_{number}', warp)
                    if goal:
                        return goal
            return self.person(snapshot, 'clair', 'Challenge Clair', 'BLACKTHORN_GYM_1F', 'BlackthornGymClairScript')
        if not snapshot.badges & 128:
            if self.data.game == 'crystal':
                return self.person(snapshot, 'rising', 'Complete the Dragon Master’s test', 'DRAGON_SHRINE', 'DragonShrineElder1Script')
            return self.person(snapshot, 'rising', 'Find the Dragon Fang', 'DRAGONS_DEN_B1F', 'DragonsDenB1FDragonFangScript')
        self.completed.setdefault('rising', snapshot.frame)
        partner = self.partner_goal(snapshot, 127)
        if partner:
            return partner
        if not snapshot.hall_of_fame_count:
            rooms = [('WILL', 'WILLS_ROOM', 'WillScript_Battle'), ('KOGA', 'KOGAS_ROOM', 'KogaScript_Battle'),
                     ('BRUNO', 'BRUNOS_ROOM', 'BrunoScript_Battle'), ('KAREN', 'KARENS_ROOM', 'KarenScript_Battle')]
            for name, room, script in rooms:
                if not snapshot.event(f'EVENT_BEAT_ELITE_4_{name}'):
                    return self.person(snapshot, f'league_{name.lower()}', f'Challenge {name.title()}', room, script)
            if not snapshot.event('EVENT_BEAT_CHAMPION_LANCE'):
                return self.person(snapshot, 'league_lance', 'Challenge Champion Lance', 'LANCES_ROOM', 'LancesRoomLanceScript')
            return Goal('hall_of_fame', 'Enter the Hall of Fame', 'HALL_OF_FAME', 4, 7)
        self.completed.setdefault('champion', snapshot.frame)
        return kanto_journey(self, snapshot, mem, Goal)

    def boulder(self, snapshot, mem, map_name, event, warp):
        if self.resetting_puzzle == snapshot.map:
            return self.reset_puzzle_goal(map_name)
        entry = self.data.maps[snapshot.map]
        known = self.nav.objects.setdefault(snapshot.map, {})
        active = [(index, obj) for index, obj in enumerate(entry['objects'], 1)
                  if obj['sprite'] == 'SPRITE_BOULDER'
                  and not (obj['event'] in self.data.events and snapshot.event(obj['event']))]
        target = next((i for i, (_, obj) in enumerate(active) if obj['event'] == event), None)
        if target is None:
            return None
        positions = tuple(known.get(index, (obj['x'], obj['y'])) for index, obj in active)
        landing = entry['warps'][warp - 1]
        hole = (landing['x'], landing['y'])
        obstacles = tuple(known.get(index, (obj['x'], obj['y'])) for index, obj in enumerate(entry['objects'], 1)
                          if obj['sprite'] != 'SPRITE_BOULDER' and obj['kind'] != 'OBJECTTYPE_ITEMBALL'
                          and not (obj['event'] in self.data.events and snapshot.event(obj['event'])))
        key = (snapshot.map, positions, target, obstacles)
        if key not in self.puzzle_cache:
            grid = self.nav.collision(snapshot, mem.memory)
            plan = push_plan(grid, entry['width'], entry['height'], self.data.permissions,
                             (snapshot.x, snapshot.y), positions, target, hole, obstacles=obstacles)
            self.puzzle_cache[key] = plan
            predicted = list(positions)
            for offset, (stand, direction) in enumerate(plan or []):
                dx, dy = DIRS[direction]
                stone = (stand[0] + dx, stand[1] + dy)
                index = predicted.index(stone)
                predicted[index] = (stone[0] + dx, stone[1] + dy)
                self.puzzle_cache[(snapshot.map, tuple(predicted), target, obstacles)] = plan[offset + 1:]
        plan = self.puzzle_cache[key]
        if plan:
            stand, direction = plan[0]
            return Goal(f'push_{event}', 'Push a boulder into the opening', map_name, *stand, direction)
        self.puzzle_cache.clear()
        self.resetting_puzzle = snapshot.map
        return self.reset_puzzle_goal(map_name)

    def reset_puzzle_goal(self, map_name):
        if map_name == 'ICE_PATH_B1F':
            return Goal('reset_ice', 'Reset the boulder arrangement', 'ICE_PATH_1F', 37, 4)
        return Goal('reset_gym', 'Reset the boulder arrangement', 'BLACKTHORN_GYM_1F', 7, 7)

    def needed_move(self, snapshot):
        if self.partner_move is not None:
            if not any(not mon.egg and self.partner_move in self.data.species[mon.species]['machines'] for mon in snapshot.party):
                return self.partner_move
            self.partner_move = None
        return 127 if snapshot.badges & 128 else 250 if snapshot.badges & 64 else 57

    def partner_goal(self, snapshot, move, shore=None):
        """The goal that fetches a partner for ``move``, or None. ``shore`` is the move whose shore a fishing
        trip picks, the move the partner is wanted for so far by default."""
        if any(not mon.egg and move in self.data.species[mon.species]['machines'] for mon in snapshot.party):
            return None
        if self.no_room(snapshot):
            # A full team, every box full and no spare to release leave nowhere to put a team member
            # down, so a partner can be neither withdrawn nor caught. A trade that sends the partner
            # away can leave the run here; visiting the PC would only fail to deposit forever.
            return None
        candidates = [mon for mon in snapshot.stored if not mon.egg
                      and move in self.data.species[mon.species]['machines']]
        if len(snapshot.party) == 6 or candidates:
            return self.storage_goal(snapshot)
        if not snapshot.event('EVENT_GOT_GOOD_ROD'):
            return self.person(snapshot, 'good_rod', 'Get a fishing rod', 'OLIVINE_GOOD_ROD_HOUSE', 'GoodRodGuru')
        return self.fishing(snapshot, shore)

    # Prompts where the adventure should answer YES at once, and prompts it must always decline.
    YES_PROMPTS = re.compile(r'HEAL')
    NO_PROMPTS = re.compile(r'MONEY|SAVE|CALL|PHONE|REGISTER|NUMBER')
    NO_LIMIT = 3

    def unknown_yes_no(self, snapshot):
        """Decline YES or NO prompts the policy has no plan for, instead of mashing A into YES.

        Mom's savings and phone calls both ask YES or NO in the overworld. A prompt that
        keeps coming back after repeated refusals is one the story needs, so it gets a YES.
        """
        rows = snapshot.tiles
        yes = next((i for i, row in enumerate(rows[:12]) if menu_label(row) == 'YES'), None)
        if yes is None or yes + 1 >= 12 or menu_label(rows[yes + 1]) != 'NO' or '▶' not in rows[yes] + rows[yes + 1]:
            return None
        question = ' '.join(' '.join(rows[13:]).upper().split())
        if self.NO_PROMPTS.search(question):
            return 'b'
        if self.YES_PROMPTS.search(question):
            return None
        count = self.refusals.get(question, 0)
        if count >= self.NO_LIMIT:
            self.refusals.clear()
            return None
        if len(self.refusals) > 32:
            self.refusals.clear()
        self.refusals[question] = count + 1
        return 'b'

    def constant(self, snapshot):
        """Map constant, or an empty name before the game has loaded a real map."""
        return self.data.maps.get(snapshot.map, {}).get('constant', '')

    def travel_region(self, snapshot):
        name = self.constant(snapshot)
        if ((name == 'TOHJO_FALLS' and snapshot.x < 20 or name == 'ROUTE_27' and snapshot.x < 32)
                and not any(127 in mon.moves for mon in snapshot.party)):
            return self.data.maps[self.data.map_ids['NEW_BARK_TOWN']]['region']
        return self.data.maps[snapshot.map]['region']

    def returned_encounter(self, snapshot, Goal, name):
        """Prepare for a one-time encounter that came back: a storage goal, False to go now, None to wait."""
        if self.in_league(snapshot) or self.in_transmitter_room(snapshot):
            # The League rooms only lead forward, so finish the run before going back for it.
            return None
        if not snapshot.can_catch:
            if self.no_room(snapshot):
                return None
            goal = self.storage_goal(snapshot)
            return Goal('collection_box', f'Make room for {name}', goal.map_name, goal.x, goal.y, goal.face)
        master = self.data.items['MASTER_BALL']
        # The Master Ball stays reserved for legendaries, and a battle without a ball only knocks it out.
        return False if any(item != master and count for item, count in snapshot.pockets['balls']) else None
