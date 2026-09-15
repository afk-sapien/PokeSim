# Repeatable decision benchmarks

`tools/benchmark_decisions.py` measures policy work separately from rendering,
emulator ticks, web traffic, and playback pacing. It also checks that a code change
preserves a complete fixed-frame gameplay trace.

## Private inputs

A fixture directory contains:

- `fixture.json`, with a name and the validated runtime `settings`, including ROM,
  reference-data paths, policy, starter, and seed.
- `checkpoint.state`, a copied PyBoy checkpoint.
- `checkpoint.json`, its original metadata with policy and RNG state.
- Optional `trade_preferences` inside `fixture.json` for partner protections.

Use stopped backups or already captured fixture copies. The harness opens the ROM
read-only, supplies independent cartridge RAM, and writes only temporary data and
the explicitly chosen output directory. It never connects to a running manager.
Generated workloads contain private snapshots, memory, settings, and policy state.
Keep them outside the checkout and never publish them.

## Preserve the baseline

Export the production source before changing it. An existing checkout can also be
passed with `--source-root`.

```sh
mkdir -p /tmp/pokesim-benchmark-baseline
git archive HEAD pokesim | tar -x -C /tmp/pokesim-benchmark-baseline
python tools/benchmark_decisions.py --source-root /tmp/pokesim-benchmark-baseline capture /path/to/private/fixture.json --frames 12000 --output /tmp/pokesim-captured-work
```

The capture runs exactly the requested number of emulated frames. It records each
decision's snapshot, RAM view, actions, persisted policy state, and route-call count.
Its report includes complete trace and final checkpoint hashes. Policy time derives
from emulated frames, so faster computation cannot alter time-based policy inputs.

## Measure the same work before and after

```sh
python tools/benchmark_decisions.py --source-root /tmp/pokesim-benchmark-baseline replay /tmp/pokesim-captured-work/workload.pickle.gz --trust-local-workload --decisions 128 --repeats 3 --warmups 1 --output /tmp/pokesim-before
python tools/benchmark_decisions.py replay /tmp/pokesim-captured-work/workload.pickle.gz --trust-local-workload --decisions 128 --repeats 3 --warmups 1 --output /tmp/pokesim-after
```

Replay does not tick an emulator. Each trial creates a fresh policy from the same
initial policy and RNG state, then feeds the exact captured inputs sequentially.
Timing covers only `policy.step`, including action generation. Input loading,
verification, and hashing are excluded. Every decision must retain its expected
actions, policy state, and number of route calls. A mismatch fails the run.

`--decisions 128` selects the same initial 128 decisions for both versions. Omit it
to use the complete corpus. Keep the frame capture, prefix, repeats, and warmups
identical. Run versions sequentially on an otherwise idle machine. Reports include
mean, p95, maximum, total wall time and thread CPU time for decisions and route
calls, plus each trial separately. CPU time helps identify interference from other
processes. These are decision-cost measurements, not overall simulation throughput.

Reports also include process peak RSS where available and an estimate of reachable
navigation-cache object size. RSS includes imported modules and the loaded corpus.
The cache estimate counts shared objects once, but it is not an exclusive allocation
measurement. Compare versions using the same corpus and interpreter.

Pickle can execute code. The explicit trust flag is required because replay files
must only come from your own local capture. Never load a downloaded workload.

## Verify gameplay equivalence

```sh
python tools/benchmark_decisions.py trace /path/to/private/fixture.json --frames 12000 --compare /tmp/pokesim-captured-work/result.json --output /tmp/pokesim-trace-after
```

This reruns ordinary input from the exact original checkpoint using the candidate
policy, with the same frame budget and virtual clock. It fails unless action counts,
decision counts, snapshot/action/policy traces, final snapshot, and final PyBoy
checkpoint hashes match the baseline. This catches changes that a faster wall-clock
run could hide by advancing a different amount of gameplay.

The runner deliberately omits runtime events, notifications, automatic recovery,
trading, and rendering. Use integration tests for those behaviors. Compare several
representative private fixtures before drawing broader performance conclusions.

## Navigation optimization results

The [September 15 validation report](validation/decision-performance-20260915.json)
records a 5.18× reduction in decision time on the navigation-heavy Red Sprout
workload. Mean decision latency fell from 156.3 ms to 30.2 ms, with p95 falling from
405.0 ms to 76.6 ms across three trials of identical inputs.

The navigator now indexes warp locations, stationary obstacles, and passable tiles.
It reuses ordered neighbor results while checking geometry, abilities, story state,
observed edges, temporary blocks, and live obstacles for changes. Searches retain
their original ordering, expansion limits, paths, and random choices.

This trades memory and cache-validation overhead for faster repeated searches.
The primary benchmark process used about 39 MiB more peak resident memory. Its
reachable navigation cache was about 22.4 MB. Cold searches remain slower than warm
ones, and cheap decisions do not necessarily improve. See the report for the other
sampled saves and full limitations.

## Comparing optional Numba acceleration

Install `.[acceleration]` in a separate environment and use that same interpreter
for both versions. The `POKESIM_NAVIGATION_BACKEND=python` environment variable
forces the Python backend. An absent Numba dependency also uses Python.

The compiled backend accelerates `Navigator.route` by assigning integer IDs to
locations and searching NumPy arrays. The Python navigator still supplies movement
rules and ordered edges. Numeric edges are populated lazily and invalidated with
the Python neighbor cache. The existing distance lookup remains in Python.

Reports include dependency versions, compiled graph call counts, compiler
initialization timing, and retained warmup trials. Confirm nonzero compiled calls
and zero backend errors before attributing results to Numba. A populated compiler
cache and a populated navigation graph are separate things. Each replay trial
starts a new policy and empty navigation graph, even after compiler warmup.

Set `NUMBA_CACHE_DIR` to a fresh private directory when measuring first compilation.
Use the same directory in a second fresh process to measure disk-cache startup.
Keep these startup costs separate from the measured decision trials. Normal game
startup initializes the optional compiler before the emulator begins playing.

Memory reports include graph arrays and deduplicate NumPy buffer owners. Process
peak RSS also includes compiler code and temporary search arrays. Compare both
latency and memory, since short searches and cold graph construction can regress
while repeated large searches improve. Compiler import or execution failure
switches the process back to Python.

## Optional compiled navigation

Use the same Python environment for the baseline and candidate, even if only the
candidate uses the optional compiler. Each report records the installed versions
of PyBoy, NumPy, Numba, and llvmlite. A missing optional dependency is recorded as
`null`. Installing Numba does not prove that a workload used it.

Each trial reports graph-route calls, calls with an actual nopython dispatcher,
backend failures, and kernel initialization time. A workload that never performs
a compiled search reports zero compiled graph-route calls. Warmup trials are kept
separately from the measured aggregate, including their first decision and route
latencies. Importing the optional backend module is timed separately before the
decision loop, so use the startup check to account for that cost.

Measure first-use compilation and disk-cache startup in separate fresh processes:

```sh
mkdir /tmp/pokesim-numba-cold-cache
NUMBA_CACHE_DIR=/tmp/pokesim-numba-cold-cache python tools/benchmark_decisions.py startup /path/to/private/fixture.json --output /tmp/pokesim-numba-first-start
NUMBA_CACHE_DIR=/tmp/pokesim-numba-cold-cache python tools/benchmark_decisions.py startup /path/to/private/fixture.json --output /tmp/pokesim-numba-disk-start
```

Use a cache directory that has never been used before for the first command. The
report lists compiled cache files before and after initialization, making the cold
and populated-cache cases reviewable. Startup timing separates source/module import
from kernel initialization and excludes interpreter startup and game simulation.
Neither command launches a game or alters its saves.

Then run the same before/after replay commands with that cache directory and one
warmup trial. Keep `POKESIM_NAVIGATION_BACKEND` consistent and report it. The `python`
value forces fallback for checking behavior when the optional backend is disabled.

Memory reports include the compiled graph's retained arrays and containers. NumPy
owning buffers are counted once even when multiple views share them. The report
separates their buffer bytes and array headers. It excludes temporary search arrays
and compiler machine code from the cache estimate. Process peak RSS captures their
broader memory impact. Compare that memory cost, first-use delay, and steady-state
benefit before enabling acceleration for a deployment.

The [Numba validation report](validation/numba-performance-20260915.json) records
three trials per workload with identical decisions and exact gameplay replays.
The demanding routing sample improved from 31.7 ms to 16.5 ms mean decision time,
with p95 improving from 79.9 ms to 58.8 ms. The short-routing sample added 0.87 ms
per decision, and the sample without routing was roughly unchanged.

The demanding benchmark process used about 148 MiB more peak RSS. Its retained
navigation structures grew from 22.4 MB to 34.2 MB, including 8.9 MB of numeric
buffers. Those figures are benchmark process measurements, not a measured live
worker memory difference. Empty-cache compiler initialization took 392 ms plus
68 ms of module loading. Loading cached code took 267 ms plus 73 ms of module
loading. The slowest measured decision increased from 336 ms to 415 ms due to
fresh graph population. These tradeoffs are why acceleration remains optional.
