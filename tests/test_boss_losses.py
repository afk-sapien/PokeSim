"""A loss to a boss raises the level the best fighter trains to before the next try, in both generations."""
from types import SimpleNamespace

from pokesim.planning.losses import Losses, best_level
from pokesim.planning.readiness import Boss, loss_bar
from pokesim.play_clock import PlayClock
from pokesim.policies.progression import boss_training
from pokesim.policies.strategic import StrategicPolicy
from pokesim.runtime.supervision import Supervisor
from pokesim.store import Store
from pokesim.strategy_data import MAPS
from test_events import snap
from test_strategy import mon

TACKLE, HARDEN = 33, 106


def test_only_a_pokemon_with_a_damaging_move_is_a_fighter():
    power = {TACKLE: 35}.get
    party = (SimpleNamespace(level=13, moves=(HARDEN, 0)), SimpleNamespace(level=9, moves=(TACKLE,)),
             SimpleNamespace(level=30, egg=True, moves=(TACKLE,)))
    assert best_level(party, power) == 9
    assert best_level(party[:1], power) == 0


def test_a_bar_rises_two_over_the_level_that_lost_up_to_ten_over_the_ace():
    losses, falkner = Losses(), Boss('zephyr', 9, floor=12)
    assert loss_bar(falkner, losses) == 12
    losses.note('zephyr', 12)
    losses.note('zephyr', 11)
    assert loss_bar(falkner, losses) == 14
    losses.note('zephyr', 30)
    assert loss_bar(falkner, losses) == 19


def test_a_gen1_level_cap_counts_only_fighters():
    # A Lv 30 Metapod with only Harden left a Lv 12 starter's cap met: Brock's gym took the team in.
    party = (mon(level=12), mon(level=60, moves=(HARDEN, 0, 0, 0), pp=(30, 0, 0, 0)))
    s = snap(map=MAPS['ROUTE_24'], badges=1, party=party)
    assert boss_training(s, SimpleNamespace(key='cascade'), Losses()).key == 'train_cascade'


def test_a_gen1_loss_to_misty_trains_on_her_route_and_outlives_the_reload(tmp_path):
    store = Store(tmp_path)
    policy = StrategicPolicy(1)
    store.attach(policy, 1)
    party = (mon(level=24, hp=0),)
    policy.goal = SimpleNamespace(key='cascade')
    policy.note_boss_loss(snap(map=MAPS['CERULEAN_GYM'], badges=1, party=party))
    # A blackout on the way is no loss to Misty.
    policy.goal = SimpleNamespace(key='thunder')
    policy.note_boss_loss(snap(map=MAPS['ROUTE_6'], badges=3, party=party))
    reloaded = StrategicPolicy(1)
    store.attach(reloaded, 1)
    assert reloaded.losses.levels() == {'cascade': 24}
    s = snap(map=MAPS['CERULEAN_CITY'], badges=1, party=(mon(level=25),))
    goal = boss_training(s, SimpleNamespace(key='cascade'), reloaded.losses)
    assert goal.key == 'train_cascade' and 'level 26' in goal.reason
    # At the bar the matchup rule judges next, and a fighter that matches up with Starmie goes in.
    ready = mon(level=26, hp=60, max_hp=60, attack=40, defense=40, special=55)
    assert boss_training(snap(map=MAPS['CERULEAN_CITY'], badges=1, party=(ready,)),
                         SimpleNamespace(key='cascade'), reloaded.losses) is None
    store.close()


def test_a_loss_saved_while_training_for_brock_loads_under_the_new_key(tmp_path):
    # Red, Blue and Yellow trained for Brock under 'train_brock' before every gym trained under
    # 'train_' and its key. A loss to the rival on Route 22 during that walk noted the old key.
    store = Store(tmp_path)
    store.set('boss_losses', {'train_brock': 12, 'cascade': 24})
    store.set('boss_aces', {'train_brock': 9})
    policy = StrategicPolicy(1)
    store.attach(policy, 1)
    assert policy.losses.levels() == {'train_boulder': 12, 'cascade': 24}
    assert policy.losses.aces() == {'train_boulder': 9}
    # The bar the old loss raised holds under the new key: Lv 13 trains, Lv 14 goes on.
    goal = SimpleNamespace(key='train_boulder', title='Prepare for Brock')
    assert boss_training(snap(map=MAPS['ROUTE_2'], party=(mon(level=13),)), goal, policy.losses)
    assert boss_training(snap(map=MAPS['ROUTE_2'], party=(mon(level=14),)), goal, policy.losses) is None
    # A new loss on the walk raises the renamed bar, and the store then keeps only the new key.
    policy.losses.note('train_boulder', 13)
    assert store.get('boss_losses') == {'train_boulder': 13, 'cascade': 24}
    store.close()


def test_an_old_and_a_new_key_for_one_boss_keep_the_higher_level():
    losses = Losses()
    losses._write('boss_losses', {'train_brock': 15, 'train_boulder': 12})
    assert losses.levels() == {'train_boulder': 15}
    losses._write('boss_losses', {'train_boulder': 16, 'train_brock': 12})
    assert losses.levels() == {'train_boulder': 16}


def test_a_gen1_stall_reload_inside_a_boss_battle_counts_as_a_loss_and_the_team_trains(tmp_path):
    # A battle with Misty that only ran long reloaded with no one fainted. Without a loss noted the
    # reload went straight back into the same fight.
    from pokesim.emulator import Emulator
    from pokesim.checkpoints import CheckpointStore
    saves = CheckpointStore(tmp_path / 'saves')
    saves.write_checkpoint(b'before', {'policy_state': {}, 'run_memory': {}})
    store = Store(tmp_path)
    policy = StrategicPolicy(1)
    store.attach(policy, 1)
    policy.goal = SimpleNamespace(key='cascade')
    restored = []
    game = SimpleNamespace(store=SimpleNamespace(autosaves=saves.autosaves, state_path=saves.state_path,
                                                 checkpoint_metadata=saves.checkpoint_metadata), reloads=0, frame=0,
                           policy=policy, snapshot=snap(map=MAPS['CERULEAN_GYM'], badges=1, in_battle=2,
                                                        party=(mon(level=24, hp=30),)),
                           _restore_first_valid=lambda paths: restored.append(paths[0].name), _tick=lambda n: None,
                           _behind_barrier=lambda metadata: False,
                           play_clock=PlayClock(), adventure_seed=7, supervisor=Supervisor())
    Emulator._unstick(game, 0, 'battle never ended')
    assert restored and policy.losses.levels() == {'cascade': 24}
    # The reload builds a new policy from the store, and its next goal trains before Misty.
    reloaded = StrategicPolicy(1)
    store.attach(reloaded, 1)
    s = snap(map=MAPS['CERULEAN_CITY'], badges=1, party=(mon(level=24),))
    assert boss_training(s, SimpleNamespace(key='cascade'), reloaded.losses).key == 'train_cascade'
    # A stall in a battle with a trainer outside the gym is no loss.
    other = StrategicPolicy(1)
    other.goal = SimpleNamespace(key='cascade')
    game.policy, game.snapshot = other, snap(map=MAPS['ROUTE_24'], badges=1, in_battle=2, party=(mon(level=24),))
    Emulator._unstick(game, 0, 'battle never ended')
    assert other.losses.levels() == {}
    store.close()


def test_a_gen1_stall_reload_in_a_rival_battle_counts_against_the_goal_under_way(tmp_path):
    # The rival fights on the S.S. Anne, no gym, so the trainer, not the room, names the boss.
    from pokesim.emulator import Emulator
    from pokesim.checkpoints import CheckpointStore
    saves = CheckpointStore(tmp_path / 'saves')
    saves.write_checkpoint(b'before', {'policy_state': {}, 'run_memory': {}})
    policy = StrategicPolicy(1)
    goal = SimpleNamespace(key='cut', title='Visit the ship’s captain')
    policy.goal = goal
    rival = snap(map=MAPS['SS_ANNE_2F'], badges=3, in_battle=2, opponent=200 + 42, enemy_level=20,
                 party=(mon(level=18, hp=30),))
    game = SimpleNamespace(store=SimpleNamespace(autosaves=saves.autosaves, state_path=saves.state_path,
                                                 checkpoint_metadata=saves.checkpoint_metadata), reloads=0, frame=0,
                           policy=policy, snapshot=rival, _restore_first_valid=lambda paths: None, _tick=lambda n: None,
                           _behind_barrier=lambda metadata: False,
                           play_clock=PlayClock(), adventure_seed=7, supervisor=Supervisor())
    Emulator._unstick(game, 0, 'battle never ended')
    assert policy.losses.levels() == {'cut': 18} and policy.losses.aces() == {'cut': 20}
    # The next goal trains on the route before Lt. Surge, the next gym, until the best fighter is Lv 20.
    s = snap(map=MAPS['VERMILION_CITY'], badges=3, party=(mon(level=19),))
    training = boss_training(s, goal, policy.losses)
    assert training.key == 'train_cut' and 'level 20' in training.reason
    assert MAPS['ROUTE_11'] in {target[0] for target in training.targets}
    assert boss_training(snap(map=MAPS['VERMILION_CITY'], badges=3, party=(mon(level=20),)), goal, policy.losses) is None
    # A stall against a Youngster on the way is no loss.
    other = StrategicPolicy(1)
    other.goal = goal
    game.policy, game.snapshot = other, snap(map=MAPS['ROUTE_6'], badges=3, in_battle=2, opponent=200 + 1,
                                             enemy_level=20, party=(mon(level=18, hp=30),))
    Emulator._unstick(game, 0, 'battle never ended')
    assert other.losses.levels() == {}


def test_a_gen1_loss_right_after_a_reload_into_the_battle_counts_by_the_room():
    # A reload into the battle leaves no boss goal yet, so the gym names the boss.
    policy = StrategicPolicy(1)
    policy.goal = None
    policy.note_boss_loss(snap(map=MAPS['CERULEAN_GYM'], badges=1, party=(mon(level=25, hp=0),)))
    policy.note_boss_loss(snap(map=MAPS['ROUTE_24'], badges=1, party=(mon(level=30, hp=0),)))
    assert policy.losses.levels() == {'cascade': 25}


def test_the_gen1_league_rooms_share_one_bar_and_never_turn_back():
    losses = Losses()
    policy = StrategicPolicy(1)
    policy.losses = losses
    policy.goal = SimpleNamespace(key='league_agatha')
    policy.note_boss_loss(snap(map=MAPS['LANCES_ROOM'], badges=255, party=(mon(level=58, hp=0),)))
    assert losses.levels() == {'league': 58}
    lobby = snap(map=MAPS['INDIGO_PLATEAU_LOBBY'], badges=255, party=(mon(level=59),))
    assert boss_training(lobby, SimpleNamespace(key='league_lorelei'), losses).key == 'train_league'
    room = snap(map=MAPS['BRUNOS_ROOM'], badges=255, party=(mon(level=59),))
    assert boss_training(room, SimpleNamespace(key='league_bruno'), losses) is None
