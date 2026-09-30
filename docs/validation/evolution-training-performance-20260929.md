# Evolution training CPU hotspot

The fresh Blue adventure ran at about 5 to 6× on Max while consuming approximately
one CPU core. Other adventures were stopped, and the host retained idle CPU
capacity. The worker confirmed speed 0, meaning unlimited.

A read-only Python stack sampler attached to the live worker on build `4c89109`.
Of 355 captured simulation-thread stacks, 290 included the collection tile scan.
There were also 60 sampling errors. These samples identify a hotspot, not an exact
CPU-time percentage. Sampling was removed before subsequent throughput checks.

The evolution-training goal rebuilt eligible grass and cave destinations on every
AI decision, even during battle dialogue. It repeatedly scanned the same maps for
multiple species sharing encounter locations. Ordinary training already cached
its destinations, but the evolution path did not use that cache.

The fix caches evolution destinations by version and level, shares results for
identical encounter-map sequences, and reuses immutable per-map coordinates.
It retains the existing level eligibility rules, Cerulean Cave exclusion, and
exact target ordering, including routing tie breaks. Cache sizes are bounded.

Validation:

- All 200 combinations of Red/Blue and levels 1 through 100 match the original
  ordered destination tuples exactly.
- Regression tests cover level and version changes, duplicate encounter maps,
  exclusion of water and Cerulean Cave sources, and reuse without another tile scan.
- The 46 collection tests pass. The broader suite excluding cartridge integration
  tests passes 1,533 tests with 96 skipped. Lint and documentation checks pass.
- A local 50-call Blue level-15 destination benchmark used 2.505 CPU seconds before
  caching and 0.000019 CPU seconds with a warm cache. This measures only destination
  construction, not full-simulation speed or cold-start cost.

This is a workload-specific optimization. Max throughput still depends on the
current AI task, emulator work, rendering, and host resources. It does not establish
a universal 30× or 50× simulation speed.


## Home-server verification

Deployed `pokesim:evolution-cache-9362df8` after a verified cold backup. The fresh
Blue adventure resumed healthy at Max. Live samples while training and traversing
Mt. Moon included 62.6×, 66.9×, 111.4×, and 114.8×. It had earned the Boulder Badge.
The three adventures the user stopped remained stopped.

These readings cover different game moments from the earlier 5 to 6× samples.
They show the post-deployment throughput, not a controlled whole-game speedup ratio.
The exact-destination comparison above verifies that the cached calculation itself
retains the original output.
