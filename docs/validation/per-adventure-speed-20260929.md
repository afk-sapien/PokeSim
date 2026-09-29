# Individual simulation speeds

Adventure settings now select that game's speed while it is running or stopped.
The setting persists across restarts. Missed worker updates are retried by health
checks. New games default to 1×. The global speed and maximum-running controls
are removed, and neither the API nor supervisor imposes a running-game limit.

A one-time registry migration copies the effective old global speed to every
existing game, including archived games and games with obsolete individual
values. Other settings remain intact. Subsequent startups keep individual edits.

Cable sessions use the slower positive participant speed, or Max when both use
Max. Each adventure keeps its own saved speed. Existing trade reservations still
freeze settings until the exchange is resolved.

Validation passed 1,537 Python tests and 10 real Chromium checks. Focused checks
covered migration with default, Max, and numbered speeds, restart persistence,
independent workers, retry after reconnect, invalid inputs, 35 simultaneous mock
workers despite a legacy limit of one, and five mixed cable speed combinations.
All 200 training destination comparisons from the memory update remain unchanged.
Frontend tests, lint, and documentation checks passed. Phone and desktop layouts
were visually inspected. Browser tests saved one game's speed while retaining the
other's, preserved a custom 0.75× setting, and verified the removed global controls.
