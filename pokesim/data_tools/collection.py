"""Build version-specific collection sources from the pret/pokered checkout."""
import json
import re
import sys
from pathlib import Path


def version_text(text, version):
    enabled = [True]
    for line in text.splitlines():
        match = re.match(r'\s*IF DEF\(_(RED|BLUE)\)', line)
        if match:
            enabled.append(enabled[-1] and match[1].lower() == version)
        elif line.strip() == 'ELSE' and len(enabled) > 1:
            enabled[-1] = enabled[-2] and not enabled[-1]
        elif line.strip() == 'ENDC' and len(enabled) > 1:
            enabled.pop()
        elif enabled[-1]:
            yield line.split(chr(59))[0]


def generate(src, strategy):
    species = {v['name']: int(k) for k, v in strategy['species'].items()}
    maps = {w['symbol']: int(k) for k, w in strategy['world'].items()}
    result = {'versions': {}, 'evolutions': {}}
    text = (src / 'data/pokemon/evos_moves.asm').read_text()
    names = {name.replace('_', ''): sid for name, sid in species.items()}
    for name, block in re.findall(r'^(\w+)EvosMoves:\n(.*?)(?=^\w+EvosMoves:|\Z)', text, re.M | re.S):
        sid = names.get(name.upper())
        if not sid:
            continue
        evos = []
        for method, args in re.findall(r'\bdb EVOLVE_(\w+),\s*([^\n]+)', block):
            parts = args.split(chr(59))[0].replace(' ', '').split(',')
            if parts[-1] not in species:
                continue
            evos.append({'method': method.lower(), 'requirement': int(parts[0]) if parts[0].isdigit() else parts[0],
                         'species': species[parts[-1]]})
        result['evolutions'][sid] = evos
    for version in ('red', 'blue'):
        sources = {}
        def add(sid, **source):
            sources.setdefault(sid, []).append(source)
        for key, world in strategy['world'].items():
            path = src / 'data/wild/maps' / (world['name'] + '.asm')
            if not path.exists():
                continue
            method = None
            for line in version_text(path.read_text(), version):
                match = re.search(r'def_(grass|water)_wildmons\s+(\d+)', line)
                if match:
                    method = ('surf' if match[1] == 'water' else 'grass') if int(match[2]) else None
                if 'end_' in line:
                    method = None
                match = re.match(r'\s*db\s+(\d+),\s*(\w+)', line)
                if method and match and match[2] in species:
                    source = dict(map=int(key), method='safari' if world['symbol'].startswith('SAFARI_ZONE_') else method,
                                  level=int(match[1]))
                    if source not in sources.get(species[match[2]], []):
                        add(species[match[2]], **source)
        fishing = '\n'.join(version_text((src / 'data/wild/super_rod.asm').read_text(), version))
        groups = {n: [(int(l), species[p]) for l, p in re.findall(r'db\s+(\d+),\s*(\w+)', block) if p in species]
                  for n, block in re.findall(r'\.(Group\d+):\n(.*?)(?=\.Group\d+:|\Z)', fishing, re.S)}
        for map_name, group in re.findall(r'dbw\s+(\w+),\s*\.(Group\d+)', fishing):
            if map_name in maps:
                for level, sid in groups[group]:
                    add(sid, map=maps[map_name], method='fish', rod='SUPER_ROD', level=level)
        for map_name in ('PALLET_TOWN', 'VIRIDIAN_CITY', 'VERMILION_CITY', 'FUCHSIA_CITY'):
            add(species['MAGIKARP'], map=maps[map_name], method='fish', rod='OLD_ROD', level=5)
            for name in ('POLIWAG', 'GOLDEEN'):
                add(species[name], map=maps[map_name], method='fish', rod='GOOD_ROD', level=10)
        for name, map_name, fragment, flag in (
            ('ARTICUNO', 'SEAFOAM_ISLANDS_B4F', 'ARTICUNO', 'EVENT_BEAT_ARTICUNO'),
            ('ZAPDOS', 'POWER_PLANT', 'ZAPDOS', 'EVENT_BEAT_ZAPDOS'),
            ('MOLTRES', 'VICTORY_ROAD_2F', 'MOLTRES', 'EVENT_BEAT_MOLTRES'),
            ('MEWTWO', 'CERULEAN_CAVE_B1F', 'MEWTWO', 'EVENT_BEAT_MEWTWO'),
            ('EEVEE', 'CELADON_MANSION_ROOF_HOUSE', 'EEVEE_POKEBALL', None),
            ('LAPRAS', 'SILPH_CO_7F', 'SILPH_WORKER_M1', None),
            ('HITMONLEE', 'FIGHTING_DOJO', 'HITMONLEE', 'EVENT_GOT_HITMONLEE'),
            ('HITMONCHAN', 'FIGHTING_DOJO', 'HITMONCHAN', 'EVENT_GOT_HITMONCHAN')):
            add(species[name], map=maps[map_name], method='static' if name in ('ARTICUNO','ZAPDOS','MOLTRES','MEWTWO') else 'gift',
                fragment=fragment, flag=flag)
        for name, item in (('OMANYTE','HELIX_FOSSIL'),('KABUTO','DOME_FOSSIL'),('AERODACTYL','OLD_AMBER')):
            add(species[name], map=maps['CINNABAR_LAB_FOSSIL_ROOM'], method='fossil', item=item, fragment='SCIENTIST1')
        for give, get, map_name, fragment in (
            ('ABRA','MR_MIME','ROUTE_2_TRADE_HOUSE',''),
            ('SPEAROW','FARFETCHD','VERMILION_TRADE_HOUSE',''),
            ('SLOWBRO','LICKITUNG','ROUTE_18_GATE_2F',''),
            ('POLIWHIRL','JYNX','CERULEAN_TRADE_HOUSE','')):
            add(species[get], map=maps[map_name], method='trade', give=species[give], fragment=fragment)
        result['versions'][version] = sources
    result['trainers'] = []
    for key,w in strategy['world'].items():
        path = src / 'scripts' / (w['name'] + '.asm')
        if not path.exists():
            continue
        text = path.read_text()
        headers = dict(re.findall(r'(\w+TrainerHeader\d*):\s*\n\s*trainer (EVENT_\w+)',text))
        for x,y,sprite,movement,fragment in w['objects']:
            label = fragment.removeprefix('TEXT_').replace('_','').lower() + 'text'
            functions = re.findall(r'^(\w+Text):\n(.*?)(?=^\w+:|\Z)',text,re.M|re.S)
            for fn,block in functions:
                if fn.lower() != label:
                    continue
                ref = re.search(r'ld hl, (\w+TrainerHeader\d*)',block)
                if ref and ref[1] in headers:
                    result['trainers'].append(dict(map=int(key),fragment=fragment,flag=headers[ref[1]]))
    return result
