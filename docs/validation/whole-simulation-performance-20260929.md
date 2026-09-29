# Whole-simulation performance

The cache and library build was compared with the previously deployed image
on the home server. Each pair used the same private Blue checkpoint and
the same number of emulated frames after 1,200 warmup frames.

| Scenario | Frames | Before CPU seconds | After CPU seconds | CPU reduction | Before pace | After pace |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Walking at Max | 12,000 | 19.54 | 10.48 | 46.4% | 9.25× | 17.62× |
| Hall of Fame to Route 1 at Max | 12,000 | 10.25 | 3.35 | 67.4% | 17.77× | 57.30× |
| Walking at 4× | 7,200 | 14.83 | 9.23 | 37.8% | 3.36× | 3.44× |

Every pair ended with identical typed snapshots and identical WRAM and
cartridge RAM checksums. The benchmark includes the actual worker loop,
AI decisions, observations, collection bookkeeping, and an active viewer.
It polls frames about ten times per second and game state every two seconds.
Startup, shutdown saves, and the shared library manager are outside the timing window.

These are short single samples on large late-game collections, not a promise
for every part of a campaign. The three production games kept running, so
server contention affects wall-clock pace. Fixed work and matching final
states make process CPU time the more useful efficiency comparison.

At Max pace a faster worker can still consume a whole core while advancing
more quickly. Fixed-pace CPU utilization and RSS values are available in the
[raw measurement record](whole-simulation-performance-20260929.json).

## Deployment

The tested image was installed on the home server after a verified cold backup.
All three adventures resumed healthy and advanced beyond their pre-upgrade
frames, with Max pace preserved. Live browser checks confirmed resource
readings, recent activity, the Back to Library button, and phone layouts.
The deployed source revision is `b875a8f1d82c805814a11320b942d437e384820a`.
This is a local Docker build, not a new public package release.
