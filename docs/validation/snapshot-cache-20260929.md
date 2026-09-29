# Snapshot and collection caching

This change keeps the Python backend and the same observation and decision
cadence. It adds no compilation dependency and does not change simulation speed.

## Reused work

PC structs and nicknames are read in contiguous blocks. A bounded cache retains
at most 128 decoded box versions, keyed by box number and exact input bytes.
Every snapshot still reads those bytes. Changes to levels, DVs, experience,
training, moves, trainer identity, names, counts, or the active box are visible
immediately. A restored checkpoint naturally selects its matching bytes.
The cache stores immutable records and holds no emulator references.

Collection milestone calculations retain only the last set of relevant inputs
and its derived goals. HP, PP, movement, and nicknames do not affect those goals.
Species, level, DVs, trainer identity, and collection membership do. New goals
still require two matching consecutive observations. Invalid observations and
trade holds still interrupt that confirmation.

PC dictionaries use shallow copies of immutable record fields. Each caller gets
fresh dictionaries, so changing API or policy rows cannot mutate a snapshot or
another caller's results. The shared Core decoder remains in use.

## Verification

Tests cover live mutations in active WRAM and inactive SRAM, box switches,
restores, separate memory instances, count changes, invalid slots, flat memory
adapters, bounded cache size, independent serialized rows, relevant milestone
changes, invalid DV types, resets, and trade holds.

Measurements use the existing production image on the home server with the
candidate modules loaded in a disposable container. The ROM and an existing
private Blue backup are mounted read-only. No production game is modified.
Three checkpoints are loaded into real PyBoy memory. Baseline and candidate
snapshots are compared field by field, then the same private emulator advances
through 300 observations per checkpoint. Snapshot contents and durable milestone
results must agree after every observation.

Timing repeats alternate baseline and candidate order. Results report median
process CPU time for warm, unchanged collections. These are component timings,
not whole-application throughput or a measured reduction in NAS CPU usage.
The checkpoints have large late-game collections. New games with empty PCs
should not be expected to gain the same amount.

## Compilation options

Numba remains an optional navigation accelerator. Its earlier decision replay
helped the slow Red navigation case by about 1.92 times, but the short Blue case
ran at about 0.78 times the baseline speed. See the
[existing measurements](numba-performance-20260915.json).

[Numba's guidance](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
favors measured hot loops that can compile in nopython mode. It is a candidate
for isolated numeric or array kernels, not an automatic accelerator for all
application objects and emulator memory calls.

[Cython's pure Python mode](https://docs.cython.org/en/latest/src/tutorial/pure.html)
can retain Python source with optional static types. It is a possible next step
for byte decoding or other measured loops after avoiding redundant work.
Neither compiler is required for this change.

## Measured results

| Checkpoint | PC Pokémon | Snapshot speedup | Milestone speedup | PC row speedup |
| --- | ---: | ---: | ---: | ---: |
| Route 23 | 235 | 7.8× | 22.4× | 6.5× |
| Victory Road 2F | 235 | 7.6× | 22.0× | 6.2× |
| Hall Of Fame | 236 | 7.6× | 22.6× | 6.5× |

All 900 advancing snapshot comparisons and milestone ledger comparisons passed.
The full suite passed with 1,485 tests and 84 skips. Lint and documentation checks passed.

Raw timings and candidate source hashes are in the
[measurement record](snapshot-cache-20260929.json).
This validation does not deploy the candidate or change any live simulation settings.
