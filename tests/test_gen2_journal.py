"""Gen II journal entries that match the ones Red, Blue and Yellow write."""
from types import SimpleNamespace

from pokesim.app.notifications import CATEGORIES
from pokesim.gen2 import journal
from pokesim.gen2.emulator import Event

DATA = SimpleNamespace(
    species={16: {'name': 'Pidgey'}, 19: {'name': 'Rattata'}, 245: {'name': 'Suicune'}, 152: {'name': 'Chikorita'}},
    items={f'HM{i:02d}': 200 + i for i in range(1, 8)},
    item_names={7: 'Bicycle', 201: 'HM01', 3: 'Potion'})


def mon(species=152, hp=20, nick='CHIKORITA', egg=False):
    return SimpleNamespace(species=species, name='Chikorita', nick=nick, hp=hp, trainer_id=1, dvs=(1, 2, 3, 4),
                           egg=egg, level=10)


def snap(**changes):
    base = dict(valid=True, started=True, seen=frozenset({152}), owned=frozenset({152}), party=(mon(),),
                in_battle=0, trainer_class=0, enemy_species=0, enemy_level=0, rival_name='???', money=3000,
                playtime=(1, 0, 0), badges=0, map_name='New Bark Town', pockets={'key': (), 'machines': ()})
    base.update(changes)
    party = base['party']
    base['all_fainted'] = bool(party) and not any(m.hp and not m.egg for m in party)
    return SimpleNamespace(**base)


def run(before, after, history=None):
    return journal.events(before, after, {} if history is None else history, DATA, Event)


def category(event):
    for key, _, _, _, rows in CATEGORIES:
        if any(event.type == kind and event.priority >= low for kind, low in rows):
            return key
    return 'other'


def test_nothing_without_an_earlier_snapshot():
    assert run(None, snap(seen=frozenset({16, 152}))) == []


def test_first_sighting_is_a_timeline_entry():
    [event] = run(snap(), snap(seen=frozenset({16, 152})))
    assert (event.type, event.title, event.priority, event.notable) == ('seen', 'Saw Pidgey for the first time', 1, False)


def test_a_catch_is_not_also_a_sighting():
    assert run(snap(), snap(seen=frozenset({16, 152}), owned=frozenset({16, 152}))) == []


def test_faint_and_blackout():
    [faint] = run(snap(party=(mon(), mon(hp=5))), snap(party=(mon(), mon(hp=0))))
    assert (faint.type, faint.title, faint.notable) == ('faint', 'Chikorita fainted', False)
    [blackout] = run(snap(party=(mon(hp=3),), in_battle=1, enemy_species=19),
                     snap(party=(mon(hp=0),), in_battle=1, enemy_species=19))
    assert blackout.type == 'blackout' and blackout.body == 'The whole party fainted on New Bark Town fighting a Rattata.'
    assert category(blackout) == 'blackouts'


def test_trainer_wins_by_rank():
    win = lambda tc, **kw: run(snap(in_battle=2, trainer_class=tc, **kw), snap(**kw))
    [karen] = win(14)
    assert (karen.title, karen.priority, category(karen)) == ('Defeated Karen', 5, 'league')
    [falkner] = win(1)
    assert (falkner.title, falkner.priority, category(falkner)) == ('Defeated Falkner', 4, 'trainers')
    [rival] = win(9, rival_name='SILVER')
    assert rival.title == 'Defeated rival SILVER'
    [youngster] = win(22)
    assert (youngster.title, youngster.priority, youngster.notable) == ('Defeated Youngster', 1, False)


def test_a_lost_trainer_battle_is_not_a_win():
    assert run(snap(in_battle=2, trainer_class=9, party=(mon(hp=0),)), snap(party=(mon(hp=0),))) == []


def test_key_items_and_hms_but_not_tms_or_potions():
    events = run(snap(), snap(pockets={'key': ((7, 1),), 'machines': ((201, 1), (150, 1))}))
    assert [e.title for e in events] == ['Got the Bicycle', 'Got the HM01']
    assert {category(e) for e in events} == {'exploration'}
    assert run(snap(pockets={'key': ((7, 1),), 'machines': ()}), snap(pockets={'key': ((7, 1),), 'machines': ()})) == []


def test_money_and_playtime_milestones_once():
    history = {}
    [money] = run(snap(money=9000), snap(money=12000), history)
    assert money.title == 'Wallet passed $10,000' and history['money_milestones'] == [10000]
    assert run(snap(money=9000), snap(money=12000), history) == []
    [hours] = run(snap(playtime=(9, 59, 59)), snap(playtime=(10, 0, 0)), history)
    assert hours.title == '10 hours of play time' and category(hours) == 'other'
    assert run(snap(playtime=(9, 59, 59)), snap(playtime=(10, 0, 0)), history) == []


def test_rival_name_after_the_placeholder():
    [event] = run(snap(rival_name='???'), snap(rival_name='SILVER'))
    assert event.title == 'The rival is named SILVER'
    assert run(snap(rival_name=''), snap(rival_name='???')) == []


def test_legendary_catch_is_urgent():
    before = snap(in_battle=1, enemy_species=245, enemy_level=40)
    event = journal.catch(DATA, 245, before, replace_owned(before, {152, 245}), Event)
    assert (event.title, event.priority, category(event)) == ('Caught the legendary Suicune!', 5, 'legendary')
    assert event.body == 'A level 40 Suicune on New Bark Town. Pokédex: 2 owned.'
    ordinary = journal.catch(DATA, 16, before, before, Event)
    assert (ordinary.title, ordinary.priority, category(ordinary)) == ('Pidgey joined the Pokédex', 4, 'pokedex')


def test_a_traded_legendary_is_not_a_catch():
    event = journal.catch(DATA, 245, snap(), snap(), Event)
    assert (event.title, event.priority) == ('Suicune joined the Pokédex', 4)


class Recorder:
    def __init__(self):
        self.checkpoints, self.pushed, self.rows = [], [], []

    def add_event(self, event, snapshot, shot, state):
        self.rows.append((event.type, state))
        return len(self.rows)

    def write_checkpoint(self, state, manifest, name=None):
        self.checkpoints.append(name)

    def event(self, eid):
        return {'id': eid}


def test_timeline_entries_keep_no_save_and_are_not_pushed_or_progress():
    from pokesim.gen2.emulator import Emulator
    store = Recorder()
    ntfy = SimpleNamespace(wants=lambda event: True, send=lambda *a, **k: store.pushed.append(a[0]))
    emu = SimpleNamespace(store=store, ntfy=ntfy, last_achievement=None, _shot_png=lambda: b'png',
                          _state_bytes=lambda: b'state', _manifest=lambda: {})
    Emulator._event(emu, Event('badge', 'Earned the Zephyr Badge', priority=5), snap())
    Emulator._event(emu, Event('faint', 'Chikorita fainted', priority=1, notable=False), snap())
    assert store.rows == [('badge', b'state'), ('faint', None)]
    assert store.checkpoints == ['event-1.state'] and store.pushed == ['Earned the Zephyr Badge']
    assert emu.last_achievement == {'id': 1}


def replace_owned(s, owned):
    return SimpleNamespace(**{**vars(s), 'owned': frozenset(owned)})

