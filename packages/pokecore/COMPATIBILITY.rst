Experimental state-aware actions and compatibility
==================================================

Applications call PokeSim Core. All helpers below live in
pokecore.state_actions and accept the existing ControllerPort. Inputs
still go through the consumer's send adapter, locks and action recording.

Observed actions
----------------

wait_until(port, predicate, max_frames=..., poll_frames=4) advances without
pressing buttons until an observation satisfies predicate. allowed_kinds can
stop waiting on an unexpected UI state. Zero budgets still inspect the current
observation.

open_menu(port, max_frames=...) presses Start once from the overworld and
waits for a menu. It accepts an already-open menu without sending input.

select_visible_option(port, label, verify=..., max_frames=...) navigates the
currently visible menu coordinates, confirms once, then waits for verify to
observe the intended effect. It rejects missing or ambiguous labels and
unrecognized cursors. It checks observations after each directional action.
For custom layouts, supply ControllerPort.menu_rows, returning dictionaries
with text and cursor coordinates. Otherwise Core reads its existing Red/Blue
menu rows. Scrolling to an option that is not visible is intentionally outside
this helper.

Example::

    from pokecore.state_actions import open_menu, select_visible_option

    opened = open_menu(port, max_frames=120)
    if opened['completed']:
        selected = select_visible_option(
            port, 'POKéMON', max_frames=180,
            verify=lambda ui: ui['kind'] == 'party',
        )

The adapter defines UI kinds. Supply menu_kind to open_menu and allowed_kinds
to selection when your adapter uses more specific labels. result_kinds can
restrict the states permitted while waiting for the confirmed effect.

Results contain status, completed, frames, actions, confirmed and a detached
observation. Status is success, timeout, unexpected_state, stopped,
consumer_budget, stalled or interrupted. A full button press and release must
fit the remaining budget before it starts. A consumer that advances beyond
the requested budget or moves time backwards raises a contract error.

confirmed means a confirmation was attempted, not that its effect succeeded.
After a timeout with confirmed=True, use wait_until to inspect completion.
Do not resubmit the action. The helper does not retry irreversible effects.
Existing use_item and switch_pokemon remain available with their established
contracts. These new helpers do not choose which item or Pokemon to use.

Replay diagnostics
------------------

Enable diagnostics explicitly when recording::

    emulator.start_recording(
        max_frames=6000,
        diagnostic_interval=30,
        diagnostic_ranges=[(0xc000, 0xe000)],
    )
    emulator.tick(6000, render=False, sound=False)
    recording = emulator.stop_recording()

Core raises pokecore.emulator.ReplayDivergence on mismatch. Its details
dictionary identifies the last verified offset and first failed checkpoint,
absolute frame, expected and actual hashes, nearby input events, and up to
64 changed RAM bytes with addresses and expected/actual values. The emulator
stops at that first failed checkpoint for inspection. It does not claim to
identify the exact instruction or first bad frame within the interval.

Checkpoints hash hardware, extra runtime fields and ROM overlays. Memory
windows are restricted to WRAM C000:E000 so diagnostic reads do not touch
side-effecting peripheral registers. Windows cannot overlap. There can be at
most 4096 checkpoints. A final partial interval is included. Diagnostics are
off by default and add time and memory costs when enabled.

The existing deterministic-hook and external-side-effect restrictions still
apply. Final-only recordings retain their previous behavior. Captured RAM
and replay reports are private game artifacts and must stay outside Git.

Permanent compatibility suite
-----------------------------

The suite currently runs on Linux and macOS, using the standard resource
module for process memory measurements. It runs every case in a fresh process. It records median elapsed time
and peak process RSS across repetitions. Trace cases compare intermediate
hardware, screen, audio and WRAM hashes. ROM and starting-state hashes must
also match the baseline. Timing includes hash sampling and any restore checks
specified by the trace, so this is not an uninstrumented maximum-FPS benchmark.
Contract cases run selected pytest nodes and require actual passes. Skips and
missing files are reported as missing coverage, never as successful validation.

Run the public synthetic suite from the Core checkout::

    python -m pokecore.compatibility compatibility/synthetic.json \
        --baseline compatibility/synthetic-baseline.json \
        --output /tmp/compatibility-result.json --repeats 3

It covers controller movement, observed menu actions, battle item/switch
contracts, storage decoding, save/load, audio and cable transport. The demo is
redistributable. Synthetic checks do not establish real-game progression or a
completed two-cartridge trade.

An explicit --capture NEW_BASELINE records a baseline only if all requested
cases pass. Existing output or baseline files are never overwritten. Review
the baseline change rather than automatically accepting a regression. Use
separate local baselines on the same machine for performance decisions.
--max-slowdown and --max-memory-growth optionally fail on percentage increases.
Default comparisons enforce correctness and report performance without a
host-dependent performance gate.

Copy compatibility/private-template.json outside the repository and populate
private ROMs, checkpoints, input traces and initial/final memory assertions.
Use recognized states for movement, menus, battles and storage interactions.
For trading, the template points to the application's existing real managed
cable integration tests. Use an environment with that application installed and
set POKESIM_CABLE_FIXTURES, POKESIM_CABLE_ROMS and GAME_DATA_DIR. Those tests own
the participant lifecycle, completed exchange and durable adoption checks.

--require-private always requires passing private cases for all seven
categories, even if a manifest requests a smaller subset. A partial private
corpus can be benchmarked using its explicit required_categories, but cannot
pass that release gate. Manifests are trusted local configuration and may
select local pytest code. No manifests or fixtures are fetched from a network.

The manual Experimental compatibility workflow accepts an explicit published
PyBoy RS revision and runs the public suite. It can be used after the worktree
changes are published. The ordinary test workflow already discovers the new
synthetic action and compatibility contract tests. Private data never enters CI.
