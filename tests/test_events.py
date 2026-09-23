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
    assert flag_bits(b"") == set()
    assert flag_bits(bytes(4)) == set()
    assert flag_bits(b"\xff\xff") == set(range(1, 17))


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

def test_a_withdrawal_caught_mid_commit_is_not_reported_as_a_release():
    # The box slot clears a few frames before the party grows, so the in-between snapshot looks
    # like a release. The guard only lets it through if the population stays down afterwards.
    mem = RunMemory(seen_maps={1})
    prev = snap(stored_pokemon=((0, 0x54, 9, 'PIKA'), (0, 0x99, 3, '')), box_counts=(2,) + (0,) * 11)
    midway = snap(stored_pokemon=((0, 0x99, 3, ''),), box_counts=(1,) + (0,) * 11)
    evs = diff(prev, midway, mem)
    assert types(evs) == ['release']
    landed = snap(party=midway.party + (PartyMon(0x54, 10, 10, 9, 'PIKA'),),
                  stored_pokemon=midway.stored_pokemon, box_counts=(1,) + (0,) * 11)
    assert not evs[0].still(landed), 'the party gained it, so nothing was released'

    # A real release keeps the population down.
    assert evs[0].still(midway)


def test_party_first_withdrawal_is_not_a_release_after_checkpoint():
    before = snap(frame=100, stored_pokemon=((0, 0x83, 70, 'YELLMAN'),))
    midway = dataclasses.replace(before, frame=130,
        party=before.party + (PartyMon(0x83, 200, 200, 70, 'YELLMAN'),))
    memory = RunMemory(seen_maps={1})
    assert 'release' not in types(diff(before, midway, memory))
    memory = RunMemory.from_dict(memory.to_dict())
    after = dataclasses.replace(midway, frame=160, stored_pokemon=())
    assert 'release' not in types(diff(midway, after, memory))
    assert memory.party_arrivals == []


def test_withdrawal_credit_does_not_hide_another_individuals_release():
    before = snap(frame=100, stored_pokemon=((0, 0x54, 9, 'PIKA'), (0, 0x54, 5, 'SPARE')))
    midway = dataclasses.replace(before, frame=130,
        party=before.party + (PartyMon(0x54, 10, 10, 9, 'PIKA'),))
    memory = RunMemory(seen_maps={1})
    diff(before, midway, memory)
    after = dataclasses.replace(midway, frame=160, stored_pokemon=())
    releases = [e for e in diff(midway, after, memory) if e.type == 'release']
    assert len(releases) == 1
    assert releases[0].still(after)


def test_old_or_rewound_arrivals_cannot_suppress_real_release():
    for observed_at in (0, 2000):
        memory = RunMemory(seen_maps={1}, party_arrivals=[[observed_at, 0x54, 'PIKA', 1]])
        before = snap(frame=1000, stored_pokemon=((0, 0x54, 9, 'PIKA'),))
        after = dataclasses.replace(before, frame=1030, stored_pokemon=())
        releases = [e for e in diff(before, after, memory) if e.type == 'release']
        assert len(releases) == 1
        assert releases[0].still(after)


def test_release_confirmation_tracks_individual_instead_of_total_population():
    before = snap(stored_pokemon=((0, 0x54, 9, 'PIKA'), (0, 0x99, 3, 'BUD')))
    midway = dataclasses.replace(before, stored_pokemon=((0, 0x99, 3, 'BUD'),))
    release = next(e for e in diff(before, midway, RunMemory()) if e.type == 'release')
    landed = dataclasses.replace(midway, stored_pokemon=(),
        party=midway.party + (PartyMon(0x54, 10, 10, 9, 'PIKA'),))
    assert not release.still(landed)


def test_redeposit_cancels_arrival_credit_before_real_release():
    boxed = snap(frame=100, stored_pokemon=((0, 0x54, 9, 'PIKA'),))
    party = dataclasses.replace(boxed, frame=130, stored_pokemon=(),
        party=boxed.party + (PartyMon(0x54, 10, 10, 9, 'PIKA'),))
    memory = RunMemory(seen_maps={1}, party_arrivals=[[120, 0x54, 'PIKA', 1]])
    deposited = dataclasses.replace(boxed, frame=160)
    diff(party, deposited, memory)
    assert memory.party_arrivals == []
    released = dataclasses.replace(deposited, frame=190, stored_pokemon=())
    assert 'release' in types(diff(deposited, released, memory))


def test_pokemon_on_the_naming_screen_is_not_a_blackout():
    """AddPartyMon counts a new Pokémon before it writes the struct at wPartyMons.

    For as long as the nickname screen is up the slot reads as species 0 with no HP,
    which used to look like a party that had fainted on the way out of Oak's lab.
    """
    mem = RunMemory(seen_maps={1})
    empty = snap(party=(), owned=frozenset(), seen=frozenset())
    naming = snap(party=(PartyMon(0, 0, 0, 0, ""),), owned=frozenset(), seen=frozenset())
    assert not naming.all_fainted
    assert types(diff(empty, naming, mem)) == []
    named = snap(party=(PartyMon(0x99, 19, 19, 5, "BULBASAUR"),), owned=frozenset({1}), seen=frozenset({1}))
    assert types(diff(naming, named, mem)) == ["obtain"]


def test_a_pending_slot_does_not_hide_a_real_blackout():
    mem = RunMemory(seen_maps={1})
    prev = snap(party=(PartyMon(0x99, 20, 20, 9, "BULBASAUR"),))
    cur = snap(party=(PartyMon(0x99, 0, 20, 9, "BULBASAUR"), PartyMon(0, 0, 0, 0, "")))
    assert cur.all_fainted
    assert types(diff(prev, cur, mem)) == ["blackout"]


def test_pending_slot_is_labelled_rather_than_named_after_species_zero():
    mon = PartyMon(0, 0, 0, 0, "")
    assert mon.pending and mon.name == "Joining the team"
    assert not PartyMon(0x99, 20, 20, 5, "BULBASAUR").pending
    entry = snap(party=(mon,)).to_dict()["party"][0]
    assert entry["pending"] is True


def test_owned_without_seen_is_not_pokedex_data():
    """Oak's lab leaves other values where the Pokédex flags will later live.

    The cartridge always sets the seen flag alongside the owned flag, so a read with
    owned entries and no matching seen entries is a half-initialised region, not four
    free starters.
    """
    from pokesim.ram import W_DEX_OWNED, W_DEX_SEEN, read_snapshot

    mem = bytearray(0x10000)
    mem[W_DEX_OWNED] = 0b01001011           # dex 1, 2, 4 and 7, exactly what Oak's lab leaves
    assert read_snapshot(mem, 0).owned == frozenset()
    mem[W_DEX_SEEN] = 0b00000001            # once Bulbasaur is genuinely registered
    snapshot = read_snapshot(mem, 0)
    assert snapshot.owned == frozenset({1}) and snapshot.seen == frozenset({1})

