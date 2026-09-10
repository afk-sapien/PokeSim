import dataclasses

from pokesim.events import HIGH, LOW, MINIMAL, NORMAL, URGENT, Event, RunMemory, diff
from pokesim.notify import Ntfy
from pokesim.ram import DEX_NAMES, PartyMon, Snapshot, bcd, decode_text, flag_bits


def snap(**kw) -> Snapshot:
    base = dict(frame=0, map=1, x=5, y=5, badges=0, party=(PartyMon(0x99, 20, 20, 5, "BULBASAUR"),),  # 0x99 = Bulbasaur internal id
                owned=frozenset({1}), seen=frozenset({1}), money=3000, items=(), in_battle=0, battle_type=0,
                enemy_species=0, enemy_level=0, opponent=0, player_name="RED", rival_name="BLUE",
                playtime=(0, 5, 0), textbox=False, start_menu=False)
    base.update(kw)
    return Snapshot(**base)


def types(evs):
    return [e.type for e in evs]


def test_decode_helpers():
    assert decode_text(bytes([0x91, 0x84, 0x83, 0x50, 0x80])) == "RED"
    assert bcd(bytes([0x01, 0x23, 0x45])) == 12345
    assert flag_bits(bytes([0b101, 0b1])) == {1, 3, 9}


def test_first_snapshot_only_records():
    mem = RunMemory()
    assert diff(None, snap(), mem) == []
    assert mem.seen_maps == {1}


def test_catch_and_seen():
    mem = RunMemory(seen_maps={1})
    prev = snap(in_battle=1, enemy_species=0x54, enemy_level=3)  # Pikachu internal id 0x54
    cur = snap(in_battle=1, enemy_species=0x54, enemy_level=3, owned=frozenset({1, 25}), seen=frozenset({1, 25, 16}),
               party=prev.party + (PartyMon(0x54, 10, 10, 3, "PIKACHU"),))
    evs = diff(prev, cur, mem)
    assert types(evs) == ["catch", "seen"]
    assert evs[0].title == "Caught Pikachu!" and "level 3" in evs[0].body and evs[0].notable
    assert evs[0].priority == HIGH
    assert not evs[1].notable and evs[1].priority == MINIMAL


def test_legendary_catch_is_urgent():
    mem = RunMemory(seen_maps={1})
    prev = snap(in_battle=1, enemy_species=0x83, enemy_level=70)   # Mewtwo internal id 0x83
    cur = snap(in_battle=1, enemy_species=0x83, enemy_level=70, owned=frozenset({1, 150}), seen=frozenset({1, 150}))
    evs = diff(prev, cur, mem)
    assert types(evs) == ["catch"] and evs[0].priority == URGENT and "legendary Mewtwo" in evs[0].title


def test_evolution_suppresses_catch():
    mem = RunMemory(seen_maps={1})
    prev = snap(party=(PartyMon(0x99, 30, 30, 16, "BULBASAUR"),))
    cur = snap(party=(PartyMon(0x09, 35, 35, 16, "BULBASAUR"),), owned=frozenset({1, 2}), seen=frozenset({1, 2}))  # 0x09 = Ivysaur
    evs = diff(prev, cur, mem)
    assert types(evs) == ["evolve"]
    assert "evolved into Ivysaur" in evs[0].title and evs[0].priority == HIGH


def test_badge_levels_faint_blackout():
    mem = RunMemory(seen_maps={1})
    prev = snap(party=(PartyMon(0x99, 20, 20, 9, "BULBASAUR"), PartyMon(0x54, 5, 10, 8, "PIKACHU")))
    cur = snap(badges=0b1, party=(PartyMon(0x99, 20, 22, 10, "BULBASAUR"), PartyMon(0x54, 0, 10, 8, "PIKACHU")))
    evs = diff(prev, cur, mem)
    assert types(evs) == ["badge", "level", "faint"]
    assert evs[0].title.startswith("Beat Brock") and "Boulder" in evs[0].title and evs[0].priority == URGENT
    assert evs[1].notable and "level 10" in evs[1].title and evs[1].priority == NORMAL
    assert evs[2].priority == MINIMAL and not evs[2].notable
    dead = snap(party=(PartyMon(0x99, 0, 22, 10, "BULBASAUR"), PartyMon(0x54, 0, 10, 8, "PIKACHU")), in_battle=1,
                enemy_species=0x54)
    evs = diff(cur, dead, mem)
    assert types(evs) == ["blackout"] and evs[0].priority == LOW and evs[0].notable


def test_level_priorities():
    mem = RunMemory(seen_maps={1})
    for lvl, prio in ((11, MINIMAL), (20, NORMAL), (50, HIGH), (100, HIGH)):
        prev = snap(party=(PartyMon(0x99, 20, 20, lvl - 1, "BULBASAUR"),))
        cur = snap(party=(PartyMon(0x99, 20, 20, lvl, "BULBASAUR"),))
        evs = diff(prev, cur, mem)
        assert types(evs) == ["level"] and evs[0].priority == prio, lvl


def test_trainer_and_rival():
    mem = RunMemory(seen_maps={1})
    prev = snap(in_battle=2, opponent=200 + 0x19)      # RIVAL1
    evs = diff(prev, snap(), mem)
    assert types(evs) == ["trainer"] and evs[0].notable and "rival BLUE" in evs[0].title and evs[0].priority == HIGH
    prev = snap(in_battle=2, opponent=200 + 1)          # Youngster
    evs = diff(prev, snap(), mem)
    assert types(evs) == ["trainer"] and not evs[0].notable and evs[0].priority == MINIMAL
    prev = snap(in_battle=2, opponent=200 + 47)         # Lance
    evs = diff(prev, snap(), mem)
    assert types(evs) == ["trainer"] and evs[0].priority == URGENT and "Lance" in evs[0].title


def test_new_map_and_hall_of_fame():
    mem = RunMemory(seen_maps={1})
    evs = diff(snap(), snap(map=2), mem)
    assert types(evs) == ["map"] and evs[0].title == "Entered Pewter City"
    assert evs[0].priority == LOW and evs[0].notable
    assert diff(snap(map=2), snap(map=2), mem) == []
    evs = diff(snap(map=2), snap(map=118), mem)
    assert types(evs) == ["champion"] and evs[0].priority == URGENT


def test_key_item_money_playtime():
    mem = RunMemory(seen_maps={1})
    cur = snap(items=((0x06, 1), (0x14, 5)), money=12000, playtime=(10, 0, 1))   # 0x06 = Bicycle, 0x14 = potion
    evs = diff(snap(playtime=(9, 59, 59)), cur, mem)
    assert types(evs) == ["item", "money", "playtime"]
    assert evs[0].title == "Got the Bicycle" and evs[0].priority == HIGH
    assert evs[1].priority == MINIMAL and not evs[1].notable       # $10k is not worth a push
    assert evs[2].priority == LOW
    big = snap(money=120_000)
    evs = diff(snap(money=90_000), big, mem)
    assert types(evs) == ["money"] and evs[0].priority == NORMAL
    assert diff(cur, cur, mem) == []          # milestones fire once


def test_intro_and_glitch_are_silent():
    mem = RunMemory()
    intro = snap(player_name="", map=0, party=(), playtime=(0, 0, 0))
    assert diff(intro, intro, mem) == [] and mem.seen_maps == set()
    glitched = snap(map=0x39, in_battle=0x39)
    assert not glitched.valid
    assert diff(snap(), glitched, mem) == []


def test_validity():
    assert snap().valid
    assert not snap(in_battle=1, party=()).valid
    assert not snap(playtime=(0, 77, 0)).valid
    assert snap().started
    assert snap(player_name="").started
    assert not snap(player_name="", map=0, party=(), playtime=(0, 0, 0)).started


def test_transient_events_carry_a_confirmation_check():
    mem = RunMemory(seen_maps={1})
    prev = snap()
    cur = snap(owned=frozenset({1, 7}), seen=frozenset({1, 7}))   # Squirtle bit flickers on
    evs = diff(prev, cur, mem)
    assert types(evs) == ["obtain"] and evs[0].still is not None
    assert evs[0].still(cur) and not evs[0].still(prev)           # gone again next snapshot -> dropped
    dead = snap(party=(PartyMon(0x99, 0, 20, 5, "BULBASAUR"),))
    ev = diff(prev, dead, mem)[0]
    assert ev.type == "blackout" and ev.still(dead) and not ev.still(prev)


def test_ntfy_filter():
    n = Ntfy("http://example.invalid/topic", min_priority=3, mute={"level"})
    assert n.wants(Event("catch", "x", priority=HIGH))
    assert not n.wants(Event("map", "x", priority=LOW))
    assert not n.wants(Event("level", "x", priority=NORMAL))        # muted type
    assert Ntfy("u").wants(Event("seen", "x", priority=MINIMAL))    # defaults: everything


def test_notable_derives_from_priority():
    assert Event("x", "t", priority=LOW).notable
    assert not Event("x", "t", priority=MINIMAL).notable
    assert Event("x", "t", priority=MINIMAL, notable=True).notable


def test_party_reordering_never_reports_evolution():
    first=PartyMon(0x99,30,30,16,'SPROUT')
    second=PartyMon(0x09,40,40,20,'LEAF')
    prev=snap(party=(first,second))
    cur=snap(party=(second,first))
    assert 'evolve' not in types(diff(prev,cur,RunMemory()))
    partial=snap(party=(second,second))
    assert 'evolve' not in types(diff(prev,partial,RunMemory()))


def test_unrelated_party_replacement_is_not_an_evolution():
    prev=snap(party=(PartyMon(0x99,30,30,16,'BUDDY'),))
    cur=snap(party=(PartyMon(0x54,30,30,16,'BUDDY'),))
    assert 'evolve' not in types(diff(prev,cur,RunMemory()))
