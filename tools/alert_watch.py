"""Turn each new main-page alert of a hosted PokeSim app into a task, so nobody has to spot it.

    ssh HOST "docker exec CONTAINER cat /data/watchdog-problems.json" \\
        | python3 tools/alert_watch.py STATE_JSON [COMMAND...]

The app's watchdog keeps the problems the main page shows (help requests, stalls, repeated trade
failures, errors) in watchdog-problems.json in its data directory. This compares them with the keys
seen on the last run, prints each new one, and runs COMMAND once per new alert with the alert text on
stdin, for example a script that hands it to an agent. An alert that clears and comes back is new
again. Nothing is posted anywhere unless COMMAND does it. Without COMMAND it only prints, and leaves
the state alone, so a run that hands nothing over cannot mark an alert as seen.
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def text(problem):
    adventure = f" (adventure {problem['adventure_id']})" if problem.get('adventure_id') else ''
    since = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(problem.get('since') or 0))
    return f"PokeSim alert, {problem['kind']}{adventure}, since {since}: {problem['message']}"


def new_alerts(problems, seen):
    """The problems whose keys were not present on the last run."""
    return [problem for problem in problems if problem['key'] not in seen]


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    state = Path(argv[1])
    command = argv[2:]
    problems = json.load(sys.stdin)
    seen = set(json.loads(state.read_text(encoding='utf-8'))) if state.exists() else set()
    failed = False
    for problem in new_alerts(problems, seen):
        message = text(problem)
        print(message)
        if command and subprocess.run(command, input=message, text=True).returncode != 0:
            # Keep it unseen, so the next run hands it over again.
            failed = True
            problems = [row for row in problems if row['key'] != problem['key']]
    if not command:
        return 0
    # While the app is down its alerts cannot be read, so the ones already handed over stay seen.
    keep = seen if any(row['kind'] == 'app_down' for row in problems) else set()
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(sorted(keep | {row['key'] for row in problems})), encoding='utf-8')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
