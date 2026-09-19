"""Run the real cartridge cable matrix against private, disposable test fixtures."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

from pokesim.interactions.cable import CableError, CableSide, checked
from pokesim.interactions.cable_driver import CableDriver
from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan, run_session
from pokesim.interactions.verification import party


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roms', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    def side(name, edition, slot=0):
        return CableParticipant(name, str(args.roms / f'poke{edition}.gbc'),
            str(args.fixtures / f'{edition}.state'), str(args.fixtures / f'{edition}.sav'), party_slot=slot)
    cases = []
    for left, right in [('red', 'blue'), ('red', 'red'), ('blue', 'blue')]:
        for reverse in (False, True):
            cases.append((f'{left}-{right}-{int(reverse)}', left, right, 0, 0, reverse))
    for slot in range(6):
        cases.append((f'slots-{slot}-{5-slot}', 'red', 'blue', slot, 5-slot, False))
    report = {'status': 'passed', 'cases': {}}
    for name, left, right, left_slot, right_slot, reverse in cases:
        started = time.monotonic()
        plan = CableSessionPlan(name, 'attempt-1', side('left', left, left_slot),
            side('right', right, right_slot), external_left=reverse, speed=0, timeout_seconds=60)
        result = run_session(plan, args.out / name)
        report['cases'][name] = {'status': result['status'],
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'adapter_id': result['adapter_id'],
            'sides': {key: row['evidence'] for key, row in result['participants'].items()}}
        print(name, 'passed', flush=True)
    plan = CableSessionPlan('no-cable', 'attempt-1', side('left', 'red'), side('right', 'blue'),
                             speed=0, timeout_seconds=60, max_steps=200)
    sides = [CableSide(plan.left), CableSide(plan.right)]
    try:
        sides[0].peer, sides[1].peer = sides[1], sides[0]
        before = [party(endpoint.pb, endpoint.sym) for endpoint in sides]
        for i, endpoint in enumerate(sides):
            endpoint.attach(i + 1, enabled=False)
        driver = CableDriver(sides, plan)
        driver.enter()
        try:
            driver.exchange()
        except CableError:
            pass
        else:
            raise CableError('Trade incorrectly succeeded with disconnected cable')
        checked(all(not endpoint.counts['TradeCenter_Trade'] and party(endpoint.pb, endpoint.sym) == old
                    for endpoint, old in zip(sides, before)), 'Disconnected cable changed party')
        report['negative_control'] = {'status': 'passed', 'parties_unchanged': True, 'trades': 0}
    finally:
        for endpoint in sides:
            endpoint.stop()
    (args.out / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'cases': len(cases), 'negative_control': 'passed'}))


if __name__ == '__main__':
    main()
