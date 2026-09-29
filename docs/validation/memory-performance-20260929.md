# Simulation memory reduction

Training targets reused separate coordinate lists for many levels with identical
destinations. Cache the map sets and share tile coordinates instead. Navigation
change detection used a hash table for every learned tile. Immutable tuple
snapshots retain edit detection with less allocation overhead. Route caches
remain available, and simulation pace and observation frequency are unchanged.

| Private workload | Mean RSS before | Mean RSS after | Peak RSS before | Peak RSS after | CPU time reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| Walking, 24,000 frames | 192.5 MiB | 175.5 MiB | 200.7 MiB | 176.2 MiB | 32.0% |
| Walking, 120,000 frames | 199.5 MiB | 176.3 MiB | 217.4 MiB | 195.8 MiB | 11.3% |
| Ceremony, 12,000 frames | 152.5 MiB | 149.9 MiB | 158.3 MiB | 150.5 MiB | 8.0% |

Each pair used the same private Blue checkpoint and ended with identical typed
snapshots and WRAM and cartridge RAM checksums. These are fixed-work, complete
worker measurements, including normal AI, observation, bookkeeping, and viewer
requests. The longer walking sample covers 33 minutes of emulated time.

The initial allocation profile identified training targets, navigation cache
validation records, and cached neighbors as substantial retained allocations.
Profiler overhead is excluded from the comparison table. Reported RSS includes
shared file-backed memory and warmup. One late-game save cannot establish a
universal footprint or prove behavior over thousands of hours.

Validation: 1,528 tests passed, with 94 optional checks skipped. Ordered training
destinations matched the original implementation for all 200 Red/Blue and level
combinations. Navigation differential checks covered graph changes, doors,
obstacles, restores, and route ordering. Lint and documentation checks passed.

See the [raw measurements](memory-performance-20260929.json) for CPU times,
sampled memory ranges, checksums, and limitations.
