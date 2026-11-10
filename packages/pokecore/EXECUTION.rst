Experimental execution APIs
===========================

These APIs belong to the isolated PyBoy RS and PokeSim Core experiment.
Applications call Core. PyBoy RS executes generic controller inputs and Core
interprets Pokemon menus and verifies their effects. No menu policy moves into
the emulator.

Bounded sequences
-----------------

Each step is a pair of a button tuple and a positive frame count. The tuple
specifies the full controller state, including simultaneous buttons. An empty
tuple releases the controller and waits. At most 4096 steps are accepted.

Example through Core::

    emulator.start_sequence([
        (('a',), 8),
        ((), 24),
        (('down',), 8),
        ((), 24),
    ])
    result = emulator.run_sequence(32, render=False, sound=False)
    checkpoint = emulator.checkpoint()
    result = emulator.run_sequence(32, render=False, sound=False)

run_sequence returns frames, reason, completed and a detached progress object.
Reasons are completed, budget, cancelled, paused and stopped. max_frames can
be zero. cancelled is an optional callable checked between frames. Returning
true suspends the sequence without discarding its progress. cancel_sequence
explicitly abandons it and queues releases for the next advanced frame.
Completion also queues releases for the next frame, matching ordinary input
semantics without consuming an unbudgeted extra frame.

Starting requires no pending input and no other active sequence. Use
run_sequence to advance an active sequence. Ordinary tick is rejected until
the sequence finishes or is cancelled. Hooks still execute synchronously and
Core flushes hook-generated pending inputs before the following frame.

Core frame_count reflects completed frames during hooks and cancellation
callbacks, including batched ticks. Checkpoint restoration preserves
the logical Core timeline even when it differs from the backend frame counter.

The first implementation schedules sequences in the Python binding around
native Rust frame execution. It is not a native batch optimization. Frame
budgets, hooks and cancellation take priority over reducing API calls.

Existing menu helpers continue to use ControllerPort.send and choose so the
consumer retains its locks, action log and global frame budget. An adapter
can translate send(button, held_frames, released_frames) into a hold step and
an empty-button wait step. Pass only the remaining consumer budget to
run_sequence and count result['frames']. Reobserve the menu after each
bounded action. Do not replace adaptive menu checks with a long fixed script.

Traces
------

pokecore.trace records a run as hash-chained gzip JSON-lines segments::

    from pokecore.trace import Recorder, Segment, verify

    recorder = Recorder(emulator)
    recorder.begin(Segment('run/0001.jsonl.gz', keep_start=True), seed=7)
    emulator.press('a')
    emulator.tick(8, render=False, sound=False)
    recorder.decide('walk', 1, 0, 0)
    recorder.detach()
    result = verify('run/0001.jsonl.gz', another_emulator)

The recorder logs every press, release, tick with its render and sound flags,
memory and register write, load, hook registration and clock call. Writes a
hook makes during a tick stay in that tick's record. The caller adds decide
and input records. The header names the ROM, the start state, the emulator
build and settings, the queued inputs and the clock lock. States a segment
loads are kept beside it by hash.

verify replays a segment with no policy and checks the chain, each write and
the periodic state digests. redecide runs a policy again from the same start
and stops at the first record that differs, ticking with the logged flags so
a headless replay matches a game that had a viewer. Both return 0 for a match,
1 for a divergence and 2 for a harness failure such as a missing state, a
broken chain or another ROM. ``pokecore trace verify SEGMENT --rom ROM`` runs
verify from the shell.

A live wall clock cannot be replayed. Lock the clock before recording a Gen II
cartridge. Sequences and checkpoint restores are refused while a recorder is
attached. Traces and kept states are private local artifacts. Do not commit or
distribute them.

Execution checkpoints
---------------------

Core checkpoint format 2 includes its own pending inputs and logical frame
counter plus the backend execution checkpoint. The backend owns delayed
events, sequence progress and native execution state. Runtime state includes
renderer counters, scheduler deadlines, serial output, RTC latches, ROM and
boot ROM overlays, and the backend frame counter. Overlay capture stores
changed bytes only. It does not embed the complete ROM.

restore_checkpoint validates identity and state before replacing execution.
Checkpoints are taken between frames, outside hooks. Python callback objects,
external resources, wall-clock pacing and diagnostic profiling counters are
not serialized. The receiving machine must already have matching hook addresses. Checkpoints
preserve each hook's underlying instruction and restore it while retaining
the receiving machine's callback and context objects.

Legacy save and load methods retain the upstream format-15 hardware bytes.
They do not preserve pending inputs or all runtime fields. Use the execution
checkpoint API for exact resume. Raw loads are rejected while a sequence is
active. Older Core format-1 checkpoints retain their historical
hardware-only backend behavior.

Profiling procedure
-------------------

Example::

    emulator.start_profiling()
    emulator.tick(6000, render=False, sound=False)
    counters = emulator.stop_profiling()

start_profiling resets and enables native counters. profiling_counters returns
a detached snapshot. stop_profiling returns the final snapshot and disables
collection. Native measurements sample approximately one in 64 scheduler
iterations, reporting raw sampled wall nanoseconds for:

* cpu_memory_dma, including CPU execution, bus accesses and DMA
* audio scheduler work
* serial scheduler work
* timers scheduler work
* graphics scheduler work

Hooks report exact callback counts, wall nanoseconds and thread CPU nanoseconds
separately. Component times are sampled wall time, not thread CPU time. Clock reads add
measurement overhead, particularly for very short components. Memory
mapped peripheral work performed inside CPU execution remains in that bucket.
Hook instruction stepping and Python boundary overhead are not included in
the component sample totals. These counters do not form a full wall-time sum.

Run tools/check_execution.py from the Core checkout with the experimental
packages installed to verify sequence resume and profiling with the
redistributable demo. It accepts --rom, --state, --frames, --render and --audio
for local fixtures.

Profile the same checkpoint and input trace separately from speed benchmarks.
Use counters to find expensive components. Measure final throughput with
profiling and tracing off, with the same render and sound settings, and
compare state hashes. Instrumentation is not a speed improvement.
