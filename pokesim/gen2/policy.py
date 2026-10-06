"""Observe and act through cartridge controls for Generation II adventures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import random
import re

from .navigation import DIRS, Navigator
from .ram import Memory
from .puzzles import push_plan
from .world import update as update_world
from .naming import Naming
from .kanto import journey as kanto_journey
from .menus import Buy, ChangeBox, DayCare, FieldMove, Fly, Give, Take, Lead, Radio, Forget, Remedy, Sell, ShowPartner, Storage, Teach, Use, choose


@dataclass(frozen=True)
class Action:
    button: str | None = None
    hold: int = 8
    gap: int = 16


@dataclass(frozen=True)
class Goal:
    key: str
    label: str
    map_name: str
    x: int
    y: int
    face: str | None = None


class Policy:
    name = 'strategic'

    def __init__(self, data, *, seed=None, starter='random'):
        self.data = data
        self.rng = random.Random(seed)
        self.starter = self.rng.choice(('chikorita', 'cyndaquil', 'totodile')) if starter == 'random' else starter
        if self.starter not in {'chikorita', 'cyndaquil', 'totodile'}:
            raise ValueError('Choose Chikorita, Cyndaquil or Totodile for this cartridge')
        self.nav = Navigator(data)
        self.decisions = 0
        self.mode = 'opening'
        self.goal = None
        self.menu = None
        self.shopping = None
        self.shop_location = None
        self.healing_map = None
        self.completed = {}
        self.collection = {'target': None, 'attempts': {}}
        self.demand = {}
        self.naming = Naming(seed)
        self.learning = False
        self.switching = None
        self.partner_move = None
        self.last_position = None
        self.same_position = 0
        self.interaction = None
        self.puzzle_cache = {}
        self.memory = None
        self.resetting_puzzle = None

    def state_dict(self):
        return {'starter': self.starter, 'completed': self.completed, 'collection': self.collection, 'demand': self.demand, 'decisions': self.decisions,
                'naming': self.naming.state_dict(), 'learning': self.learning, 'switching': self.switching, 'partner_move': self.partner_move,
                'menu': {'kind': type(self.menu).__name__, 'state': asdict(self.menu)} if self.menu else None,
                'shopping': self.shopping, 'shop_location': self.shop_location, 'healing_map': self.healing_map,
                'interaction': self.interaction, 'resetting_puzzle': self.resetting_puzzle,
                'objects': {str(mid): {str(index): point for index, point in objects.items()}
                            for mid, objects in self.nav.objects.items()}}

    def load_state_dict(self, state):
        self.starter = state.get('starter', self.starter)
        self.completed = state.get('completed', {})
        self.collection = state.get('collection', {'target': None, 'attempts': {}})
        self.demand = {int(key): value for key, value in state.get('demand', {}).items()}
        self.decisions = state.get('decisions', 0)
        self.naming.load_state_dict(state.get('naming', {}))
        self.learning = state.get('learning', False)
        self.switching = state.get('switching')
        self.partner_move = state.get('partner_move')
        menu = state.get('menu')
        kinds = {'ShowPartner': ShowPartner, 'Sell': Sell, 'Lead': Lead, 'DayCare': DayCare, 'FieldMove': FieldMove, 'Give': Give, 'Take': Take, 'Fly': Fly, 'Radio': Radio, 'ChangeBox': ChangeBox, 'Buy': Buy, 'Teach': Teach, 'Use': Use, 'Storage': Storage, 'Forget': Forget, 'Remedy': Remedy}
        self.menu = kinds[menu['kind']](**menu['state']) if menu and menu.get('kind') in kinds else None
        self.shopping = tuple(state['shopping']) if state.get('shopping') else None
        self.shop_location = tuple(state['shop_location']) if state.get('shop_location') else None
        self.healing_map = state.get('healing_map')
        self.interaction = state.get('interaction')
        self.resetting_puzzle = state.get('resetting_puzzle')
        if isinstance(self.interaction, list):
            self.interaction = tuple(self.interaction)
        self.nav.objects = {int(mid): {int(index): tuple(point) for index, point in objects.items()}
                            for mid, objects in state.get('objects', {}).items()}

    def on_restore(self):
        objects = self.nav.objects
        self.nav = Navigator(self.data)
        self.nav.objects = objects

    def describe(self):
        return f'strategic ({self.mode})'

    def details(self):
        return {'action': self.mode, 'decisions': self.decisions, 'starter': self.starter,
                'milestones': dict(self.completed), 'visited_tiles': len(self.nav.visits),
                'objective': {'key': self.goal.key, 'label': self.goal.label, 'reason': self.goal.label} if self.goal else {},
                'collection': {'version': self.data.game, 'dex_total': 251,
                               'phase': self.collection.get('phase', 'journey'),
                               'hunting': (self.collection.get('target') or {}).get('species')},
                'reason': self.goal.label if self.goal else 'Start the adventure'}

    def journey(self, snapshot, mem):
        if snapshot.map == self.data.map_ids['POKECENTER_2F']:
            return Goal('return_from_cable', 'Return downstairs after the Cable Club', 'POKECENTER_2F', 0, 7)
        if self.collection.get('time_capsule_restore'):
            from .teams import assemble
            goal = assemble(self, snapshot, self.collection['time_capsule_restore'], Goal,
                            'Restore the adventure team after the Time Capsule')
            if goal:
                return goal
            self.collection.pop('time_capsule_restore', None)
        if self.collection.get('tower'):
            from .tower import journey
            goal = journey(self, snapshot, Goal)
            if goal:
                return goal
        if self.collection.get('contest'):
            from .contest import journey
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
            from .quests import room_for_gift
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
        if not snapshot.event('EVENT_FOUGHT_SUDOWOODO'):
            return Goal('sudowoodo', 'Investigate the moving tree', 'ROUTE_36', 35, 10, 'up')
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
                and self.data.maps[snapshot.map]['constant'].startswith('ICE_PATH_')):
            name = self.data.maps[snapshot.map]['constant']
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
        known.update({index: (x, y) for index, x, y in snapshot.objects})
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

    def partner_goal(self, snapshot, move):
        if any(not mon.egg and move in self.data.species[mon.species]['machines'] for mon in snapshot.party):
            return None
        candidates = [mon for mon in snapshot.stored if not mon.egg
                      and move in self.data.species[mon.species]['machines']]
        if len(snapshot.party) == 6 or candidates:
            return self.storage_goal(snapshot)
        if not snapshot.event('EVENT_GOT_GOOD_ROD'):
            return self.person(snapshot, 'good_rod', 'Get a fishing rod', 'OLIVINE_GOOD_ROD_HOUSE', 'GoodRodGuru')
        return self.fishing(snapshot)

    def travel_region(self, snapshot):
        name = self.data.maps[snapshot.map]['constant']
        if ((name == 'TOHJO_FALLS' and snapshot.x < 20 or name == 'ROUTE_27' and snapshot.x < 32)
                and not any(127 in mon.moves for mon in snapshot.party)):
            return self.data.maps[self.data.map_ids['NEW_BARK_TOWN']]['region']
        return self.data.maps[snapshot.map]['region']

    def storage_goal(self, snapshot):
        choices = []
        for mid, entry in self.data.maps.items():
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            if entry['region'] != self.travel_region(snapshot):
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.route(snapshot.map, mid)
            if route is None:
                continue
            for index, tile in enumerate(entry['collision']):
                if tile == 0x93:
                    choices.append((len(route), mid, index % entry['width'], index // entry['width'] + 1))
        _, mid, x, y = min(choices)
        return Goal('storage', 'Prepare a place for a field move partner', self.data.maps[mid]['constant'], x, y, 'up')

    def fishing(self, snapshot):
        map_name = 'BLACKTHORN_CITY' if self.needed_move(snapshot) == 127 else 'OLIVINE_CITY'
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
                    if path is not None:
                        choices.append((len(path), x, y, face))
        _, x, y, face = min(choices)
        return Goal('fish_surf', 'Catch a partner for field moves', map_name, x, y, face)

    def person(self, snapshot, key, label, map_name, script):
        mid = self.data.map_ids[map_name]
        entry = self.data.maps[mid]
        matches = [(i, obj) for i, obj in enumerate(entry['objects'], 1) if obj['script'] == script]
        index, obj = next(((i, obj) for i, obj in matches
                           if obj['event'] not in self.data.events or not snapshot.event(obj['event'])), matches[0])
        x, y = next(((x, y) for i, x, y in snapshot.objects if i == index), (obj['x'], obj['y'])) if snapshot.map == mid else (obj['x'], obj['y'])
        grid = self.nav.collision(replace(snapshot, map=mid), self.memory if snapshot.map == mid else None)
        choices = []
        for face, (dx, dy) in DIRS.items():
            for distance in (1, 2):
                point = (x - dx * distance, y - dy * distance)
                if not (0 <= point[0] < entry['width'] and 0 <= point[1] < entry['height']):
                    continue
                if distance == 2 and grid[(y - dy) * entry['width'] + x - dx] not in (0x90, 0x98):
                    continue
                if not self.nav.passable(grid[point[1] * entry['width'] + point[0]]):
                    continue
                if snapshot.map == mid:
                    path = self.nav.local(snapshot, [point], self.memory)
                else:
                    paths = [self.nav.local(replace(snapshot, map=mid, x=warp['x'], y=warp['y'], objects=()), [point])
                             for warp in entry['warps'] if warp['map'] != mid]
                    path = min((path for path in paths if path is not None), key=len, default=None)
                if path is not None:
                    choices.append((len(path), point[0], point[1], face))
        if not choices:
            return Goal(key, label, map_name, x, y + 1, 'up')
        _, x, y, face = min(choices)
        return Goal(key, label, map_name, x, y, face)

    def in_league(self, snapshot):
        return self.data.maps[snapshot.map]['constant'] in {
            'WILLS_ROOM', 'KOGAS_ROOM', 'BRUNOS_ROOM', 'KARENS_ROOM', 'LANCES_ROOM', 'HALL_OF_FAME'}

    def in_transmitter_room(self, snapshot):
        return (snapshot.map == self.data.map_ids['TEAM_ROCKET_BASE_B2F']
                and snapshot.event('EVENT_BEAT_ROCKET_EXECUTIVEF_2')
                and not snapshot.event('EVENT_CLEARED_ROCKET_HIDEOUT'))

    def healing(self, snapshot):
        if (self.in_transmitter_room(snapshot) or self.in_league(snapshot)
                or self.data.maps[snapshot.map]['constant'].startswith('ICE_PATH_')
                or self.data.maps[snapshot.map]['constant'] in {
                    'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES'}):
            return None
        if (snapshot.map == self.data.map_ids['BURNED_TOWER_B1F']
                and (not snapshot.event('EVENT_RELEASED_THE_BEASTS') or self.data.game == 'crystal'
                     and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER'))):
            return None
        healthy = [mon for mon in snapshot.party if not mon.egg]
        if not healthy or not any(mon.hp < mon.max_hp * 0.6 or mon.status
                                  or (any(self.data.moves.get(move, {}).get('power', 0) for move in mon.moves)
                                      and not any(pp for move, pp in zip(mon.moves, mon.pp)
                                                  if self.data.moves.get(move, {}).get('power', 0)))
                                  for mon in healthy):
            self.healing_map = None
            return None
        choices = []
        for mid, entry in self.data.maps.items():
            if self.healing_map is not None and mid != self.healing_map:
                continue
            if not entry['constant'].endswith('POKECENTER_1F'):
                continue
            if entry['region'] != self.travel_region(snapshot):
                continue
            if entry['constant'] == 'BLACKTHORN_POKECENTER_1F' and 'ice_path' not in self.completed:
                continue
            route = self.nav.route(snapshot.map, mid)
            if route is not None:
                choices.append((len(route), mid))
        if not choices:
            return None
        _, mid = min(choices)
        self.healing_map = mid
        nurse = next(obj for obj in self.data.maps[mid]['objects'] if obj['sprite'] == 'SPRITE_NURSE')
        return Goal('heal', 'Restore the team at a Pokémon Center', self.data.maps[mid]['constant'],
                    nurse['x'], nurse['y'] + 2, 'up')

    def shop(self, snapshot):
        if (self.in_transmitter_room(snapshot) or self.in_league(snapshot)
                or self.data.maps[snapshot.map]['constant'].startswith('ICE_PATH_')
                or self.data.maps[snapshot.map]['constant'] in {'BLACKTHORN_GYM_1F', 'BLACKTHORN_GYM_2F',
                    'GOLDENROD_UNDERGROUND_WAREHOUSE', 'GOLDENROD_UNDERGROUND_SWITCH_ROOM_ENTRANCES'}):
            return None
        if (snapshot.map == self.data.map_ids['BURNED_TOWER_B1F']
                and (not snapshot.event('EVENT_RELEASED_THE_BEASTS') or self.data.game == 'crystal'
                     and not snapshot.event('EVENT_EUSINE_IN_BURNED_TOWER'))):
            return None
        if not snapshot.event('EVENT_GAVE_MYSTERY_EGG_TO_ELM'):
            self.shop_location = None
            return None
        inventory = dict(snapshot.items)
        if snapshot.money < 200:
            self.shop_location = None
            if snapshot.pockets['balls']:
                return None
            spare = next((self.data.items[name] for name in ('NUGGET', 'PEARL', 'BIG_PEARL', 'STARDUST', 'STAR_PIECE',
                          'TM50', 'TM31', 'TM45', 'TM30', 'TM49', 'TM32', 'TM16')
                          if inventory.get(self.data.items[name])), None)
            if spare is None:
                return None
            choices = []
            for mid, entry in self.data.maps.items():
                if entry['region'] != self.travel_region(snapshot):
                    continue
                for shop in entry['shops']:
                    goal = self.person(snapshot, 'sell_supplies', 'Sell a spare item for capture supplies', entry['constant'], shop['script'])
                    route = self.nav.regions.route(snapshot, mid, [(goal.x, goal.y)],
                                                  cut=bool(snapshot.badges & 2), surf=bool(snapshot.badges & 8))
                    if route is not None:
                        choices.append((len(route), mid, goal))
            if choices:
                self.shopping = (spare, inventory[spare])
                return min(choices, key=lambda row: row[:2])[-1]
            return None
        reserve = 400 if snapshot.money >= 1200 else 0
        from .breeding import retrieval_cost
        fees = retrieval_cost(self.data, snapshot)
        if fees:
            reserve = max(reserve, fees + 1000)
        requests = []
        ball_target = 20 if self.collection.get('phase') == 'legendary' else 4
        if sum(count for _, count in snapshot.pockets['balls']) < ball_target and snapshot.can_catch:
            names = ('ULTRA_BALL', 'GREAT_BALL', 'POKE_BALL') if snapshot.badges & 64 else ('POKE_BALL', 'GREAT_BALL', 'ULTRA_BALL')
            requests.append((names, 40 if ball_target == 20 else 20))
        if snapshot.badges & 64 and 'red' not in self.completed and (not snapshot.hall_of_fame_count or snapshot.badges == 65535):
            potions = ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION')
            count = sum(inventory.get(self.data.items[name], 0) for name in potions)
            if count < 8:
                requests.append((potions, 12 - count))
            if inventory.get(self.data.items['REVIVE'], 0) < 3:
                requests.append((('REVIVE',), 5 - inventory.get(self.data.items['REVIVE'], 0)))
        if not requests:
            self.shop_location = None
            return None
        choices = []
        for priority, (names, amount) in enumerate(requests):
            for mid, entry in self.data.maps.items():
                if entry['region'] != self.travel_region(snapshot):
                    continue
                if entry['constant'] == 'MAHOGANY_MART_1F':
                    continue
                if entry['constant'] == 'BLACKTHORN_MART' and 'ice_path' not in self.completed:
                    continue
                route = self.nav.route(snapshot.map, mid)
                if route is None or len(route) > 5 and (not self.shop_location or mid != self.shop_location[0]):
                    continue
                if 'ice_path' not in self.completed and any(self.data.maps[dest]['constant'].startswith('ICE_PATH_')
                                                             for _, dest, _, _ in route):
                    continue
                for shop in entry['shops']:
                    item = next((self.data.items[name] for name in names
                                 if self.data.items[name] in shop['items']
                                 and self.data.item_attributes[self.data.items[name]]['price'] <= snapshot.money - reserve), None)
                    if item:
                        goal = self.person(snapshot, 'buy_balls', 'Restock adventure supplies', entry['constant'], shop['script'])
                        walk = self.nav.regions.route(snapshot, mid, [(goal.x, goal.y)],
                            cut=bool(snapshot.badges & 2), surf=bool(snapshot.badges & 8))
                        if walk is None:
                            continue
                        choices.append((priority, 0 if self.shop_location == (mid, shop['script'], item) else 1,
                                        len(walk), mid, item, shop['script'], amount))
        if not choices:
            self.shop_location = None
            return None
        _, _, _, mid, item, script, amount = min(choices)
        self.shop_location = (mid, script, item)
        price = self.data.item_attributes[item]['price']
        self.shopping = (item, min(amount, (snapshot.money - reserve) // price))
        return self.person(snapshot, 'buy_balls', 'Restock adventure supplies', self.data.maps[mid]['constant'], script)

    def step(self, snapshot, memory):
        self.memory = memory
        self.decisions += 1
        mem = Memory(memory, self.data)
        from .ruins import control
        puzzle = control(snapshot, mem) if snapshot.started and snapshot.valid else None
        if puzzle:
            self.mode = 'Solve the Ruins of Alph picture puzzle'
            return Action(None, 0, 24) if puzzle == 'wait' else Action(puzzle, 6, 24)
        update_world(self.nav.regions, snapshot)
        naming = self.naming.step(snapshot, mem)
        if naming:
            self.mode = 'naming'
            return Action(naming, 6, 18)
        if snapshot.hall_of_fame_count and snapshot.map == self.data.map_ids['HALL_OF_FAME']:
            self.mode = 'Hall of Fame and credits'
            return Action('a', 8, 52)
        if not snapshot.started:
            self.mode = 'opening'
            return Action('start' if self.decisions % 20 == 1 else 'a', 8, 52)
        from .contest import control as contest_control
        contest_button = contest_control(self, snapshot, mem)
        if contest_button:
            self.mode = 'Catch a Bug-Catching Contest partner'
            return Action(contest_button, 8, 28)
        from .tower import control as tower_control
        tower_button = tower_control(self, snapshot, mem)
        if tower_button:
            self.mode = 'Choose the Battle Tower challenge'
            return Action(tower_button, 6, 26)
        if self.menu is None and not snapshot.in_battle and self.data.maps[snapshot.map]['constant'].endswith('POKECENTER_1F'):
            if 'TURN OFF' in snapshot.text:
                return Action(choose(snapshot.tiles, 'TURN OFF') or 'b', 8, 36)
            if 'CHANGE BOX' in snapshot.text or 'Choose a' in snapshot.text:
                return Action('b', 8, 36)
        if self.menu is None and snapshot.started and not snapshot.in_battle and ('CANCEL' in snapshot.text or 'PACK' in snapshot.text and 'SAVE' in snapshot.text or 'Teach ' in snapshot.text and 'POKéMON?' in snapshot.text):
            return Action('b', 8, 28)
        if isinstance(self.menu, Remedy):
            button = self.menu.step(snapshot, mem)
            if button:
                self.mode = 'Heal the team'
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
        if snapshot.in_battle:
            self.mode = 'battle'
            return self.battle(snapshot, mem)
        self.nav.observe(snapshot)
        if self.resetting_puzzle is not None and self.resetting_puzzle != snapshot.map:
            self.resetting_puzzle = None
        self.goal = self.journey(snapshot, mem)
        if isinstance(self.menu, Storage) and 'BOX is full' in snapshot.text:
            box = next((box for box, count in enumerate(snapshot.box_counts) if count < 20), None)
            if box is not None:
                self.menu = ChangeBox(box)
        if self.menu:
            button = self.menu.step(snapshot, mem)
            if button:
                labels = {Buy: 'Buy supplies', Sell: 'Sell a spare item', Storage: 'Manage Pokémon storage',
                          ChangeBox: 'Choose a receiving box', Use: 'Use an item', ShowPartner: 'Show a Pokémon',
                          DayCare: 'Manage the Day Care partners', Lead: 'Prepare the lead Pokémon',
                          Give: 'Give a held item', Take: 'Take a held item', Fly: 'Fly to the next destination',
                          FieldMove: 'Use a field move', Radio: 'Tune the radio', Teach: 'Teach a move'}
                self.mode = labels.get(type(self.menu), 'Manage the team')
                return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 28)
            self.menu = None
        if self.data.game == 'crystal' and snapshot.map == self.data.map_ids['DRAGON_SHRINE']:
            for label in ('Pal', 'Strategy', 'Anybody', 'Love', 'Both'):
                action = choose(snapshot.tiles, label, exact=True)
                if action:
                    return Action(action, 8, 28)
        if self.goal.key == 'radio_card' and 'YES' in snapshot.text and 'NO' in snapshot.text:
            negative = any(word in snapshot.text for word in ('FLASH', 'CHARMANDER', 'APRIKORN', 'MARIE'))
            return Action(choose(snapshot.tiles, 'NO' if negative else 'YES', exact=True) or 'a', 8, 28)
        # Textboxes cover the bottom six rows. Scripted walking is allowed to finish.
        if '┌' in snapshot.tiles[12] or mem.byte('wScriptRunning'):
            self.mode = 'conversation'
            return Action('a', 8, 36)
        strongest = max((i for i, mon in enumerate(snapshot.party) if not mon.egg),
                        key=lambda i: snapshot.party[i].level, default=0)
        if strongest and snapshot.party[strongest].level > snapshot.party[0].level + 5:
            mon = snapshot.party[strongest]
            self.menu = Lead(strongest, (mon.trainer_id, mon.dvs))
            return Action(None, 0, 24)
        for event, move in ([] if self.collection.get('tower') or self.collection.get('contest') or self.collection.get('time_capsule_restore') else [('EVENT_GOT_HM01_CUT', 15), ('EVENT_GOT_HM02_FLY', 19), ('EVENT_GOT_HM03_SURF', 57),
                            ('EVENT_GOT_HM04_STRENGTH', 70), ('EVENT_GOT_HM06_WHIRLPOOL', 250), ('EVENT_GOT_HM07_WATERFALL', 127)]):
            if snapshot.event(event) and not any(move in mon.moves for mon in snapshot.party):
                protected = {15, 19, 57, 70, 148, 250, 127}
                slot = min((i for i, mon in enumerate(snapshot.party)
                            if not mon.egg and move in self.data.species[mon.species]['machines']
                            and not all(known in protected for known in mon.moves)),
                           key=lambda i: (len(protected.intersection(snapshot.party[i].moves)), i), default=None)
                if slot is not None:
                    self.menu = Teach(move, slot)
                    return Action(None, 0, 24)
                compatible = [mon for mon in snapshot.party if not mon.egg
                              and move in self.data.species[mon.species]['machines']]
                if not compatible and move in {57, 250, 127}:
                    self.partner_move = move
                    self.goal = self.partner_goal(snapshot, move)
                    break
                if 'ice_path' in self.completed:
                    candidates = [i for i, mon in enumerate(snapshot.party) if not mon.egg
                                  and move in self.data.species[mon.species]['machines']]
                    if candidates:
                        self.goal = self.person(snapshot, f'delete_hm_{candidates[0]}', 'Make room for Waterfall',
                                                'MOVE_DELETERS_HOUSE', 'MoveDeleter')
                        break
        lead = snapshot.party[0] if snapshot.party else None
        if (lead and not lead.egg and snapshot.badges & 128 and self.data.items['TM23'] in dict(snapshot.items)
                and 231 in self.data.species[lead.species]['machines']
                and all(self.data.moves.get(move, {}).get('type', 0) in (0, 22) for move in lead.moves)):
            self.menu = Teach(231, 0)
            return Action(None, 0, 24)
        if self.in_league(snapshot) and self.remedy(snapshot):
            return Action(None, 0, 24)
        well_item = (self.goal.key == 'collection_trade_item'
                     and self.data.maps[snapshot.map]['constant'] in {'SLOWPOKE_WELL_B1F', 'SLOWPOKE_WELL_B2F'})
        if not self.goal.key.startswith('push_') and not well_item and (not self.collection.get('contest') or not mem.byte('wStatusFlags2') & 4):
            self.goal = self.healing(snapshot) or self.shop(snapshot) or self.goal
        target = self.data.map_ids[self.goal.map_name]
        from .flight import shortcut
        flight = shortcut(self, snapshot, mem, target)
        if flight:
            self.menu = flight
            self.mode = 'Fly to the next destination'
            return Action(None, 0, 24)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        path = self.nav.toward(snapshot, target, [(self.goal.x, self.goal.y)], memory, surf=surf)
        self.mode = self.goal.label
        if path:
            return self.walk(snapshot, memory, path)
        if path == []:
            if self.goal.key.startswith('collection_'):
                from .collection import arrive
                if self.goal.face and mem.byte('wPlayerDirection') & 12 != {'down': 0, 'up': 4, 'left': 8, 'right': 12}[self.goal.face]:
                    return Action(self.goal.face, 8, 16)
                button = arrive(self, snapshot)
                if button:
                    return Action(None, 0, 24) if button == 'wait' else Action(button, 8, 36)
            if self.goal.key == 'snorlax' and mem.byte('wMapMusic') != 0x40:
                self.menu = Radio()
                return Action(None, 0, 24)
            if self.goal.key.startswith('delete_hm_') and self.interaction == self.goal.key:
                slot = int(self.goal.key.rsplit('_', 1)[1])
                move = next((move for move in (15, 70, 250) if move in snapshot.party[slot].moves), snapshot.party[slot].moves[0])
                self.menu = Forget(slot, move)
                return Action('a', 8, 36)
            if self.goal.key == 'storage' and self.interaction == self.goal.key:
                candidates = [mon for mon in snapshot.stored if not mon.egg
                              and self.needed_move(snapshot) in self.data.species[mon.species]['machines']]
                box = (next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
                       if snapshot.box_counts[snapshot.active_box] == 20 else None)
                if len(snapshot.party) < 6 and candidates:
                    box = candidates[0].box if candidates[0].box != snapshot.active_box else None
                if box is not None:
                    self.menu = ChangeBox(box)
                elif len(snapshot.party) == 6:
                    protected = {15, 19, 57, 70, 148, 250, 127}
                    slot = min(range(1, len(snapshot.party)), key=lambda i:
                               (bool(protected.intersection(snapshot.party[i].moves)), snapshot.party[i].level))
                    self.menu = Storage('DEPOSIT', slot, len(snapshot.party))
                else:
                    mon = next(mon for mon in snapshot.stored if not mon.egg and mon.box == snapshot.active_box
                               and self.needed_move(snapshot) in self.data.species[mon.species]['machines'])
                    self.menu = Storage('WITHDRAW', mon.position, len(snapshot.party))
                return Action('a', 8, 36)
            if self.goal.key.startswith('push_') and mem.byte('wBikeFlags') & 1:
                self.nav.issued(snapshot, self.goal.face)
                return Action(self.goal.face, 16, 32)
            if self.goal.key == 'fish_surf' and self.interaction == self.goal.key:
                self.menu = Use(self.data.items['GOOD_ROD'])
                return Action(None, 0, 24)
            if self.goal.key == 'buy_balls' and self.interaction == self.goal.key:
                item, amount = self.shopping
                self.menu = Buy(item, amount, dict(snapshot.items).get(item, 0))
                return Action('a', 8, 36)
            if self.goal.key == 'sell_supplies' and self.interaction == self.goal.key:
                item, count = self.shopping
                self.menu = Sell(item, count)
                return Action('a', 8, 36)
            if self.goal.face and self.interaction != self.goal.key:
                self.interaction = self.goal.key
                return Action(self.goal.face, 8, 8)
            return Action('a', 8, 36)
        # Briefly wait for moving people or map transitions before replanning.
        return Action(None, 0, 24)

    def walk(self, snapshot, memory, path):
        mem = Memory(memory, self.data)
        surf = bool(snapshot.badges & 8) and any(57 in mon.moves for mon in snapshot.party)
        dx, dy = DIRS[path[0]]
        entry = self.data.maps[snapshot.map]
        nx, ny = snapshot.x + dx, snapshot.y + dy
        cut_tree = (0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x12, 0x1A))
        water = (surf and mem.byte('wPlayerState') not in (4, 8)
                 and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                 and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in (0x21, 0x29))
        obstacle = (surf and 0 <= nx < entry['width'] and 0 <= ny < entry['height']
                    and self.nav.collision(snapshot, memory)[ny * entry['width'] + nx] in ((0x24, 0x2C, 0x33) if path[0] == 'up' else (0x24, 0x2C)))
        if cut_tree or water or obstacle or (nx, ny) in {(x, y) for _, x, y in snapshot.objects}:
            key = (snapshot.map, snapshot.x + dx, snapshot.y + dy)
            if self.interaction == key and mem.byte('wPlayerDirection') & 12 == {'down': 0, 'up': 4, 'left': 8, 'right': 12}[path[0]]:
                return Action('a', 8, 36)
            self.interaction = key
            return Action(path[0], 8, 16)
        self.interaction = None
        self.nav.issued(snapshot, path[0])
        return Action(path[0], 16, 16)

    def remedy(self, snapshot, *, active=None):
        items = dict(snapshot.items)
        for slot, mon in enumerate(snapshot.party):
            if mon.egg or active is not None and slot != active:
                continue
            names = ()
            if mon.hp == 0:
                names = ('MAX_REVIVE', 'REVIVE')
            elif mon.hp < mon.max_hp * (0.55 if snapshot.in_battle else 0.8):
                names = ('FULL_RESTORE', 'MAX_POTION', 'HYPER_POTION', 'SUPER_POTION', 'POTION')
            elif mon.status:
                names = ('FULL_RESTORE', 'FULL_HEAL', 'ANTIDOTE' if mon.status & 8 else
                         'AWAKENING' if mon.status & 7 else 'PARLYZ_HEAL' if mon.status & 64 else
                         'BURN_HEAL' if mon.status & 16 else 'ICE_HEAL')
            item = next((self.data.items[name] for name in names if items.get(self.data.items[name], 0)), None)
            if item:
                self.menu = Remedy(item, slot, items[item])
                return True
        return False

    def battle(self, snapshot, mem):
        text = snapshot.text
        needed = self.needed_move(snapshot)
        partner = (not any(needed in self.data.species[mon.species]['machines'] for mon in snapshot.party if not mon.egg)
                   and needed in self.data.species.get(snapshot.enemy_species, {}).get('machines', []))
        requested = (self.demand.get(snapshot.enemy_species, 0)
                     and sum(mon.species == snapshot.enemy_species and not mon.egg
                             for mon in snapshot.party + snapshot.stored) <= self.demand[snapshot.enemy_species])
        catch = (snapshot.in_battle == 1 and (snapshot.enemy_species not in snapshot.owned or partner or requested)
                 and snapshot.can_catch and any(self.data.item_names.get(item, '').casefold() in
                    {label.casefold() for label in self.ball_labels(snapshot)} for item, count in snapshot.pockets['balls'] if count))
        if (catch and not partner and snapshot.enemy_species not in {130, 243, 244, 245, 249, 250, 251}
                and snapshot.badges < 128 and snapshot.money < 1200
                and sum(count for _, count in snapshot.pockets['balls']) <= 3):
            catch = False
        weaken = self.capture_move(snapshot, mem) if catch else None
        if 'SWITCH' in text and 'STATS' in text:
            return Action(choose(snapshot.tiles, 'SWITCH', exact=True) or 'a', 8, 32)
        if 'QUIT' in text:
            return Action((choose(snapshot.tiles, 'USE') or 'a') if 'USE' in text else 'a')
        if any(row.startswith('ぐげござ') for row in snapshot.tiles[:2]):
            if not catch:
                return Action('b', 8, 64)
            if not any('▶' in row for row in snapshot.tiles[:12]):
                return Action(None, 0, 48)
            pocket = mem.byte('wCurPocket')
            if pocket != 1:
                return Action('left' if pocket > 1 else 'right')
            if not catch:
                return Action('b')
            for label in self.ball_labels(snapshot):
                button = choose(snapshot.tiles, label, exact=True)
                if button:
                    return Action(button)
            return Action('down')
        if ('CANCEL' in text and (mem.byte('wCurPocket') == 3
                and any(re.match(r'(?:H[1-7]|\d{2})[ ▶▷]', row[5:]) for row in snapshot.tiles)
                or mem.byte('wCurPocket') == 2 and any(self.data.item_names.get(item, '').upper() in text
                                                     for item, _ in snapshot.pockets.get('key', ())))):
            return Action('left' if catch else 'b')
        if '×' in text or 'CANCEL' in text and '/' not in text and 'ABLE' not in text:
            if not catch:
                return Action('b')
            if mem.byte('wCurPocket') != 1:
                return Action('left' if mem.byte('wCurPocket') > 1 else 'right')
            labels = self.ball_labels(snapshot)
            for label in labels:
                action = choose(snapshot.tiles, label, exact=True)
                if action:
                    return Action(action)
            return Action('down')
        if 'already out' in text:
            self.switching = None
            return Action('b', 8, 24)
        if 'no will' in text:
            self.switching = None
            return Action('b', 8, 48)
        if 'CANCEL' in text and '/' in text and 'TYPE' not in text:
            active = min(mem.byte('wCurBattleMon'), max(0, len(snapshot.party) - 1))
            if snapshot.party and snapshot.party[active].hp and self.switching is None:
                return Action('b')
            target = max((i for i, mon in enumerate(snapshot.party) if mon.hp and not mon.egg),
                         key=lambda i: max((self.move_score(move, snapshot.party[i], snapshot)
                                            for move, pp in zip(snapshot.party[i].moves, snapshot.party[i].pp) if pp), default=0),
                         default=0) + 1
            if self.switching is not None and snapshot.party[self.switching].hp:
                target = self.switching + 1
            else:
                self.switching = None
            cursor = mem.byte('wMenuCursorY')
            return Action('a' if target == cursor else 'down' if cursor < target else 'up')
        if 'FIGHT' in text and 'TYPE' not in text:
            self.switching = None
            active = mem.byte('wCurBattleMon')
            if catch and (partner or snapshot.enemy_species in {243, 244, 245, 249, 250, 251}) and weaken is None and snapshot.enemy_hp > snapshot.enemy_max_hp // 2:
                candidates = [(self.capture_move(snapshot, mem, slot=i), i)
                              for i, mon in enumerate(snapshot.party)
                              if i != active and not mon.egg and mon.hp > mon.max_hp // 2
                              and (partner or mon.level * 2 >= snapshot.enemy_level)]
                target = next((i for move, i in candidates if move is not None), None)
                if target is not None:
                    self.switching = target
                    if mem.byte('wMenuCursorX') < 2:
                        return Action('right')
                    if mem.byte('wMenuCursorY') > 1:
                        return Action('up')
                    return Action('a')
            scores = [max((self.move_score(move, mon, snapshot) for move, pp in zip(mon.moves, mon.pp) if pp), default=0)
                      if mon.hp and not mon.egg else 0 for mon in snapshot.party]
            if not catch and scores and scores[min(active, len(scores) - 1)] == 0 and max(scores) > 0:
                self.switching = max(range(len(scores)), key=scores.__getitem__)
                if mem.byte('wMenuCursorX') < 2:
                    return Action('right')
                if mem.byte('wMenuCursorY') > 1:
                    return Action('up')
                return Action('a')
            if self.data.maps[snapshot.map]['constant'] != 'BATTLE_TOWER_BATTLE_ROOM' and self.remedy(snapshot, active=mem.byte('wCurBattleMon')):
                return Action(None, 0, 24)
            self.learning = False
            if catch:
                if weaken is not None:
                    if mem.byte('wMenuCursorX') > 1:
                        return Action('left')
                    if mem.byte('wMenuCursorY') > 1:
                        return Action('up')
                    return Action('a')
                if mem.byte('wMenuCursorX') > 1:
                    return Action('left')
                if mem.byte('wMenuCursorY') < 2:
                    return Action('down')
                return Action('a')
            # The cartridge remembers this cursor between turns.
            if mem.byte('wMenuCursorX') > 1:
                return Action('left')
            if mem.byte('wMenuCursorY') > 1:
                return Action('up')
            return Action('a')
        if any(phrase in text for phrase in ('trying to learn', 'Which move', 'HM moves', 'Forget an')):
            self.learning = True
        if ('TYPE/' in text or 'Disabled!' in text or 'No PP' in text or 'TYPE' in text and '/' in text
                or self.learning and '▶' in text and 'Which move' in text):
            slot = min(mem.byte('wCurPartyMon' if self.learning else 'wCurBattleMon'), max(0, len(snapshot.party) - 1))
            if snapshot.party:
                mon = snapshot.party[slot]
                options = [(self.move_score(move, mon, snapshot), index)
                           for index, move in enumerate(mon.moves) if move and mon.pp[index]
                           and not (mem.byte('wPlayerDisableCount') and move == mem.byte('wDisabledMove'))]
                if not self.learning and snapshot.in_battle == 2 and not self.collection.get('tower'):
                    normal_available = any(self.data.moves.get(move, {}).get('type') == 0 and mon.pp[index]
                                           and self.move_score(move, mon, snapshot) > 0
                                           for index, move in enumerate(mon.moves) if move)
                    if normal_available:
                        options = [(score * (0.25 if mon.pp[index] <= 5
                                            and self.data.moves[mon.moves[index]]['type'] != 0 else 1), index)
                                   for score, index in options]
                if self.learning:
                    protected = {15, 19, 57, 70, 148, 250, 127, 29, 249}
                    if all(move in protected for move in mon.moves):
                        return Action('b')
                    target = min(range(4), key=lambda i: 999 if mon.moves[i] in protected else self.data.moves.get(mon.moves[i], {}).get('power', 0)) + 1
                else:
                    target = weaken + 1 if weaken is not None else max(options)[1] + 1 if options else 1
                cursor = mem.byte('wMenuCursorY')
                if cursor != target:
                    return Action('down' if cursor < target else 'up', 8, 40)
            return Action('a', 8, 40)
        return Action('a', 8, 24)

    def ball_labels(self, snapshot):
        master = ('MASTER BALL',) if snapshot.enemy_species in {243, 244, 245, 249, 250, 251} else ()
        regular = ('ULTRA BALL', 'GREAT BALL', 'POKé BALL', 'LURE BALL', 'FAST BALL',
                   'HEAVY BALL', 'LEVEL BALL', 'LOVE BALL', 'FRIEND BALL', 'MOON BALL')
        roaming = snapshot.enemy_species in {243, 244} or snapshot.enemy_species == 245 and self.data.game != 'crystal'
        return master + regular if roaming else regular + master

    def capture_move(self, snapshot, mem, slot=None):
        master = self.data.items['MASTER_BALL']
        if (dict(snapshot.pockets['balls']).get(master) and (self.ball_labels(snapshot)[0] == 'MASTER BALL'
                or not any(item != master and count for item, count in snapshot.pockets['balls']))):
            return None
        if not snapshot.party:
            return None
        mon = snapshot.party[min(mem.byte('wCurBattleMon') if slot is None else slot, len(snapshot.party) - 1)]
        if not mem.byte('wEnemyMonStatus'):
            for index, move in enumerate(mon.moves):
                entry = self.data.moves.get(move, {})
                if (mon.pp[index] and entry.get('effect') in {'EFFECT_SLEEP', 'EFFECT_PARALYZE'}
                        and all(self.data.matchups.get((entry['type'], kind), 1)
                                for kind in self.data.species[snapshot.enemy_species]['types'])):
                    return index
        if snapshot.enemy_hp <= snapshot.enemy_max_hp // 2:
            return None
        options = []
        for index, move in enumerate(mon.moves):
            entry = self.data.moves.get(move, {})
            if not mon.pp[index] or not entry.get('power') or entry.get('effect') not in {'EFFECT_NORMAL_HIT', 'EFFECT_FALSE_SWIPE'}:
                continue
            special = entry['type'] >= 20
            defense = mem.word('wEnemyMonSpclDef' if special else 'wEnemyMonDefense')
            attack = mon.stats[4 if special else 1]
            factor = 1.5 if entry['type'] in self.data.species[mon.species]['types'] else 1
            for kind in set(self.data.species[snapshot.enemy_species]['types']):
                factor *= self.data.matchups.get((entry['type'], kind), 1)
            damage = (((2 * mon.level // 5 + 2) * entry['power'] * attack / max(1, defense)) / 50 + 2) * factor
            if entry.get('effect') == 'EFFECT_FALSE_SWIPE' or 0 < damage * 2.5 < snapshot.enemy_hp:
                options.append((damage, index))
        return max(options)[1] if options else None

    def move_score(self, mid, mon, snapshot):
        move = self.data.moves.get(mid, {})
        power = move.get('power', 0)
        if not power:
            return 0
        kind = move['type']
        factor = 1
        for target_type in set(self.data.species.get(snapshot.enemy_species, {}).get('types', [])):
            factor *= self.data.matchups.get((kind, target_type), 1)
        if not factor:
            return 0
        accuracy = move.get('accuracy', 100) / 100
        effect = move.get('effect')
        if effect == 'EFFECT_STATIC_DAMAGE':
            return power * accuracy
        if effect == 'EFFECT_LEVEL_DAMAGE':
            return mon.level * accuracy
        if effect == 'EFFECT_SUPER_FANG':
            return getattr(snapshot, 'enemy_hp', 0) / 2 * accuracy
        attack = mon.stats[1 if kind < 20 else 4]
        enemy = self.data.species.get(snapshot.enemy_species, {}).get('stats', [50] * 6)
        defense = (enemy[2 if kind < 20 else 5] + 8) * 2 * getattr(snapshot, 'enemy_level', mon.level) / 100 + 5
        stab = 1.5 if kind in self.data.species[mon.species]['types'] else 1
        score = ((2 * mon.level / 5 + 2) * power * attack / max(1, defense) / 50 + 2) * factor * stab * accuracy
        if effect == 'EFFECT_MULTI_HIT':
            score *= 3
        if effect in {'EFFECT_DOUBLE_HIT', 'EFFECT_POISON_MULTI_HIT'}:
            score *= 2
        if move.get('effect') in {'EFFECT_EXPLOSION', 'EFFECT_SELFDESTRUCT'}:
            score *= 0.1
        if move.get('effect') in {'EFFECT_RECHARGE', 'EFFECT_RAZOR_WIND', 'EFFECT_SOLARBEAM'}:
            score *= 0.5
        return score
