# One bot, two adapters

Phase 3 of the architecture plan. Red, Blue and Yellow (Gen I) and Gold, Silver and Crystal (Gen II) play
through one policy shape and one runtime loop. What truly differs between the games sits in a small
`GameAdapter` per generation, and every difference that stays is named there as a setting. Gen I is the
reference: where the two differ for no reason, Gen II takes the Gen I way.

There are five items, one PR each. Each PR deletes what it replaces and carries the full proof once at the
end: the ladder gate, the stuck replays, decision agreement against the PR before it and the shadow
equivalence tests. Items 1, 2, 4 and 5 move code and keep play the same, so their agreement is 100%. Item 3
changes how Gen II ranks its goals, and its PR names each change a player can see.

## Today

The runtime already shares one step (`runtime/game_loop.py`), the trace, capture, supervision, the reload
ladder, the manifest and the pin script. Around it sit two of everything else:

1. Two policy shapes. Gen I is `step(ctx) -> list[Action]` on `policies/base.Policy`. Gen II is
   `step(snapshot, memory, sp, clock) -> Action` on its own class, with its own `Action` and an unversioned
   save.
2. Two emulators of about 1,400 lines each (`emulator.py`, `gen2/emulator.py`) and two headless runners.
   They run the same loop with the same autosave, guards, reload, trace and pin calls, and differ in about
   eleven places.
3. Gen II's ladder picks one rung before the decide pipeline sees it, and its tier, worth and frames are
   dropped on the way. The arbiter sees every Gen II rung as story progress.
4. The boss and training rules are written twice, once in `policies/progression.py` and once in
   `gen2/policy.py`.
5. `gen2/policy.py` is one 2,732 line class with about 70 fields. Errands (heal, shop) are latches and
   fields in both generations, with no object of their own.

## 1. One Policy protocol

`runtime/policy.py` holds `Action`, `PolicyContext` and a `typing.Protocol` named `Policy`. It imports no
game data, so a Gen II worker still never loads Gen I code.

```python
class Policy(Protocol):
    def step(self, ctx: PolicyContext) -> list[Action]: ...
    def state_dict(self) -> dict: ...            # versioned in both generations
    def load_state_dict(self, state: dict): ...  # clears the pin and calls on_restore itself
    def on_restore(self): ...
    def describe(self) -> str: ...
    def details(self) -> dict: ...
    def goal_record(self) -> dict | None: ...
    def goals(self, snapshot, query=None): ...
    def catalogue(self, snapshot, query=None, limit=None): ...
    def pin_goal(self, snapshot, key): ...
    def unpin_goal(self): ...
    def drop_pin(self): ...
    def restore_pin(self, pin): ...              # what a replayed pin script sets
    @property
    def pin(self): ...
```

[Goal queue](goal-queue.md) proposes `set_queue(entries)` and `queue_state()` in place of the five pin methods, and a load that no longer clears the choice. Its slice 1 PR changes this protocol as built.

Gen II's `step` takes the same `PolicyContext` (snapshot, clock, memory, stack pointer) and returns a list.
`hopeless_battle` is a method of the snapshot in both.

Deletes: the `Gen1` and `Gen2` deciders in `game_loop.py` (one decider remains), Gen II's `Action` class,
the callers' own `on_restore` after a load, the two `restore_pin` branches in the headless runners, and
`policies/base.Policy`. Both policies subclass the protocol by name, which gives them its defaults.

## 2. One runtime loop with a GameAdapter

One `runtime/emulator.py` runs the loop for both: boot, commands, pause, manual input, pacing, the step,
autosave, guards, reload, load, trace, capture and the final save. One `runtime/headless.py` does the same
for tests and tools. Each generation gives an adapter:

```python
class GameAdapter(Protocol):
    generation: int
    settings: Settings
    def read(self, pb, frame) -> Snapshot: ...
    def new_policy(self, seed, store) -> Policy: ...
    def options(self, pb): ...                  # the text speed and animation byte
    def after_load(self, pb, policy): ...        # Gen II sets its clock and options here
    def guard(self, snapshot, policy) -> Verdict: ...  # fine, park, or climb the reload ladder
    def reload_targets(self, saves) -> list: ...
    def background(self, frame): ...            # work that runs on a frame cadence beside play
```

Deletes: the duplicated halves of `emulator.py` and `gen2/emulator.py`, and of `headless.py` and
`gen2/headless.py`. What stays per generation is the adapter, a few hundred lines each.

## 3. Gen II ladder rungs as candidates

Each rung offers to the Gen II ballot as its own source, with its real tier, worth and frames, as Gen I's
collection does. A rung's build no longer writes state. It returns the goal and a commit that runs only when
the rung wins. The arbiter weighs every rung at once, and the running rung's interrupt price, stand-downs,
a missing route and the pin all go through the same paths as Gen I's offers.

The Gen II story's ordered returns stay one `story` source, as Gen I's story does.

Deletes: the `Ladder` class with its saved and undone slots, the two-at-a-time choose, `settle_pin` and the
generic progress candidate in `gen2/pipeline.py`. `ladder_rung` stays as the name of the source that won, for
the stuck watchdog, the supervisor and the replay tools.

## 4. League and training rules in planning

`planning/league.py` holds the boss order, the next boss, the readiness target, boss and story training, the
loss note and the boss gate, for both generations. Each generation gives a boss table and a matchup scorer.

Deletes: those functions in `policies/progression.py`, the boss block in `gen2/policy.py` and the Gen I gate
wrapper in `policies/strategic.py`.

## 5. Split gen2/policy.py, errands as tasks

`gen2/policy.py` becomes a package: story, errands, storage, menus, navigation, items, battle and pins, with a
thin `Policy` that steps them. Its state is typed dataclasses, saved under a version.

An errand is a task object in `planning/errand.py`: it offers a candidate, commits when picked, walks to its
site, acts there and says when it is done, and it saves its own state. Heal and shop are errands in both
generations, and so is Gen I's social detour, which keeps its random draws at the same point of the step.

Deletes: the errand latches and fields in both policies (`errand`, `errand_offer`, the heal latch,
`healing_map`, `shopping`, `shop_location`), the detour's goal write inside the walk and the inline arrival
code in Gen II's step.

As built, the parts of `gen2/policy/` share the policy's state, one module each, and `Policy` in its
`__init__.py` keeps the step, the save and the restore. The errands are `Heal` and `Shop` in
`gen2/errands.py`, and `Heal`, `ShoppingController` and `Detour` in `policies/errands.py`. In both
generations a `Trip` holds the errand under way and the offer it was picked under. Gen II saves each
errand's state in a typed record under version 2. Gen I saves no errand state, as before, so a reload starts
its errands afresh, and the detour keeps its waits before the next chat and the next partner training. The
detour records the goal it picks, and the step applies it after the walk, at the same point as before.

## Differences that stay, as adapter settings

These have a reason in the code or in the PR that made them, and they stay.

| Setting | Gen I | Gen II | Reason on record |
|---|---|---|---|
| Options byte | written before each decision | written once after a load | a write per step would change every Gen II trace |
| Real-time clock | none | follows game time | only the Gen II cartridge has a clock |
| Reload after a park | never | on a second stall before new progress | #547, which named it an adapter setting |
| Wait after a policy press | 2 frames | 16 frames | every Gen II trace and gate is played this way |
| Background check | none | rewards and Celebi every 300 frames | Gen II events only |
| League partner (`partner`) | trains a sturdy second battler before the League | none | in the Gen I rules since the first public source, with no PR on record |
| Postgame League gate (`rematch`) | none | a full attack's PP for each opponent, and a deeper team after a loss | Crystal runs ran out of attacks at Lance and lost to him every twenty minutes (`league.run`) |
| Last balls kept (`LAST_BALLS`) | none, the last ball is thrown | 3, while money cannot buy 4 Poké Balls back, except for a species met only once | the Gen II last-ball rule, which moved onto the ledger with the other money rules |

The League partner and the postgame League gate are settings in each generation's boss table
(`planning/league.py`). Item 4 kept play the same, so both stay as they are for now. The last balls kept is
a setting of the spare ball rule in `planning/throws.py`, which both generations' goal pickers ask, so a
hunt whose catch the battle would refuse is not feasible and waits with the reason. All three are open
choices for the owner: each can change in one line, and its gate then shows what the change does.

Two more are data, not settings: Gen II judges only the Johto gyms by matchup, and Falkner has a level
floor. Both are rows in the Gen II boss table (`gen2/readiness.py`).

## Differences to settle

These have no reason on record. Each item that meets one takes the Gen I way, unless its gate shows a loss,
and its PR says which way it went.

1. Manual press: hold 6 and wait 2 in Gen I, hold 8 and wait 8 in Gen II (item 2).
2. Restart: Gen I calls `reset()` on the policy it has, Gen II builds a new one. Both build a new one, so no
   field can outlive a restart (item 2).
3. Saves behind a trade or a custom reward: Gen II never reloads to one, since that would undo the trade.
   Item 2 checks how Gen I keeps the same rule and makes it one.
4. The League partner: Gen I trains a sturdy partner beside the strongest before the League, Gen II does
   not. Item 4 kept it as a setting that stays (above), an open choice for the owner.
5. Gen I's rematch has no readiness gate, Gen II's postgame League has a stamina and depth gate. Item 4
   kept it as a setting that stays (above), an open choice for the owner.
6. The last balls: Gen I throws its last ball, Gen II keeps three while money cannot buy the floor back.
   The spare ball rule kept it as a setting that stays (above), an open choice for the owner.
