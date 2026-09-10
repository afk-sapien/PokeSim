from dataclasses import replace
import random

from pokesim.policies.collection import Collection, DATA, EVOS, dex
from pokesim.policies.battle import choose_battle, needs_healing
from pokesim.policies.navigation import Navigator
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import StrategicPolicy
from pokesim.ram import read_snapshot, read_stored_pokemon, W_CURRENT_BOX, W_BOX_COUNT
from pokesim.strategy_data import MAPS, ITEMS, SPECIES
from pokesim.screen import Screen
from test_events import snap
from test_strategy import mon, flags, menu


def sid(d):
    return next(i for i,m in SPECIES.items() if m['dex']==d)


def state(**kw):
    base=dict(party=(mon(hp=100,max_hp=100,level=40),), owned=frozenset({1}),
              event_flags=flags('EVENT_GOT_POKEDEX'), items=((ITEMS['POKE_BALL'],10),))
    base.update(kw)
    return snap(**base)


def test_data_is_version_specific_and_has_evolution_methods():
    red=DATA['versions']['red']
    blue=DATA['versions']['blue']
    assert str(sid(43)) in red and str(sid(43)) not in blue
    assert str(sid(69)) in blue and str(sid(69)) not in red
    assert EVOS[sid(10)][0]['requirement']==7
    assert EVOS[sid(64)][0]['method']=='trade'
    assert EVOS[sid(44)][0]['requirement']=='LEAF_STONE'
    assert any(r['method']=='fish' for r in red[str(sid(147))])


def test_missing_low_level_species_gets_balls_without_a_lethal_attack():
    me=mon(level=80,hp=200,max_hp=200,attack=200,special=200)
    enemy=mon(species=sid(16),level=2,hp=10,max_hp=10,moves=(33,),pp=(35,))
    s=state(party=(me,),in_battle=1)
    assert choose_battle(s,me,enemy,0,collect_missing=True).kind=='item'


def test_catcher_uses_non_damaging_status_and_preserves_legendary():
    me=mon(moves=(79,33,0,0),pp=(15,35,0,0),hp=200,max_hp=200)
    enemy=mon(species=sid(16),level=2,hp=10,max_hp=10,moves=(33,),pp=(35,))
    s=state(party=(me,),in_battle=1)
    decision=choose_battle(s,me,enemy,0,collect_missing=True)
    assert (decision.kind,decision.index)==('fight',0)
    enemy=replace(enemy,species=sid(144))
    s=replace(s,items=((ITEMS['MASTER_BALL'],1),))
    assert choose_battle(s,me,enemy,0,collect_missing=True).kind=='item'
    s=replace(s,boxed_pokemon=((sid(16),2),)*20,party=(me,)*6)
    assert choose_battle(s,me,enemy,0,collect_missing=True).kind!='item'


def test_low_level_catcher_is_not_switched_into_certain_damage():
    me=mon(level=80,hp=200,max_hp=200,defense=200,moves=(33,),pp=(35,))
    weak=mon(level=2,hp=10,max_hp=10,defense=3,moves=(79,),pp=(15,))
    enemy=mon(species=sid(16),level=40,hp=100,max_hp=100,attack=100,moves=(63,),pp=(5,))
    s=state(party=(me,weak),in_battle=1)
    assert choose_battle(s,me,enemy,0,collect_missing=True).kind!='switch'


def test_hunt_deadline_survives_restart_and_yields_to_story():
    c=Collection()
    c.project={'species':sid(16),'method':'grass','map':MAPS['ROUTE_1'],'key':'hunt'}
    c.remaining=50
    saved=c.state_dict()
    restored=Collection()
    restored.load(saved)
    restored.observe(state(frame=100))
    restored.observe(state(frame=160))
    assert restored.project is None
    assert restored.attempts['hunt'] > restored.elapsed
    assert restored.cooldown > 0


def test_capture_completes_project_and_records_progress():
    c=Collection()
    c.project={'species':sid(16),'method':'grass','map':MAPS['ROUTE_1'],'key':'hunt'}
    c.remaining=100
    c.observe(state(owned=frozenset({1,16})))
    assert c.project is None and c.history[-1]=='Completed: Pidgey'


def test_readiness_for_postgame_uses_saved_hall_of_fame_count():
    c=Collection()
    c.observe(state(hall_of_fame_count=1))
    assert c.completed_champion
    assert c.details()['phase']=='Pokédex expeditions'


def test_restricted_entries_are_not_counted_as_available():
    c=Collection()
    report=c.describe(state())
    entries={e['dex']:e for e in report['entries']}
    assert entries[151]['status']=='external'
    assert entries[65]['status']=='external'
    assert entries[4]['status']=='external'
    assert entries[69]['status']=='unavailable'
    assert entries[137]['status']=='available'


def test_focused_pace_preserves_main_journey_before_champion():
    c=Collection()
    c.pace='focused'
    s=state(map=MAPS['ROUTE_1'])
    nav=Navigator()
    nav.update_story(s)
    assert c.choose(s,nav,random.Random(3),Goal('boulder','Brock','Earn a badge')) is None


def test_nonattacking_evolution_partner_does_not_cause_healing_loop():
    magikarp=mon(species=sid(129),moves=(150,),pp=(40,))
    fighter=mon()
    assert not needs_healing((magikarp,fighter))


def test_training_withdraws_a_boxed_partner_before_evolution():
    c=Collection()
    parent=sid(10)
    c.project={'method':'evolve','parent':parent,'species':sid(11),'box':2,'evolution':EVOS[parent][0],'key':'evo'}
    s=state(stored_pokemon=((2,parent,6,'MOSS'),))
    assert c.goal(s).key=='party_collection'
    s=replace(s,party=s.party+(mon(species=parent,level=6),))
    assert c.goal(s).key=='collect_train'


def test_stone_project_buys_then_uses_the_correct_stone():
    c=Collection()
    parent=sid(44)
    c.project={'method':'evolve','parent':parent,'species':sid(45),'box':None,'evolution':EVOS[parent][0],'key':'evo'}
    s=state(party=(mon(species=parent),))
    assert c.goal(s).key=='collect_stone'
    s=replace(s,items=s.items+((ITEMS['LEAF_STONE'],1),))
    assert c.goal(s).key=='collect_evolve'


def test_pc_deposits_before_switching_to_a_full_source_box():
    p=StrategicPolicy(1)
    p.collection.project={'method':'evolve','parent':sid(10),'box':2}
    p.goal=Goal('party_collection','Withdraw','Evolution')
    s=state(party=(mon(),)*6,active_box=1,boxed_pokemon=())
    mem=menu({1:'  WITHDRAW',3:'  DEPOSIT',5:'  RELEASE',7:'  CHANGE BOX'},(1,1),top=(1,1))
    assert p._dispatch(s,Screen(mem),'pc',mem)[0].button=='down'
    assert p.pc_operation=='deposit'


def test_fossil_quest_walks_outside_while_lab_works():
    c=Collection()
    c.project={'method':'fossil','species':sid(138),'item':'HELIX_FOSSIL','fragment':'SCIENTIST1','map':MAPS['CINNABAR_LAB_FOSSIL_ROOM'],'key':'fossil'}
    s=state(party=(mon(),),event_flags=flags('EVENT_GOT_POKEDEX','EVENT_GAVE_FOSSIL_TO_LAB','EVENT_LAB_STILL_REVIVING_FOSSIL'))
    assert c.goal(s).key=='collect_fossil_walk'


def test_coin_project_stages_and_cash_reserve():
    c=Collection()
    c.project={'method':'prize','species':sid(137),'key':'prize'}
    assert c.goal(state()).key=='collect_coins'
    s=state(items=((ITEMS['COIN_CASE'],1),),money=20000,coins=9999)
    assert c.goal(s).key=='collect_prize'
    c.remaining=100
    assert c.goal(replace(s,coins=0,money=9000)) is None
    assert c.remaining==0


def test_snapshot_reads_coin_and_completion_bytes():
    mem=bytearray(65536)
    mem[0xD5A2]=2
    mem[0xD5A4:0xD5A6]=bytes([0x65,0x00])
    s=read_snapshot(mem,0)
    assert s.coins==6500 and s.hall_of_fame_count==2


def test_storage_records_read_banked_species_levels_and_names():
    class Memory:
        def __getitem__(self,key):
            if key==W_CURRENT_BOX: return 0x80
            if key==W_BOX_COUNT: return 0
            if isinstance(key,tuple):
                bank,address=key
                if (bank,address)==(3,0xA000): return 1
                if (bank,address)==(3,0xA016): return sid(10)
                if (bank,address)==(3,0xA019): return 6
                if 0xA386 <= address < 0xA391: return 0x50
            return 0
    assert read_stored_pokemon(Memory())==((6,sid(10),6,''),)


def test_adventure_pace_command_persists_without_changing_speed():
    from unittest.mock import Mock
    from pokesim.emulator import Emulator
    emu=Emulator.__new__(Emulator)
    emu.policy=StrategicPolicy(2)
    emu.store=Mock()
    emu.speed=4
    assert emu._handle_command('adventure_pace','balanced')
    assert emu.policy.collection.pace=='balanced'
    assert emu.speed==4
    emu.store.set.assert_called_once()


def test_api_rejects_invalid_adventure_pace(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import pytest
    from fastapi import HTTPException
    from pokesim.web.app import create_app, Control
    emu=Mock()
    app=create_app(emu,SimpleNamespace(shots=tmp_path))
    endpoint=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/control')
    with pytest.raises(HTTPException) as error:
        endpoint(Control(action='adventure_pace',value='invalid'))
    assert error.value.status_code==400
    assert endpoint(Control(action='adventure_pace',value='thorough'))=={'ok':True}
    emu.command.assert_called_once_with('adventure_pace','thorough')


def test_evolution_project_does_not_block_restocking_at_another_mart():
    p=StrategicPolicy(7)
    parent=sid(44)
    p.collection.project={'method':'evolve','parent':parent,'species':sid(45),'evolution':EVOS[parent][0]}
    p.goal=Goal('collect_stone','Buy a stone','Evolve')
    s=state(map=MAPS['LAVENDER_MART'],money=10000)
    assert p._shopping_item(s,[ITEMS['SUPER_POTION']])==ITEMS['SUPER_POTION']
    s=replace(s,map=MAPS['CELADON_MART_4F'])
    assert p._shopping_item(s,[ITEMS['LEAF_STONE']])==ITEMS['LEAF_STONE']


def test_stone_vendor_goal_is_reachable_from_the_shop_floor():
    c=Collection()
    parent=sid(44)
    c.project={'method':'evolve','parent':parent,'species':sid(45),'evolution':EVOS[parent][0]}
    s=state(map=MAPS['CELADON_MART_4F'],x=12,y=2,party=(mon(species=parent),))
    goal=c.goal(s)
    nav=Navigator()
    nav.update_story(s)
    assert nav.route((s.map,s.x,s.y),goal.targets,s.frame) is not None
    assert goal.facing=='down'


def test_evolution_training_leaves_gym_without_competing_lead_swaps():
    from unittest.mock import Mock
    p=StrategicPolicy(7)
    parent=sid(17)
    p.collection.project={'method':'evolve','parent':parent,'species':sid(18),'evolution':EVOS[parent][0]}
    p.goal=Goal('collect_train','Train Pidgeotto','Evolution',((MAPS['ROUTE_1'],10,10),))
    p.collection.choose=Mock(return_value=p.goal)
    p.readiness={'lead':1}
    p.development_index=1
    p.development_until=10000
    s=state(map=MAPS['VIRIDIAN_GYM'],x=3,y=1,
            party=(mon(species=parent,level=33),mon(species=sid(3),level=57)),
            items=((ITEMS['POKE_BALL'],10),(ITEMS['SUPER_POTION'],5)))
    p.nav.update_story(s)
    p._social_interaction=Mock(return_value=None)
    action=p._overworld(s,bytearray(65536))
    assert p.intent is None
    assert action[0].button in ('up','down','left','right')
    s=replace(s,party=s.party[::-1])
    p._overworld(s,bytearray(65536))
    assert p.intent.kind=='reorder' and p.intent.index==1
