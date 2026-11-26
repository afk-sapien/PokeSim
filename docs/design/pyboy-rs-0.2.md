# pyboy-rs 0.2.0

Status: draft on 2026-11-25. It covers the pin of pyboy-rs 0.2.0 in pokecore and PokeSim, read against main at `15e09285`.

pyboy-rs 0.2.0 follows real hardware timing: the timer, EI and halt, interrupt dispatch, the STAT line, mode 3 length, IO reads and CGB VRAM transfers. The same inputs from the same state play out differently than under 0.1.9. So every result that depends on the exact frames a run took moves, and every result that depends on what the bot reaches must hold.

## 1. State files across the two versions

| File | 0.1.9 reads it | 0.2.0 reads it |
|---|---|---|
| 0.1.9 state, `pyboy-format-15` | yes | yes, but it plays on differently |
| 0.2.0 state, `pyboy-format-15+pyboy-rs-3` | no, "Trailing data in save state" | yes |

A 0.2.0 state is the format 15 body with a pyboy-rs section after it. `state_body(state)` returns the body alone, and every comparison of two states uses it, never the whole file. PyBoy 2.7.0 reads 0.2.0 states, so the reference check in CI still runs.

## 2. What breaks here

| Kind | What happens under 0.2.0 | What the pin PR does |
|---|---|---|
| Exact match on `pyboy-format-15` | `emulator_state.py` refused every 0.2.0 checkpoint | accepts both formats through `backend_formats()`. Old benchmark records keep their label |
| Stored checkpoints, rewind copies, journals | 0.1.9 files load after the format fix | nothing to convert |
| The Gen II clock offset in `tools/verify_cartridge.py` | read from the end of the file, which is now the pyboy-rs section | reads it from the end of `state_body` |
| Golden hashes | tests hold only ROM and data hashes. No screen or audio value is pinned | nothing to regenerate |
| Action traces | `trace.verify` refuses a 0.1.9 trace: "the trace was recorded on pyboy-rs 0.1.9" | none are tracked. The kept main traces are local and get retraced at the new head |
| Stall captures from before the upgrade | refused the same way | replay them on a 0.1.9 tree. `--any-emulator` runs them on 0.2.0 but they diverge |
| Stuck scenarios | they rerun the bot from `start.state`, they are not recordings. The trajectory changes | section 4 |
| Ladder gate | rungs start from stored checkpoints and reseed. Per-rung numbers move | section 5 |
| `known-failures.txt` | lists `silver-mahogany-pharmacist` only | adds red-agatha and the two new stall scenarios, each with its rate and date (section 4) |

No 0.1.9 recording is re-recorded and blessed. The only regenerated files are the local kept traces, and a trace proves only that one version replays itself. pyboy-rs carries the determinism test for one version: 200,000 frames in two processes.

## 3. The check behind each kind

A rerun that passes proves nothing by itself, so each kind is judged on what the bot reaches, against 0.1.9 on the same inputs.

1. Scenarios: the scenario's own goal, reached or not, at 27 start offsets on both versions (section 4). A pass on one trajectory is not counted as a fix, and a fail on one trajectory is not counted as a regression.
2. Ladder gate: mean waste and milestones per rung over goal seeds 10 to 19 on both versions, seeds the baseline never used (section 5).
3. Real stalls still caught: `silver-mahogany-pharmacist` still fails on 0.2.0, and the stall detectors fire on 0.2.0 trajectories (section 4).
4. Live saves: the image trial loads the 8 live runs' saves from the newest cold backup and checks that they progress (section 6).

## 4. Scenarios

78 scenarios. On 0.1.9 one fails, the known `silver-mahogany-pharmacist`. On 0.2.0 four fail: that one and three new ones.

A scenario's goal seed does not change its run, since the checkpoint carries the policy's random state. Seven seeds gave seven copies of one run. So the probe idles a number of frames before the first decision: 0 to 3, 5, 8, 13 and 21 to 40, 27 runs per scenario and version. The game's own random numbers follow the frame and the divider, so each offset is another stream of in-game luck. Offset 0 is the plain test.

| Scenario | 0.1.9 passes | 0.2.0 passes | 0.2.0 failure at offset 0 |
|---|---|---|---|
| red-agatha-poison-20261112 | 14 of 27 | 9 of 27 | no champion within 240 game minutes |
| red-roof-house-link-help-20261124 | 27 of 27 | 26 of 27, fails at 0 only | nothing achieved for 30 game minutes |
| yellow-fuchsia-withdraw-20261013 | 27 of 27 | 26 of 27, fails at 0 only | 121 goal changes in 60 game minutes |

Reading:

1. red-roof and yellow-fuchsia fail on one trajectory each, and the new timing lands offset 0 on it. Each failure is a real stall the detectors caught, on the bot's side. It replays every time on 0.2.0 at offset 0, so each is a replayable bug.
2. red-agatha passes about half its runs on both versions. Its offset 0 passed on 0.1.9 by luck. 14 of 27 against 9 of 27 is within chance, two-sided Fisher p = 0.27.
3. The Yellow churn is not the investment bug of section 9. The probe sets no ROM path, so no cartridge is rated.
4. So 0.2.0 shows no scenario regression the offsets can tell from chance. It shows three bot weaknesses on the plain replay, one of them already there under 0.1.9.
5. Every probe ran in a tree with no cartridge at the default `roms/pokered.gb`, as a fresh worktree has, so no Gen I run rated TMs. Live runs do. The investment PR (section 9) makes each replay rate its own cartridge's TMs, and it rechecks these scenarios.

### Keeping the original guards

Listing red-roof and yellow-fuchsia as known failures would drop the guards for their own fixes, so neither is listed. A scenario now has `idle_frames` (default 0), frames it idles once the save loads and before the first decision. Both scenarios set `"idle_frames": 1`. Each still starts from its original `start.state`, which both versions load, and still asserts what it was captured for. The offset 0 trajectory is kept as a new scenario from the same save, with no idle, `expect = "stuck"` in `scenarios/index.toml` and a line in `known-failures.txt`:

| New scenario | From | Stall on 0.2.0 at idle 0 |
|---|---|---|
| red-mt-moon-b2f-clefairy-quiet-20261125 | red-roof-house-link-help-20261124 | nothing achieved for 30 game minutes on Mt. Moon B2F, Find Clefairy |
| yellow-victory-road-storage-churn-20261125 | yellow-fuchsia-withdraw-20261013 | 121 goal changes in 60 game minutes on Victory Road 3F, Make room in storage |

`known-failures.txt` gets three lines, each with its measured rate and the date. red-agatha goes on as a flake on both versions, not as a 0.2.0 regression:

```
red-agatha-poison-20261112  # 2026-11-25, a flake on both versions: passes 14 of 27 idle offsets on pyboy-rs 0.1.9 and 9 of 27 on 0.2.0 (Fisher p 0.27)
red-mt-moon-b2f-clefairy-quiet-20261125  # 2026-11-25, pyboy-rs 0.2.0: fails 10 of 10 replays, the one failing offset of red-roof-house-link-help's 27. Passes on 0.1.9
yellow-victory-road-storage-churn-20261125  # 2026-11-25, pyboy-rs 0.2.0: fails 10 of 10 replays, the one failing offset of yellow-fuchsia-withdraw's 27. Passes on 0.1.9
```

Splitting the check instead would need a new mark, such as the player left a map, and would let the Yellow scenario pass while the withdraw stalls again later in the same run. Re-recording the save at an offset would write a 0.2.0 state that 0.1.9 trees refuse. An idle in the scenario keeps the save as it was and is the same one-line change on any version.

Through the normal test path (`POKESIM_SCENARIO_TESTS=1`, no ROM path), on a scratch copy of the four scenarios:

| Scenario | 0.1.9 | 0.2.0 |
|---|---|---|
| red-roof-house-link-help-20261124, idle 1 | passes | passes, 3 achievements in 60 game minutes, ends on Route 21 |
| yellow-fuchsia-withdraw-20261013, idle 1 | passes | passes, 13 achievements in 240 game minutes, ends on Route 23 |
| red-mt-moon-b2f-clefairy-quiet-20261125 | passes | fails, nothing achieved for 30 game minutes on Mt. Moon B2F |
| yellow-victory-road-storage-churn-20261125 | passes | fails, 121 goal changes in 60 game minutes on Victory Road 3F |

The 0.2.0 rows match the probe's offset 0 and offset 1 runs to the achievement, the map and the worst quiet stretch. A 0.1.9 tree ignores `idle_frames`, so there both originals play their old offset 0 trajectory, which passes.

### Pass rate over offsets as a replay mode

No for the preflight, yes as a tool run by hand. N offsets cost N replays. 27 offsets of these three scenarios took about 10 minutes per version at 5 jobs. Scaled to the 78 scenarios, 27 offsets would take about 4 hours, against about 14 minutes for a whole preflight today (13 to 14 minutes over its last three runs, the gate included). Measured on one scenario at a time, it answers whether a failure is a flake, a bot weakness or a regression, which one trajectory cannot. So it fits an emulator pin, a timing change or a scenario that flakes, not every head.

## 5. Ladder gate

On seeds 7, 8 and 9, against `tools/ladder/gate-baseline.json`, 0.1.9 passes all 59 rungs. 0.2.0 fails 8 rungs and improves 2. Mean waste goes from 2.34 to 2.48 and total milestones from 44.68 to 44.01. Per-seed swings are large: gold-randomized/badges_4 gives 27.11, 0 and 0.

So both versions played goal seeds 10 to 19, which the baseline never used, with no baseline to compare against:

| | 0.1.9 | 0.2.0 |
|---|---|---|
| Mean waste per rung | 2.60 | 2.42 |
| Total milestones | 43.70 | 44.60 |
| Stalls | 1 | 0 |
| Errors | 0 | 0 |
| Wall time, 5 jobs | 1167 s | 1152 s |

The test shuffles the version labels within each rung, 4000 rounds:

1. The waste shift is -0.18 a rung, p = 0.32. The milestone shift is +0.015 a rung, p = 0.20. On seeds 7 to 9 the same test gives p = 0.62 and p = 0.78.
2. Two rungs differ at p < 0.05, against about 3 expected by chance across 59. Both favor 0.2.0: red/badges_4 (16.77 to 10.08, where 0.1.9 hit a retry loop on one seed) and silver/badges_8 (0.11 to 0).
3. None of the 8 rungs that failed on seeds 7 to 9 differs on seeds 10 to 19. For example blue/badges_4 goes from 14.83 to 14.04, crystal/new_game from 4.58 to 2.23 and silver/badges_4 from 1.89 to 3.44.

So the 8 failures are the baseline's three seeds landing on other trajectories, not a change in what the bot reaches. The baseline has to be retaken on the pin, or every preflight on main fails those 8 rungs.

The pin PR retakes it: one gate run of `5db7dacc` on seeds 7, 8 and 9 with `--write-baseline`. It matches the earlier run of `1869a5f2` on all 59 rungs. Against the 2026-11-20 baseline, mean waste goes from 2.33 to 2.48, milestones from 44.68 to 44.01, and stalls and errors stay at 0. 22 rungs get a looser limit, 11 only a tighter one, and 26 keep theirs. The 8 rungs that failed:

| Rung | Waste before | Waste after | Milestones before | Milestones after | Looser on |
|---|---:|---:|---:|---:|---|
| gold-randomized/badges_4 | 1.50 | 9.04 | 0.00 | 0.00 | waste |
| red/badges_6 | 4.87 | 8.91 | 0.00 | 0.00 | waste |
| silver/badges_4 | 0.00 | 3.57 | 0.00 | 0.00 | waste |
| blue/badges_4 | 8.20 | 10.79 | 0.00 | 0.00 | waste |
| crystal/new_game | 1.55 | 3.39 | 3.00 | 2.67 | waste and milestones |
| crystal/red | 0.66 | 0.66 | 1.00 | 0.33 | milestones |
| silver/badges_2 | 0.00 | 0.00 | 0.67 | 0.33 | milestones |
| silver/new_game | 7.31 | 3.58 | 3.00 | 2.67 | milestones |

`tools/ladder/regressions-suspected-20261125.md` lists all 22 looser rungs beside their seeds 10 to 19 means. Of the 22, only red/badges_4 differs on seeds 10 to 19 at p < 0.05, and it is better on 0.2.0. crystal/red is the one to watch: it also earns fewer milestones on seeds 10 to 19, 0.60 against 0.30, though not at p < 0.05. The raw seeds 10 to 19 results for both versions are kept in the checkout's untracked data folder, `data/pyboy-rs-0.2/gate-seeds-10-19`, since gate run folders hold private game data.

## 6. Deploy and rollback

1. One image runs every worker. Trade peers in one deploy share its container, and a remote peer gets JSON, never a state. So no worker mixes versions within a deploy.
2. The upgrade moves saves one way. The first save under 0.2.0 has the new format.
3. An older app refuses a 0.2.0 checkpoint cleanly, "Unsupported checkpoint emulator or state format". A rollback restores the cold backup taken before the upgrade.
4. The image trial ran the pin commit `359c15f4` for 30 minutes on the newest cold backup, with the 8 live runs. All 8 loaded their 0.1.9 saves, kept running with 0 restarts, 0 errors and 0 problems, earned progress events, and wrote checkpoints in the new format. The same backup under 0.1.9 (`da777ecc`) also ran all 8 with 0 problems. Progress events over the 30 minutes came to 1577 on 0.2.0 and 1447 on 0.1.9.

## 7. Speed and memory

Deep postgame saves, red-deep, gold-deep and crystal-deep, through the live sim with its bot, 3 pairs of 500,000 frames each, niced, on one CPU, the arm order rotating each pair. Each arm ends on the same state in all 3 pairs.

| Save | fps 0.1.9 | fps 0.2.0 | Change | Memory 0.1.9 | Memory 0.2.0 |
|---|---:|---:|---:|---:|---:|
| red-deep | 7321 | 7344 | +0.3% | 289 MiB | 288 MiB |
| gold-deep | 4633 | 5580 | +20.4% | 170 MiB | 166 MiB |
| crystal-deep | 4999 | 5266 | +5.3% | 175 MiB | 175 MiB |

The versions take each save down different trajectories, splitting at policy step 754 on Red, 434 on Gold and 150 on Crystal. So these rows compare different game work. Gold's rise is mostly that: on 0.2.0, 44% of its policy steps are in battle, against 32% on 0.1.9.

The emulator alone, with no bot, ticking each save 120,000 frames with no input, median of 3 rounds:

| Save | fps 0.1.9 | fps 0.2.0 | Change |
|---|---:|---:|---:|
| red-deep | 36,571 | 39,063 | +6.8% |
| gold-deep | 24,565 | 26,429 | +7.6% |
| crystal-deep | 19,202 | 20,076 | +4.6% |

So 0.2.0 is 5 to 8% faster as an emulator, and no sim got slower. Memory is the same within 4 MiB.

## 8. Sound off

Sims boot with `sound_emulated=True` (`pokecore/emulator.py:182`). Headless runs already turn it off (`pokesim/adapter.py:44`, `gen2/adapter.py:58`).

What reads sound state:

1. The viewer's audio feed (`pokesim/runtime/emulator.py:221-249`). It needs sound on.
2. `enable_checkpoint_sound` in `checkpoint_audio.py`, called on a reload (`pokesim/emulator.py:329`), a cable link (`interactions/cable.py:58`) and a trade (`trade/execute.py:94`).
3. The trace header, which records the option.

Can a save move over? Measured on the three deep saves on 0.2.0, and on red-deep and gold-deep on 0.1.9 too:

1. Work RAM after 3600 idle frames is equal with sound on and with sound off, 0 bytes apart.
2. A sound-on save loads with sound off. The save it then writes loads with sound on and plays: about 290,000 changing samples per 600 frames on red, 211,000 on gold, against 0 from a machine with sound off.
3. `enable_checkpoint_sound` leaves a 0.2.0 sound-off save unchanged.

Gain, on 0.2.0, from the same 3 pairs as section 7:

| Save | fps sound on | fps sound off | Change | Same trajectory |
|---|---:|---:|---:|---|
| red-deep | 7344 | 7397 | +0.7% | no, it splits at policy step 168 |
| gold-deep | 5580 | 5740 | +2.9% | yes, all 32,356 steps |
| crystal-deep | 5266 | 5390 | +2.4% | yes, all 39,200 steps |

The emulator alone gains 15.4% on red-deep, 14.0% on gold-deep and 12.7% on crystal-deep. Emulation is about a fifth to a quarter of a sim's time on these saves (sim fps over bare fps), so a sim gains 2 to 3%. Memory does not change.

With sound off, every sound register from 0xFF10 to 0xFF26 reads 0, where sound on reads the real values. On Red the bot's down press then lands one step later at policy step 168 and the run goes another way. Gold and Crystal keep the same trajectory for all 500,000 frames. So on Gen I, sound off changes play for live sims. The gate and the replays already run with sound off, so their baselines would not move.

Answer: yes, saves written with sound on move over safely. Work RAM ends 0 bytes apart after 3600 idle frames on all three deep saves, and a moved save plays sound again when loaded with sound on. The gain is 2.4% on Crystal, 2.9% on Gold and 0.7% on Red. That is too small to pay for what it costs: the live sim keeps sound running so a listener can join at any moment (`_sync_audio`), so sound off needs an emulator reload whenever someone listens, and it changes Gen I play.

## 9. PR split

1. The pin PR: the pin, the format and clock fixes, `idle_frames`, the two new stall rows in `scenarios/index.toml`, the retaken gate baseline with its list of looser rungs, and this note. The private scenarios folder changes when it merges, since 0.1.9 trees share it: `"idle_frames": 1` in the two scenarios, the two new scenario folders and three `known-failures.txt` lines. A 0.1.9 tree ignores the new key with a warning and still passes both.
2. The investment PR, after the pin. The rating reads `config.ROM_PATH`, so a Yellow run with ROM paths set rates Red's TMs, and a run in a tree without `roms/pokered.gb` rates none. Its test is the yellow-fuchsia-withdraw replay with ROM paths set. Since every Gen I replay then rates TMs, it replays all scenarios and the gate before it merges.
3. Then one PR per cause, each taking its line off `known-failures.txt`: the Mt. Moon B2F quiet stall, the Victory Road storage churn, then red-agatha.
