"""Exercise the postgame director on a private champion save without changing cartridge RAM.

Collection errands are bypassed so each version can exercise the director independently of its
remaining Pokédex work. Start a real shiny outing, restart during its fiftieth encounter, and let
the director choose subsequent activities. Receipts distinguish bounded checks from full campaigns.
"""
import argparse
import hashlib
import json
from pathlib import Path

from pokecore.gen2.clock import boot, follow_game_time
from pokecore.gen2.ram import Memory, read_snapshot

from pokesim.gen2 import postgame
from pokesim.gen2.data import GameData
from pokesim.gen2.policy import Goal, Policy
from pokesim.gen2.world import update


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--game', choices=('gold', 'silver', 'crystal'), required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--load', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=2000000)
    parser.add_argument('--hunt-map', help='Pin the first outing to a real grass map for encounter-count checks')
    parser.add_argument('--first-outing-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = GameData.load(args.data, args.game)
    initialized = False

    def open_game(path):
        game = boot(str(args.rom), sound=True)
        with path.open('rb') as stream:
            game.load_state(stream)
        follow_game_time(game)
        game.set_emulation_speed(0)
        return game

    def make_policy(saved=None):
        controller = Policy(data, seed=1)
        if saved:
            controller.load_state_dict(saved)

        def focused(snapshot, mem):
            from pokesim.gen2.collection import league_funding
            if not initialized or not snapshot.can_catch:
                goal = controller.storage_goal(snapshot)
                return Goal('collection_box', 'Prepare a receiving box', goal.map_name, goal.x, goal.y, goal.face)
            loop = controller.collection.get('league_loop')
            if loop is not None and snapshot.hall_of_fame_count < loop:
                return league_funding(controller, snapshot, Goal, again=True)
            controller.collection.pop('league_loop', None)
            current = ('morning', 'day', 'night')[min(2, mem.byte('wTimeOfDay'))]
            goal = postgame.journey(controller, snapshot, mem, Goal, current)
            return goal or Goal('collection_wait', 'No postgame activity available',
                                data.maps[snapshot.map]['constant'], snapshot.x, snapshot.y)

        controller.journey = focused
        return controller

    pb = open_game(args.load)
    policy = make_policy()
    frame, restarted, outing_done = 0, False, False
    completed_activities = 0
    transitions, training = [], []
    receipt = {'game': args.game, 'scope': 'focused postgame director with collection errands bypassed',
               'source_sha256': hashlib.sha256(args.load.read_bytes()).hexdigest()}
    try:
        snapshot = read_snapshot(pb.memory, data, frame)
        if not snapshot.valid or not snapshot.hall_of_fame_count:
            raise ValueError('A valid champion checkpoint is required')
        policy.completed['champion'] = 0
        policy.memory = pb.memory
        update(policy.nav.regions, snapshot)
        first = None
        previous = None
        while frame < args.frames:
            snapshot = read_snapshot(pb.memory, data, frame)
            ready = (snapshot.valid and not snapshot.in_battle and policy.menu is None
                     and not Memory(pb.memory, data).byte('wScriptRunning') and '┌' not in snapshot.tiles[12])
            if not initialized and ready and snapshot.can_catch and postgame.balls(policy, snapshot) >= postgame.HUNT_BALLS:
                current = ('morning', 'day', 'night')[min(2, Memory(pb.memory, data).byte('wTimeOfDay'))]
                first = postgame.shiny(policy, snapshot, current)
                if first is None:
                    raise ValueError('No reachable shiny outing is available')
                if args.hunt_map:
                    mid = data.map_ids[args.hunt_map]
                    if not any(row['map'] == mid and row['method'] == 'grass' for row in data.encounters):
                        raise ValueError('The requested hunt map has no grass encounters')
                    first['row']['map'] = mid
                    receipt['first_hunt_map'] = args.hunt_map
                postgame.state(policy)['activity'] = first
                postgame.state(policy)['recent'] = ['shiny']
                initialized = True
            before = postgame.state(policy)['activity']
            action = policy.step(snapshot, pb.memory)
            activity = postgame.state(policy)['activity']
            marker = ((activity or {}).get('kind'), repr(activity and activity.get('identity')),
                      (activity or {}).get('started'), (activity or {}).get('level_goal'))
            if marker != previous:
                transitions.append({'frame': frame, 'kind': marker[0], 'previous_encounters': (before or {}).get('encounters'),
                                    'shiny_break': postgame.state(policy)['shiny_break'], 'map': snapshot.map_name,
                                    'can_catch': snapshot.can_catch, 'balls': postgame.balls(policy, snapshot),
                                    'shinies': sum(mon.shiny for mon in postgame.held(snapshot))})
                print(transitions[-1], flush=True)
                previous = marker
                if outing_done and before and before is not activity and before['kind'] != 'shiny':
                    completed_activities += 1
                    if before['kind'] == 'train':
                        trained = next((mon for mon in postgame.held(snapshot)
                                        if postgame.ident(mon) == before['identity']), None)
                        if trained and training:
                            training[-1]['end_level'] = trained.level
                            training[-1]['goal_reached'] = trained.level >= before['level_goal']
                if activity and activity['kind'] == 'train':
                    copies = [mon for mon in postgame.held(snapshot) if mon.species == activity['species']]
                    chosen = next(mon for mon in copies if postgame.ident(mon) == activity['identity'])
                    assert postgame.potential(data, chosen) == max(postgame.potential(data, mon) for mon in copies)
                    training.append({'species': chosen.species, 'start_level': chosen.level,
                                     'goal': activity['level_goal'], 'best_potential': True})
            if first and not outing_done and before is first and activity is not first:
                outing_done = True
                receipt['first_outing'] = {'encounters': first['encounters'], 'frames': frame,
                                           'battle_finished': not snapshot.in_battle}
                if args.first_outing_only:
                    break
            if outing_done and activity and activity['kind'] == 'shiny':
                receipt['next_shiny_frame'] = frame
                break
            if completed_activities >= 2 and postgame.state(policy)['shiny_break'] == 0:
                receipt['rotation_passed'] = True
                break
            if first and not restarted and activity is first and first['encounters'] >= 50:
                path = args.output / 'restart.state'
                with path.open('wb') as stream:
                    pb.save_state(stream)
                saved = json.loads(json.dumps(policy.state_dict()))
                (args.output / 'restart.policy.json').write_text(json.dumps(saved))
                pb.stop(save=False)
                pb = open_game(path)
                policy = make_policy(saved)
                first = postgame.state(policy)['activity']
                restored = read_snapshot(pb.memory, data, frame)
                count = first['encounters']
                postgame.observe(policy, restored)
                assert first['encounters'] == count
                assert restored.party == snapshot.party
                receipt['restart'] = {'frame': frame, 'encounters': count, 'battle_latch_preserved': True,
                                      'party_preserved': True}
                restarted = True
                continue
            if action.button:
                pb.button_press(action.button)
            if action.hold:
                pb.tick(action.hold, True)
            if action.button:
                pb.button_release(action.button)
            if action.gap:
                pb.tick(action.gap, True)
            frame += action.hold + action.gap
        receipt.update(frames=frame, transitions=transitions, training=training,
                       restart_passed=restarted, first_outing_finished=outing_done)
        receipt['passed'] = bool(restarted and receipt.get('first_outing', {}).get('encounters') == 100
                                 and (args.first_outing_only or receipt.get('rotation_passed')
                                      or receipt.get('next_shiny_frame')))
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        with (args.output / 'final.state').open('wb') as stream:
            pb.save_state(stream)
        (args.output / 'final.policy.json').write_text(json.dumps(policy.state_dict()))
        pb.screen.image.save(args.output / 'final.png')
        print(json.dumps(receipt, indent=2))
    finally:
        pb.stop(save=False)
    if not receipt.get('passed'):
        raise SystemExit('Postgame checks did not all pass within the frame budget')


if __name__ == '__main__':
    main()
