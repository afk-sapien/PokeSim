"""Bounded collecting expeditions and evolution projects for a continuing adventure."""
import json
from collections import Counter
from functools import lru_cache
from ..game_data import load
from pathlib import Path

from .progression import Goal, object_goal, at
from .navigation import DIRS
from .director import AdventureDirector
from ..strategy_data import ITEMS, MAPS, SPECIES, WORLD, EVENTS, event_set, object_hidden

DATA = load('collection.json')
EVOS = {int(sid): rows for sid, rows in DATA['evolutions'].items()}
PACE = {'focused': (0, 0), 'balanced': (3600, 18000), 'thorough': (10800, 12000)}
CENTERS = tuple((m, 13, 4) for m, w in WORLD.items() if 'Pokecenter' in w['name'] and w['width'] == 14)
CENTERS += ((MAPS['INDIGO_PLATEAU_LOBBY'], 15, 8),)
LEAGUE = {MAPS[n] for n in ('LORELEIS_ROOM','BRUNOS_ROOM','AGATHAS_ROOM','LANCES_ROOM','CHAMPIONS_ROOM','HALL_OF_FAME')}
RODS = {'OLD_ROD': 'VERMILION_OLD_ROD_HOUSE', 'GOOD_ROD': 'FUCHSIA_GOOD_ROD_HOUSE', 'SUPER_ROD': 'ROUTE_12_SUPER_ROD_HOUSE'}
TRADE_NPCS = {'ROUTE_2_TRADE_HOUSE':'SCIENTIST', 'VERMILION_TRADE_HOUSE':'LITTLE_GIRL',
              'ROUTE_18_GATE_2F':'YOUNGSTER', 'CERULEAN_TRADE_HOUSE':'GRANNY'}


# Grass tile per tileset, from data/tilesets/tileset_headers.asm. A tileset with no grass tile
# (CAVERN and the interiors, -1 upstream) has encounters on any walkable floor tile instead, which
# is the fallback in tiles(). Leaving PLATEAU out of this meant Route 23 offered 981 encounter
# tiles instead of its 44, so the run walked to a tile that could never produce a battle.
GRASS_TILES = {'OVERWORLD': 0x52, 'FOREST': 0x20, 'PLATEAU': 0x45}


def name(sid):
    return SPECIES.get(sid, {}).get('name', 'Unknown').replace('_', ' ').title()


def dex(sid):
    return SPECIES.get(sid, {}).get('dex', 0)


def storage_exchange_possible(s):
    """Taking a Pokemon out needs a free party slot, or somewhere to deposit a reserve first."""
    return len(s.party) < 6 or not s.box_full or s.next_free_box is not None


def champion(s):
    return s.hall_of_fame_count > 0 or event_set(s.event_flags, 'EVENT_BEAT_CHAMPION_RIVAL') or s.map == MAPS['HALL_OF_FAME']


def tiles(source):
    w = WORLD[source['map']]
    mode = source['method']
    if mode == 'fish':
        points = []
        for y, row in enumerate(w['tiles']):
            for x, tile in enumerate(row):
                if tile not in w['passable'] or tile in (0x14,0x32,0x48):
                    continue
                for direction, (dx,dy) in DIRS.items():
                    if 0 <= y+dy < w['height'] and 0 <= x+dx < w['width'] and w['tiles'][y+dy][x+dx] in (0x14,0x32,0x48):
                        points.append((source['map'], x, y, direction))
        return tuple(points)
    water = (0x14,0x32,0x48)
    grass = GRASS_TILES.get(w['tileset'])
    return tuple((source['map'],x,y,None) for y,row in enumerate(w['tiles']) for x,tile in enumerate(row)
                 if (tile in water if mode == 'surf'
                     else tile == grass if grass is not None
                     else tile in w['passable'] and tile not in water)
                 and not any(warp[:2] == [x,y] for warp in w['warps']))


@lru_cache(maxsize=200)
def training_targets(version, level):
    sources = [source for rows in DATA['versions'].get(version, {}).values() for source in rows
               if source['method'] == 'grass' and source['level'] <= max(3, level - 3)
               and not WORLD[source['map']]['symbol'].startswith('CERULEAN_CAVE')]
    best = max((source['level'] for source in sources), default=0)
    return tuple(sorted({target[:3] for source in sources if source['level'] >= max(2, best - 8)
                         for target in tiles(source)}))


def training_family(sid):
    family = {sid}
    for _ in range(2):
        family.update(evo['species'] for parent in tuple(family) for evo in EVOS.get(parent, [])
                      if evo['method'] == 'level')
    return sorted(family)


class Collection:
    def __init__(self):
        self.pace = 'thorough'
        self.version = 'red'
        self.project = None
        self.remaining = 0
        self.cooldown = 0
        self.attempts = {}
        self.elapsed = 0
        self.last_frame = None
        self.last_choice = -600
        self.report = {}
        self.report_key = None
        self.eevee_choice = 134
        self.history = []
        self.completed_champion = False
        self.idle_frames = 0
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        self.was_in_battle = False
        self.director = AdventureDirector()

    def state_dict(self):
        return {**{k:getattr(self,k) for k in ('pace','project','remaining','cooldown','attempts','elapsed','eevee_choice','history','completed_champion','idle_frames','project_maps','project_flags')},
                'director': self.director.state_dict()}

    def load(self, data):
        for key in self.state_dict():
            if key in data and key != 'director':
                setattr(self,key,data[key])
        self.director.load(data.get('director', {}))
        if self.pace not in PACE:
            self.pace = 'thorough'
        if self.eevee_choice not in (134, 135, 136):
            self.eevee_choice = 134
        self.last_frame = None
        self.report_key = None
        self.progress_token = None
        self.was_in_battle = False
        # A reload rewinds `elapsed` to the checkpoint's value while `last_choice` keeps the
        # in-memory high-water mark. Left alone, the spacing guard in choose() would then hold
        # for as long as the rewind and the planner would pick nothing at all.
        self.last_choice = min(self.last_choice, self.elapsed - 600)

    def abandon(self, reason):
        if not self.project:
            return False
        project = self.project
        label = name(project['species']) if project.get('species') else project['method'].title()
        progressed = bool(project.get('gains', {}).get('experience', 0))
        self.attempts[project.get('key', label)] = self.director.finish(
            project, self.elapsed, False, reason, progressed)
        self.history = (self.history + [f'Changed plan: {label}. {reason}'])[-6:]
        self.project = None
        self.remaining = 0
        self.cooldown = 0
        self.last_choice = self.elapsed - 600
        self.idle_frames = 0
        self.project_maps = []
        self.project_flags = []
        self.progress_token = None
        return True

    def observe(self,s, suspended=False, training_ready=True):
        delta = max(0,min(120,s.frame - self.last_frame)) if self.last_frame is not None else 0
        self.last_frame = s.frame
        self.elapsed += delta
        self.cooldown = max(0,self.cooldown-delta)
        self.completed_champion |= champion(s)
        self.attempts = {key: deadline for key, deadline in self.attempts.items() if deadline > self.elapsed}
        if self.project and not suspended:
            project = self.project
            self.remaining -= delta
            if len(self.project_flags) != len(s.event_flags):
                self.project_flags = list(s.event_flags)
            new_flags = any(now & ~before for now, before in zip(s.event_flags, self.project_flags))
            self.project_flags = [now | before for now, before in zip(s.event_flags, self.project_flags)]
            token = (s.owned, s.badges, s.items, s.coins,
                     tuple(sorted((p.species, p.level, p.experience) for p in s.party)))
            if project['method'] == 'train':
                trainee = self.trainee(s, project) if training_ready else None
                if trainee is not None:
                    mon = s.party[trainee]
                    project['parent'] = mon.species
                    # Reaching the party is a one-time preparation milestone. Keep it
                    # in the project so menu transitions and reloads cannot repeat it.
                    if 'initial_experience' not in project:
                        self.idle_frames = 0
                    baseline = project.setdefault('initial_experience', mon.experience)
                    gains = project.setdefault('gains', {})
                    gains['experience'] = max(gains.get('experience', 0), mon.experience - baseline)
                    gains['levels'] = max(gains.get('levels', 0), mon.level - project['initial_level'])
                    token = (mon.species, mon.level, mon.experience)
                else:
                    token = None
            # First visits and completed battles count toward an expedition. Walking between
            # familiar maps, rearranging menus, and taking damage do not extend its deadline.
            self.idle_frames += delta
            if ((token is not None and self.progress_token is not None and token != self.progress_token)
                    or new_flags or s.map not in self.project_maps
                    or self.project['method'] in ('grass', 'surf', 'fish', 'safari') and self.was_in_battle and not s.in_battle):
                self.idle_frames = 0
            if s.map not in self.project_maps:
                self.project_maps.append(s.map)
            self.progress_token = token
            self.was_in_battle = bool(s.in_battle)
            target = self.project.get('species')
            item = self.project.get('item')
            finished = (target and dex(target) in s.owned) or (not target and item and any(i==ITEMS[item] for i,q in s.items if q))
            if self.project['method']=='fossil' and self.project.get('initial_owned'):
                finished = finished or bool(s.owned - set(self.project['initial_owned']))
            if self.project['method']=='trainer':
                finished = event_set(s.event_flags,self.project['flag'])
            if self.project['method']=='explore':
                finished = (s.map,s.x,s.y) == tuple(self.project['target'])
            if self.project['method']=='rematch':
                finished = s.hall_of_fame_count > self.project['hof_count']
            if project['method'] == 'train':
                finished = trainee is not None and s.party[trainee].level >= project['target_level']
            if finished or self.remaining <= 0:
                label = name(target) if target else item.replace('_',' ').title() if item else self.project['method'].title()
                if project['method'] == 'train':
                    label = f'{name(project["parent"])} toward level {project["target_level"]}'
                self.history = (self.history + [f'{"Completed" if finished else "Will revisit"}: {label}'])[-6:]
                progressed = bool(project.get('gains', {}).get('experience', 0))
                retry = self.director.finish(project, self.elapsed, bool(finished),
                                             'Target reached' if finished else 'Expedition time budget reached', progressed)
                if retry:
                    self.attempts[self.project['key']] = retry
                self.project = None
                self.cooldown = 1200 if self.completed_champion else PACE[self.pace][1]
            elif self.idle_frames >= 7200 and not s.in_battle:
                self.abandon('No encounter, training gain, or new route in two minutes')
        key = (s.owned, s.items, s.stored_pokemon, tuple((p.species,p.level) for p in s.party), s.event_flags, s.hidden_objects, self.completed_champion, self.pace, self.version)
        if key != self.report_key:
            self.report_key = key
            self.report = self.describe(s)

    def sources(self):
        return {int(k):v for k,v in DATA['versions'].get(self.version, {}).items()}

    def available(self,s,source):
        mode = source['method']
        bag = dict(s.items)
        if source.get('flag') in EVENTS and event_set(s.event_flags, source['flag']):
            return False
        if mode in ('gift','static'):
            objects = WORLD[source['map']]['objects']
            index = next((i for i,o in enumerate(objects) if source.get('fragment','') in o[4]),None)
            if index is not None:
                try:
                    if object_hidden(s,source['map'],index):
                        return False
                except ValueError:
                    pass
        if source['map'] in {MAPS['CERULEAN_CAVE_1F'], MAPS['CERULEAN_CAVE_2F'], MAPS['CERULEAN_CAVE_B1F']} and not self.completed_champion:
            return False
        if source.get('fragment') in ('HITMONLEE','HITMONCHAN'):
            return not any(event_set(s.event_flags,f) for f in ('EVENT_GOT_HITMONLEE','EVENT_GOT_HITMONCHAN'))
        if mode == 'fossil':
            return bool(bag.get(ITEMS[source['item']]) or event_set(s.event_flags,'EVENT_GAVE_FOSSIL_TO_LAB'))
        return True

    def describe(self,s):
        sources = self.sources()
        held = {p.species for p in s.party} | {sid for box,sid,level,nick in s.stored_pokemon}
        reachable = {sid for sid,rows in sources.items() if any(self.available(s,r) and r['method'] not in ('trade',) for r in rows)} | held
        # The unavailable starter families have no wild source in Red or Blue.
        for _ in range(4):
            for sid in tuple(reachable):
                reachable.update(e['species'] for e in EVOS.get(sid,[]) if e['method'] != 'trade')
            for sid,rows in sources.items():
                if any(r['method']=='trade' and r['give'] in reachable for r in rows):
                    reachable.add(sid)
        entries = []
        for sid,mon in sorted(SPECIES.items(),key=lambda pair:pair[1]['dex']):
            d = mon['dex']
            parents = [(p,e) for p,rows in EVOS.items() for e in rows if e['species']==sid]
            if d in s.owned:
                status,reason = 'caught','Registered in the Pokédex'
            elif any(e['method']=='trade' for p,e in parents) and sid not in sources:
                status,reason = 'external','Requires a link trade'
            elif sid in reachable:
                status,reason = 'available','Available through encounters, gifts, trades, or evolution'
                if parents and not sources.get(sid):
                    reason = 'Evolve ' + name(parents[0][0])
            else:
                status,reason = 'unavailable','Requires another version, an unchosen gift, or a different acquisition method'
            if d == 151 and d not in s.owned:
                status,reason = 'external','Event Pokémon, not a normal encounter'
            if d == 137 and d not in s.owned:
                status,reason = 'available','Save coins for the Game Corner prize'
            if d in (134,135,136) and d not in s.owned and not any(dex(p)==133 for p in held) and any(i in s.owned for i in (134,135,136)):
                status,reason = 'unavailable','Requires another Eevee after the evolution choice'
            if status != 'caught' and d in range(1,10):
                family = (d-1)//3
                if not any(i in s.owned for i in range(family*3+1,family*3+4)):
                    status,reason = 'external','Requires another starter through trading'
            rows = sources.get(sid,[])
            if status == 'unavailable' and any(r['method']=='static' for r in rows):
                reason = 'Encounter already resolved, or area not unlocked yet'
            entries.append({'dex':d,'name':name(sid),'species':sid,'status':status,'reason':reason,
                            'methods':sorted({r['method'] for r in rows})})
        evos = []
        for p in s.party:
            for e in EVOS.get(p.species,[]):
                if dex(e['species']) not in s.owned:
                    evos.append({'from':p.nick or name(p.species),'to':name(e['species']), 'method':e['method'],
                                 'requirement':e['requirement'],'level':p.level})
        return {'pace':self.pace,'phase':'Pokédex expeditions' if self.completed_champion else 'Thorough adventure' if self.pace=='thorough' else 'Badge journey',
                'caught':len(s.owned),'available':sum(e['status']=='available' for e in entries),
                'entries':entries,'evolutions':evos[:6], 'version':self.version}

    def details(self):
        return {**self.report,'hunt':self.project,'remaining_seconds':max(0,self.remaining//60),
                'history':self.history, 'director': self.director.state_dict(),
                'reason':'Collect, evolve, train, and explore in bounded projects. Repeated failures wait longer before retrying.'}

    def choose(self,s,nav,rng,main):
        if s.map in LEAGUE or not s.party or not s.owned or not event_set(s.event_flags,'EVENT_GOT_POKEDEX') or main.key.startswith(('heal','party_','teach_','restock')):
            return None
        if self.project:
            return self.goal(s)
        if (self.pace=='focused' and not self.completed_champion) or self.cooldown or self.elapsed-self.last_choice < 600:
            return None
        if not self.completed_champion and main.key.startswith('league_'):
            return None
        self.last_choice = self.elapsed
        bag = dict(s.items)
        held = [(p.species,p.level,None) for p in s.party] + [(sid,level,box) for box,sid,level,nick in s.stored_pokemon]
        candidates = []
        def add(project,weight):
            key = str(project.get('species',0)) + ':' + project['method'] + ':' + str(project.get('map',0)) + ':' + str(project.get('fragment',''))
            if project['method'] == 'train':
                key = f'train:{project["parent"]}:{project["target_level"]}'
            if self.attempts.get(key,0) <= self.elapsed:
                goal = self.goal(s, project)
                if goal and goal.targets and distance_to(goal.targets) is not None:
                    candidates.append((weight,{**project,'key':key}))
        sources = self.sources()
        searched = set()
        distance_to = nav.distance_lookup((s.map, s.x, s.y), s.frame)
        for sid,rows in sources.items():
            if dex(sid) in s.owned:
                continue
            for source in rows:
                if not self.available(s,source):
                    continue
                mode = source['method']
                if not self.completed_champion and source['map'] != s.map:
                    continue
                if mode in ('grass','surf','fish','safari','static') and (not s.can_catch or not any(bag.get(ITEMS[n]) for n in ('POKE_BALL','GREAT_BALL','ULTRA_BALL','MASTER_BALL'))):
                    continue
                if mode == 'surf' and not nav.can_surf:
                    continue
                if mode == 'fish' and not bag.get(ITEMS[source['rod']]):
                    continue
                if mode == 'safari' and s.money < 800:
                    continue
                if mode == 'trade':
                    offered = next((p for p in s.party if p.species==source['give']),None)
                    if offered is None or offered.level == max(p.level for p in s.party) or any(
                        mid in (15,19,57,70,148) and not any(mid in other.moves for other in s.party if other is not offered)
                        for mid in offered.moves):
                        continue
                if mode in ('gift','fossil','trade','static') and not self.completed_champion and s.map != source['map']:
                    continue
                if mode in ('gift','fossil') and len(s.party)>=6 and not storage_exchange_possible(s):
                    continue
                if mode == 'grass' and source.get('level',100) > max(p.level for p in s.party)+3:
                    continue
                search_key = (sid,source['map'],mode,source.get('rod'))
                if search_key in searched:
                    continue
                searched.add(search_key)
                project = dict(source,species=sid)
                goal = self.project_goal(s,project)
                if not goal or not goal.targets:
                    continue
                distance = distance_to(goal.targets)
                if distance is None:
                    continue
                if not self.completed_champion and (source['map'] != s.map or distance>60):
                    continue
                add(project, (5 if mode in ('gift','fossil','static') else 1) / (1+distance/40))
        for sid,level,box in held:
            if not self.completed_champion and self.pace=='balanced' and self.elapsed < 1800:
                continue
            for evo in EVOS.get(sid,[]):
                if dex(evo['species']) in s.owned or evo['method']=='trade':
                    continue
                if sid == next((i for i,d in SPECIES.items() if d['dex']==133),None) and dex(evo['species']) != self.eevee_choice:
                    continue
                if evo['method']=='item' and not bag.get(ITEMS[evo['requirement']]) and evo['requirement']=='MOON_STONE':
                    continue
                if box is not None and (not self.completed_champion or not storage_exchange_possible(s)):
                    continue
                add({'species':evo['species'],'parent':sid,'method':'evolve','evolution':evo,'box':box},3)
        if self.completed_champion:
            counts = Counter(sid for sid, level, box in held)
            for sid, level, box in held:
                family = training_family(sid)
                if level >= 100 or sum(counts[relative] for relative in family) != 1:
                    continue
                if box is not None and not storage_exchange_possible(s):
                    continue
                # Prefer missing evolutions before a general level milestone for this partner.
                if any(evo['method'] == 'level' and dex(evo['species']) not in s.owned for evo in EVOS.get(sid, [])):
                    continue
                add({'method': 'train', 'parent': sid, 'family': family,
                     'box': box, 'initial_level': level, 'target_level': min(100, (level // 10 + 1) * 10)},
                    1 / (1 + level / 20))
            if s.money < 10000:
                add({'method':'rematch','hof_count':s.hall_of_fame_count},10)
            porygon = next(sid for sid,mon in SPECIES.items() if mon['dex']==137)
            if 137 not in s.owned and (s.money >= 20000 or s.coins >= (9999 if self.version=='red' else 6500)):
                add({'method':'prize','species':porygon,'map':MAPS['GAME_CORNER_PRIZE_ROOM']},0.5)
            for trainer in DATA.get('trainers',[]):
                if trainer['map'] in LEAGUE or event_set(s.event_flags,trainer['flag']):
                    continue
                if trainer['map'] == s.map:
                    add(dict(trainer,method='trainer'),1.5)
            unseen = []
            visited = {m for m,x,y in nav.visits}
            for m,w in WORLD.items():
                if m in visited or m in LEAGUE or m==s.map or not w['warps']:
                    continue
                warp = w['warps'][0]
                target = (m,warp[0],max(0,warp[1]-1))
                unseen.append((m,target))
            rng.shuffle(unseen)
            for m,target in unseen[:8]:
                if distance_to((target,)) is not None:
                    add({'method':'explore','map':m,'target':target},0.3)
                    break
            for rod,room in RODS.items():
                if not bag.get(ITEMS[rod]):
                    add({'method':'rod','item':rod,'map':MAPS[room],'room':room},2)
            if not bag.get(ITEMS['OLD_AMBER']) and 142 not in s.owned:
                if not event_set(s.event_flags,'EVENT_GOT_OLD_AMBER'):
                    add({'method':'amber','item':'OLD_AMBER','map':MAPS['MUSEUM_1F']},1)
        if not candidates:
            self.cooldown = 3600
            return None
        self.project = (self.director.select(candidates, rng, urgent=s.money < 10000)
                        if self.completed_champion else
                        rng.choices([p for w,p in candidates],weights=[w for w,p in candidates])[0])
        self.project['initial_owned'] = list(s.owned)
        self.idle_frames = 0
        self.project_maps = [s.map]
        self.project_flags = list(s.event_flags)
        self.progress_token = None
        self.remaining = 300000 if self.project['method']=='rematch' else 72000 if self.project['method']=='train' else 36000 if self.completed_champion else PACE[self.pace][0]
        nav.path.clear()
        return self.goal(s)

    def project_goal(self,s,p):
        mode=p['method']
        sid=p.get('species')
        if mode in ('grass','surf','fish','safari'):
            points=tiles(p)
            return Goal('collect_hunt','Find '+name(sid),f'Search {WORLD[p["map"]]["name"]} for a missing Pokédex entry',
                        tuple(t[:3] for t in points), approaches=tuple(t for t in points if t[3]))
        if mode in ('gift','static','trade','fossil'):
            room=WORLD[p['map']]['symbol']
            fragment = p['fragment']
            if mode=='trade':
                fragment=TRADE_NPCS[room]
            if mode=='gift' and dex(sid) in (106,107) and not event_set(s.event_flags,'EVENT_BEAT_KARATE_MASTER'):
                fragment='KARATE_MASTER'
            if mode=='gift' and dex(sid)==133:
                fragment='EEVEE_POKEBALL'
            if mode=='fossil' and event_set(s.event_flags,'EVENT_LAB_STILL_REVIVING_FOSSIL'):
                return at('collect_fossil_walk','Give the fossil lab time','Step outside while the fossil is revived','CINNABAR_ISLAND',6,10)
            return object_goal('collect_'+mode,'Collect '+name(sid),'Visit a remaining source for the Pokédex',room,fragment)
        if mode=='rematch':
            if s.map != MAPS['INDIGO_PLATEAU_LOBBY']:
                return at('collect_rematch','Return for a League rematch','Earn prize money and experience for collecting','INDIGO_PLATEAU_LOBBY',8,10)
            return object_goal('league_lorelei','Begin a League rematch','Fund the next expeditions','LORELEIS_ROOM','LORELEI')
        if mode=='trainer':
            return object_goal('collect_trainer','Meet an unbeaten trainer','Explore and earn experience and supplies',WORLD[p['map']]['symbol'],p['fragment'])
        if mode=='explore':
            return Goal('collect_explore','Explore '+WORLD[p['map']]['name'],'Visit an area that has not been explored',(tuple(p['target']),))
        if mode=='prize':
            if not dict(s.items).get(ITEMS['COIN_CASE']):
                return object_goal('collect_coins','Get the Coin Case','Prepare to exchange coins for Porygon','CELADON_DINER','FISHER')
            cost = 9999 if self.version=='red' else 6500
            if s.coins < cost:
                if s.money < 10000:
                    self.remaining=0
                    return None
                return at('collect_coins','Save coins for Porygon',f'{s.coins} of {cost} coins saved','GAME_CORNER',5,8,'up')
            return at('collect_prize','Collect Porygon','Exchange saved coins for a new Pokédex entry','GAME_CORNER_PRIZE_ROOM',4,3,'up')
        if mode=='rod':
            return object_goal('collect_rod','Obtain '+p['item'].replace('_',' ').title(),'Unlock more fishing encounters',p['room'],'FISHING_GURU')
        if mode=='amber':
            return object_goal('collect_amber','Collect Old Amber','Revive Aerodactyl at the Cinnabar lab','MUSEUM_1F','SCIENTIST2')
        return None

    @staticmethod
    def trainee(s, project):
        family = project.get('family', [project.get('parent')])
        return next((i for i, mon in enumerate(s.party) if mon.species in family), None)

    def goal(self,s,project=None):
        p=self.project if project is None else project
        if not p:
            return None
        if p['method'] in ('evolve', 'train'):
            index = self.trainee(s, p)
            if index is None:
                if not storage_exchange_possible(s):
                    return None
                return Goal('party_collection','Withdraw a training partner','Keep the main battlers and bring a reserve out of storage',CENTERS,'up',True)
            if p['method'] == 'train':
                return Goal('collect_train', f'Train {name(s.party[index].species)} to level {p["target_level"]}',
                            f'Level {s.party[index].level} of {p["target_level"]}. Raise a partner, then rotate projects',
                            training_targets(self.version, s.party[index].level))
            evo=p['evolution']
            if evo['method']=='item':
                if not dict(s.items).get(ITEMS[evo['requirement']]):
                    return at('collect_stone','Buy an evolution stone','Complete another Pokédex entry','CELADON_MART_4F',5,5,'down')
                return Goal('collect_evolve','Evolve '+name(p['parent']), 'Use '+evo['requirement'].replace('_',' ').title(),((s.map,s.x,s.y),))
            options=[]
            for rows in self.sources().values():
                for source in rows:
                    if source['method']=='grass' and source['level'] <= max(3,s.party[index].level-3) and source['level'] >= max(2,s.party[index].level-12):
                        if not WORLD[source['map']]['symbol'].startswith('CERULEAN_CAVE'):
                            options.extend(t[:3] for t in tiles(source))
            return Goal('collect_train','Train '+name(p['parent'])+' toward '+name(p['species']),
                        f'Work toward level {evo["requirement"]}, then resume other activities',tuple(set(options)))
        if p['method'] in ('gift','fossil') and len(s.party)>=6:
            if not storage_exchange_possible(s):
                return None
            return Goal('party_collection_space','Make room for a gift','Store a reserve before receiving a Pokémon',CENTERS,'up',True)
        return self.project_goal(s,p)
