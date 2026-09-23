# Changelog

## Unreleased

## 0.3.4

- Keep a save state only for moments worth returning to. A rewind stores a whole emulator save
  state, and one was kept for every *notable* entry — which conflated three different questions,
  because notable also decides what reaches the feed and what sends a notification. Levelling up
  and walking into a Pokémon Center are worth reading and are not worth a snapshot: across two
  live adventures they were 1,261 of 2,840 states, and 82% of states belonged to types nobody
  would rewind to. States are now kept for badges, Hall of Fame runs, new partners, evolutions,
  blackouts, stalls and legendary retries only. Existing entries keep the states they already
  have, so no rewind that works today stops working.

## 0.3.3

- Compress the save state kept with every notable journal entry. A PyBoy state is 167 KB of
  mostly zeroed RAM and gzips about ten to one; one is stored for each notable entry so the
  journal can rewind to that moment, and they are only ever added to. A live server was carrying
  456 MB of them across two adventures — 2,836 states against 68 MB of screenshots — which is
  where essentially all of the "40 MB an hour" went. States written before this release stay
  readable, so an existing library keeps resuming and every old entry keeps its rewind.

## 0.3.2

- Stop staging backups and imports in the container's `/tmp`. `create_backup` copied `assets`,
  `adventures` and `interactions` into an unqualified `TemporaryDirectory` before writing
  anything, and the shipped Compose file mounts `/tmp` as a 256 MB tmpfs on a read-only root, so
  the copy went to RAM and failed on any library past about a quarter of a gigabyte — a library
  reaches that in a few hours. The backup stops every adventure first and restarts them in its
  `finally`, so the pre-upgrade backup an operator is told to take was exactly the operation that
  could not finish. Both legacy import paths had the same defect, including the one that extracts
  up to two gigabytes. All three now stage inside the application folder, which is what the
  restore path and three other callers already did.
- Delete the attempt directories of finished Cable Club exchanges. Every attempt keeps two save
  states, two cartridge saves and two screenshots — about half a megabyte — and nothing ever
  removed them, so `interactions/` grew with every exchange and every backup copied the whole
  accumulated tree into its archive. The live server had 377 of them, 174 MB. The newest twenty
  resolved exchanges are kept, an unresolved one is never touched whatever its age because
  recovery still needs its outputs, and zero means keep everything, as it does for autosaves and
  stall bundles. The legacy coordinator already did this; the application one never got it.
- Let an adventure bound its own journal. Every notable event stores a full save state beside its
  screenshot, about 40 MB an hour, and `prune_events` has always existed to trim it — but
  `event_retention_days` was missing from the Library's settings whitelist, so a managed
  adventure could not set it and the pruning call was permanently dead. The live server had
  560 MB of event states across two adventures.
- Answer a busy emulator with a retry instead of an internal error. `runtime.call` raises
  `TimeoutError` when the emulator thread has not reached a queued participant operation in
  45 seconds, and its message asks the caller to retry the same operation — but `TimeoutError` is
  an `OSError`, not a `RuntimeError`, so it escaped the handler's tuple and became a 500 with a
  full traceback in the worker log. Seen firing during ordinary play on the live server, not only
  during shutdown.
- Back off a recovery that keeps failing. An interrupted exchange that cannot be finished — a
  participant record lost to a restore, say — was re-driven every 30 seconds indefinitely, and
  each pass starts the worker again through the recovery path that deliberately ignores a stop
  request. Retries still never give up, because a committed exchange has to be completed on both
  sides, but the interval now doubles to ten minutes and the status explains itself after the
  third failure rather than repeating that progress is saved.

## 0.3.1

- Stop reporting a blackout for a Pokémon that is still being named. `AddPartyMon` raises the party
  count and writes the species list before the nickname screen, and only fills the struct at
  `wPartyMons` once naming is over, so for the 27 seconds that screen is up the new partner reads as
  species 0 with no HP. That counted as a fainted team, so every new adventure recorded two
  "Blacked out!" entries on its way out of Oak's lab and sent the matching notifications, and the
  live page showed the slot as `No Mon`, level 0, fainted. A counted slot the cartridge has not
  filled in yet is now held apart from the team it is joining.
- Stop registering four starters the player never received. The region the Pokédex flags will later
  occupy holds other values for a couple of seconds in Oak's lab, which read as owning Bulbasaur,
  Ivysaur, Charmander and Squirtle at once and put all four in the journal. Every cartridge path
  that registers a species also marks it seen, so an owned flag arriving without its seen flag is
  not Pokédex data and is no longer read as any.
- Keep the post-trade checks when assertions are turned off. The verification that a staged
  exchange left the party, badges, bag, box counts and every untraded slot alone, and that the
  arriving Pokémon is the agreed one down to its struct and original trainer, was written as bare
  `assert` statements, as was the checksum compared just before a staged checkpoint is adopted.
  `python -O` removes those outright, which would have marked a corrupted exchange staged and
  adopted it without a word. They raise now.
- Decode an adventure's response in the application before forwarding it. The proxy streamed the
  child's raw bytes while dropping `content-encoding` from the headers it passes on, so any
  compressed response would have reached the browser as undeclared gzip. Nothing compresses one
  today, which is the only reason this was invisible.
- Name the commands in `pokesim --help`. The help listed the flags for serving the library and
  nothing else, so `adventures`, `import`, `import-pair`, `backup` and `restore` could only be
  found by reading the source, and the usage line called the program `__main__.py` rather than the
  command that was installed.
- Darken the small print on the Pokédex cards. The entry number, the caught and seen notes and an
  unencountered species' name sat between 2.5 and 3.7 to 1 against the card, at nine pixels, so the
  line telling you whether you have caught something was the hardest thing on the page to read.
  Every one of them now clears 4.5 to 1.
- Remove four tools that did nothing of their own. `gen_collection.py`, `gen_strategy.py` and
  `gen_tables.py` were byte-identical shims around `pokesim.prepare_data`, which the data tools now
  name directly, and `prepare_desktop_test_data.py` differed from its sibling by one word of
  docstring. A personal checkout path no longer appears in `link_spike.py`'s error message, and
  `sample_live.py` asks for a host instead of defaulting to one homeserver's name.
- Retake the README screenshots against a library that has a portrait pack installed. Every
  collection view in the old set showed empty squares where the portraits go, which is what a
  reader saw first and is not what the application does: a missing portrait has drawn a numbered
  placeholder since 0.2.0. The live shot is now a battle at 1x rather than whatever frame Max
  speed happened to be on, the PC is sorted by DV rating the way the text beside it claims, the
  Journal has a picture of its own for the first time, and the unreferenced PNG copy of each view
  is gone from the source package.

## 0.3.0

- Stack the plan row on a narrow screen. The three columns it reads across kept their layout at
  every width, so the live page scrolled sideways on a 320 pixel phone.
- Stop reading finished Cable Club trades at startup. Every completed exchange kept the whole
  policy snapshot it was staged from, which on a long-running adventure is mostly the learned
  navigation graph, and startup parsed all of them to act on none of them. An adventure with 229
  finished trades needed more than three gigabytes to open, missed its readiness deadline, and was
  started again by the trade recovery waiting on it, which held the machine in that loop until
  nothing else on it could run. Recovery now reads only unfinished exchanges, releasing a trade
  drops the snapshot it no longer needs, and records kept by earlier versions are compacted as
  adventures start.
- Say why an adventure would not start. The cleanup that stops a worker which never became ready
  reported its own shutdown deadline instead, so the reason the adventure failed was replaced by a
  message about stopping it everywhere that error was shown.
- Train in steps of ten levels instead of aiming straight at 100. Training was also the only kind
  of work exempt from the planner's recency decay, so once it started it kept winning the draw and
  a single partner could hold an adventure for hundreds of game hours while trades and unregistered
  species waited. It still leads when there is nothing new to register, by 247 draws to 173 in the
  settled case, rather than by never stopping.
- Value a trade that triggers an evolution at 40 even when the evolved species is already
  registered. Kadabra coming back an Alakazam scored nothing once Alakazam was in the book, despite
  the cable being the only way it can happen.
- Say what crossed the Cable Club. A completed trade recorded the same sentence every time and drew
  a placeholder beside it; the entry now names both Pokémon and the trainer on the other end, and
  the journal card shows the two of them either side of a swap arrow. Events gained a `detail`
  column for that, added by the store's own migration. Trades staged by an older build keep the
  previous wording.
- Build nicknames from prefix and suffix pairs, 1,616 of them instead of 100. An adventure
  remembers every name it has used, so after a hundred Pokémon the draw fell back to the whole list
  and began repeating. The written names are unchanged and still come first.
- Encode a game frame only while something is asking for one, and no faster than the stream shows
  them. At Max speed the emulator was encoding about 1,100 JPEGs a second for a viewer that shows
  fifteen, whether or not a browser was open: Max goes from about 74x to about 314x real time.
- Decode screen tiles and event flags from lookup tables, worth about 14% of a headless run on its
  own.
- Simplify the top bar. The adventure bar carried eight items in one row using three different
  looks for navigation, and the link that left the adventure was bolder than the page you were on.
  One breadcrumb answers where you are, tabs share one active treatment with the library, and the
  edition badge that three other places already stated is gone.
- Give the live page its space back. The plan moves to a full-width row along the foot, the game
  screen grows from 400 to 560 pixels, and the team column runs the full height beside it with six
  slots, each card carrying its moves, remaining PP and DV rating.
- Hold the plan steady. The planner reports its gap between projects as an objective of its own, so
  the row cycled between the real goal, "Plan the next adventure project" and the ceremony several
  times a minute.
- Cut the Pokédex overview to registered, seen, caught, level 100 and perfect finds. Level 100 was
  labelled and badged with a star, which put a milestone in the same visual language as the DV
  ratings beside it; it reads as a flag now. Three-star DVs are still recorded, badged and
  filterable.
- Give the app a mark of its own, a handheld rather than the `p.` lockup, in the browser tab and
  the top bar.
- Let the seed vary a stall hunt that continues from a checkpoint. A checkpoint carries the policy's
  own random state, so `tools/find_stalls.py --seed` was ignored and four postgame hunts with four
  seeds were one hunt repeated four times. Scenario replays still make the original choices.
- Put new Pokédex entries before the level 100 grind. While any missing species can be caught or
  evolved, those projects are chosen about two times in three and training about one in five. It
  used to be the other way round, and wild Pokémon stop near level 45, so two adventures spent most
  of 400 game hours in Pokémon Mansion with 27 obtainable entries missing. Once nothing new is on
  offer, training leads as before.
- Evolve a partner with a stone before training it to level 100. A Weepinbell was being trained
  with Victreebel unregistered.
- Stop building standalone executable bundles. The PyInstaller build, its checks and its workflow are
  removed. Install the Python package with pipx, or run the container.

## 0.2.1

- Train for the League in Route 23's grass. Training places were found by the overworld's grass
  tile, and Route 23 uses the Plateau tileset's, so the goal had no destination. A fresh run with
  eight badges drifted along Route 21 for seventeen game hours before entering the League.
- Keep Mt. Moon as the goal wherever a side project leads before it is cleared. Back in Viridian
  Forest the goal became training for Misty on Route 24, which lies beyond the mountain, so two of
  three fresh runs wandered between Route 1 and Route 22 and reached Misty after nine game hours
  instead of three.
- Choose the second League battler the same way whatever the party order. With two partners tied
  for the highest level, moving the chosen partner to the lead changed the choice, and a run with
  eight badges swapped Lapras and Muk in the party menu of Pokémon Mansion indefinitely.
- Keep each stall for later. An adventure's `stalls/` folder holds the moment a stall was reported
  beside the first autosave after the last achievement, which the rotating autosaves had long
  dropped by then. `KEEP_STALL_BUNDLES` sets how many are kept, 5 by default, 0 for none.
- Replay stuck scenarios as regression tests with `tools/stuck_scenarios.py`. A scenario is a copied
  save, optionally edited into a harder situation such as a frozen party with no cures at the League door.
- End a battle in which nobody can act. The original trainer routine favours any move of a super
  effective type, so Lorelei's Dewgong only uses Rest against a frozen Muk and never knocks it out.
  The player hands over to a partner the foe does attack, and when there is none the save from
  before the battle is reloaded at once instead of after the battle timeout.

## 0.2.0

- Respect the badge checks on Route 23, plan restocking only at shops that can be reached, and spend
  vitamins and Rare Candies when the bag is too full to buy Poké Balls. A run with six badges and a
  bag of keepsakes argued with the Volcano Badge guard on its way to the Indigo Plateau shop.
- Restart a League attempt that cannot be finished. A checkpoint is kept from the moment the
  attempt begins, and it is used when a battle runs past the timeout twice with no progress between.
- Tell party members of one species apart when changing the lead. With two Haunters the run
  thought the stronger one already led, and reopened the party menu at a gym door forever.
- Buy Full Heals before the League, keep the save from before an endless battle until the
  timeout reloads it, and idle a random moment after that reload so the battle plays out
  differently. Lance's Dragonair can use Agility forever against a frozen last partner.
- Heal at a real Center once Silph Co is freed, because its nurse stops healing then, and stand
  next to her before that instead of two squares away. A sleeping partner kept a run at her side indefinitely.
- Hand over or revive a partner when the active Pokémon is frozen. Freeze never thaws in these
  games, and a foe with only Normal attacks could not finish a frozen Ghost, so the battle never ended.
- Find a Cut, Surf or Strength partner in any PC box and open that box before withdrawing.
  A run whose gift Lapras sat in another box hunted for a Surf partner it could never reach.
- Keep fighting with the last partner standing. The party menu used to choose the partner
  already in battle, which the game refuses, and the battle never ended.
- Leave edge exits such as cave mouths by walking outward. A run that needed healing paced
  between Victory Road 2F's two east exit squares indefinitely.
- Sell a spare valuable to raise the Safari Zone entry fee. A run that reached the gate
  short of the fee used to talk to the attendant indefinitely, and shopping now leaves
  the fee untouched until Surf and the Gold Teeth are collected.
- Report a stall. An adventure with no achievement for two hours of game time and
  fifteen real minutes records a `stall` journal entry with the saved moment, shows
  Stuck? on Live, and sets `stalled` in the Library summary. Managed trades do not
  count as progress. `STALL_ALERT_GAME_MINUTES=0` turns it off.
- Add `tools/find_stalls.py`, which plays an isolated adventure at full speed and keeps
  a replayable bundle for every stall it finds.
- Keep the last Surf partner out of automatic trades, and stop revisiting the Silph
  worker once his Lapras is registered. A run that traded the gift Lapras away before
  collecting HM03 had no reachable way to cross water.
- Set up phone notifications from the Library's new Notifications page, with no
  account or settings file. Choose the ntfy server and topic, generate a random
  topic, add an optional access token, and send a test notification.
- Choose which adventures notify and which kinds of news are sent, including a
  "Stuck or needs attention" kind. Changes reach running adventures right away.
- Name the adventure in every notification title, and announce completed trades once.
- Keep `NTFY_URL`, `NTFY_TOKEN`, `NTFY_MIN_PRIORITY` and `NTFY_MUTE` as the defaults
  until notifications are saved in the Library.

## 0.1.2

- Install with one pipx or pip command from the repository, with no checkout, uv,
  or release URL to keep up to date.
- Point the container quick start at the latest published release and image.

## 0.1.1

- Show All Pokémon in the PC as a compact card grid again, so many more partners
  fit on screen. Lock and trade actions are in each partner's details.

## 0.1.0

- Show the trainer, badges, registrations, League wins, money and play time above
  the Live game and party panels.
- Publish GHCR images automatically when a GitHub release is published, with anonymous pull
  verification, and versioned Compose downloads for Python and Docker releases.
- Consolidate the Adventure Library and independent Red and Blue workers on main.
- Coordinate automatic Cable Club trading with protected partners and recovery.
- Add PC DV star ratings, rating filters, and persistent three-star Pokédex counts.
- Keep level 100 and perfect-DV milestones across checkpoint restores.
- Track captures, current ownership, and individual League victories.
- Improve repeat catching, training, NPC exchanges, healing, and PC cleanup.
- Preserve party detail dialogs and use one global simulation pace setting.
- Update dependencies and verify Python installations across five native targets.
- Align publication with Python packages and Docker, verified draft checksums,
  and the Adventure Library startup and worker lifecycle.

## 0.2.0rc31, experimental beta

Desktop setup, collection controls, and lifecycle hardening. Existing deployments
must be upgraded separately.

### Lifecycle and verification

- Report final-save failures as unsuccessful server exits.
- Share runtime ownership between desktop and server launchers. Hold an adventure
  directory lock until the worker stops and its database closes.
- Clear stale input, recovery timers, and transient menu state on appropriate
  transitions while preserving checkpoint memory and existing journal history.
- Extract shopping and storage controllers with explicit state and decision inputs.
- Report source revision and dirty state, and embed build identity in distributions.
- Add real Chromium scenarios to CI and release checks, plus bounded private replay
  comparisons with progress sampling and input-integrity checks.

### One-time Mew reward

- Award one level-5 Mew after defeating the final Champion rival, separately from
  repeatable Championship rewards. Existing Mew registrations and delivery records
  prevent another gift after rematches, trades, or reloads.
- Remove Mew from the random reward pool. Preserve pending selections for the other
  seven species and existing Pokémon. Reward-enabled coordinators also enable the
  separate Mew gift, including policies carrying the older disabled Mew flag.

### Desktop and collection controls

- Add the desktop launcher with local browser setup, verified reference preparation,
  persistent save locations, process locking, and native packaging workflows.
- Add game-local trading views, explicit offers and withdrawals, and partner locks
  that protect against automatic release and trading.
- Separate physical box browsing from the sortable whole-collection view.

### Repository maintenance

- Index current documentation and archive earlier roadmap, status, and operations logs.
- Extract event-page rendering and its rewind handler. Display rejected rewind requests
  without leaving the event page.
- Run all browser checks and local documentation link checks in CI and release validation.
- Include README screenshots in source packages and verify newer runtime assets.

## 0.2.0rc30, avoid distant shopping for optional supplies

- Require affordable core supplies or saleable items before starting distant ordinary
  shopping trips. Keep optional top-ups in the current mart and preserve legendary preparation.

## 0.2.0rc29, renew preparation through real training gains

- Renew preparation time only when the selected trainee gains XP. Bound total training
  and preparation to 150 game minutes while retaining inactivity checks.

## 0.2.0rc28, productive training with bounded preparation

- Separate preparation from active training budgets, persist progress across saves and
  trades, and favor nearby training targets. Show preparation separately in Live.

## 0.2.0rc27, include the party in PC comparisons

- Include party members in combined searches, sorting, and strongest-partner rankings.
  Add a Party scope with the same stat details as boxed Pokémon.

## 0.2.0rc26, find the strongest stored partners

- Add Power and individual-stat sorts using calculated current-level stats, plus a
  strongest-partners shortcut and five-stat breakdown.

## 0.2.0rc25, retreat from stalled Victory Road healing

- Try one ordinary Escape Rope when healing recovery stalls in Victory Road. Preserve
  the attempt across saves and trades until the party is fully healed.
- Preserve recent valid event observations through short invalid PC-transfer readings.

## 0.2.0rc24, independent exchange safe points

- Request each game's safe checkpoint independently within a shared retry window.
  Abort rejected or timed-out preparation and release its holds.

## 0.2.0rc23, share safe points between rewards and trades

- Give overdue useful exchanges a turn after reward delivery attempts. Persist the
  scheduling state so a reward backlog cannot indefinitely displace trades.

## 0.2.0rc22, recognize PC withdrawals in either write order

- Avoid recording a release when cartridge RAM updates a withdrawal in separate steps.
  Retain genuine release events and existing journal history.

## 0.2.0rc21, complete Articuno's current puzzle

- Plan the Seafoam B3F boulder drops before attempting Surf on B4F, preserve completed
  drops across reentry, and avoid dropping the player through the holes.

## 0.2.0rc20, recover missed legendary encounters

- Restore eligible missed encounters after leaving the room and waiting a persistent
  retry delay. Preserve damage, spent items, and progress. Registered species stay resolved.
- Correct generated toggle-object indexing used by late-map visibility flags.

## 0.2.0rc19, prepare and complete legendary expeditions

- Give legendary projects their own priority, bounded budget, supply preparation, and
  progress accounting. Use status and balls without potentially lethal damage attacks.

## 0.2.0rc18, repeatable Championship rewards

- Award one random level-5 starter, Eevee, fossil Pokémon, or Mew for each newly observed
  Championship, with durable delivery and pending claims when storage is full.
  The rc31 candidate above separates Mew from this historical pool.

## 0.2.0rc17, varied choices and broader exchanges

- New runs choose a seeded random fossil and Eevee evolution, persisted across reloads.
- Optional last-copy trades unlock new Pokédex registrations while protecting parties,
  current projects, and explicitly protected species. Unique partners are not exchanged
  merely to restore collection gaps or improve stats.
- An optional one-time postgame PokeSim Mew distribution uses backed-up checkpoints,
  verified inventory preservation, and the existing durable hold and recovery controls.
  Gifts are labeled as custom events and counted separately from trades.
- Starter and Eevee supply farming remain outside scope.

## 0.2.0rc16, scoped automatic trading

- Coordinate trades through authenticated controls and durable game holds, without Docker access or a root service.
- Recover holds across game restarts and load both committed inventories before releasing either adventure.

## 0.2.0rc15, regular exchanges between trusted adventures

- Enable useful spare exchanges for explicitly configured peers, including exclusives, trade evolutions, and meaningful training upgrades.
- Stage and verify both saves, journal completed exchanges, and recover interrupted transactions without repeating a swap.
- Prevent restores from undoing one side of a completed exchange. Show trade history and opportunities on the board.

## 0.2.0rc14, compare stored partners

- Sort selected or all storage boxes by level, total DVs, total stat experience, total experience, Pokédex number, species, nickname, or box order.
- Apply sorting before pagination, keep the selection in the URL, and show individual stat totals on cards and in details.

- Record verified training gains as partial progress when the idle guard abandons a project.
- Keep the idle deadline and retry delay, without escalating productive attempts as repeated failures.

## 0.2.0rc13, count reserve preparation once

- Start a fresh training idle window when the selected partner first reaches a stable party snapshot.
- Persist that milestone through reloads and keep the overall expedition deadline unchanged.

## 0.2.0rc12, leave Seafoam through the ladders

- Avoid Seafoam floor holes during routine navigation, including remembered steps that previously fell between floors.
- Route exhausted parties out of the fall-and-current loop to healing and resume the adventure.
- Keep the held rc11 obstacle experiment out of this release.

## 0.2.0rc11 candidate, respect obstacles on remembered routes

- Apply observed solid-object positions to remembered steps on the current map. Preserve distant learned routes until fresh object positions are available.
- Stop walking through a remembered Victory Road route when a boulder has returned to the path.
- Allow the route again when the object moves away or is confirmed hidden.

## 0.2.0rc10, verify training after PC transfers

- Accept training progress in battle or after returning to the overworld, avoiding temporary level values during PC withdrawals.
- Keep transfers and missing party entries from resetting the training idle timer.
- Preserve project state across reloads and count subsequent experience and level gains normally.

## 0.2.0rc9, recover routes after Victory Road switches reset

- Ignore remembered steps through currently closed puzzle gates.
- Reach the upper puzzle by ladder when reentry leaves the lower boulder inaccessible.
- Preserve existing saves, parties, and ongoing postgame projects.

## 0.2.0rc8, persistent postgame projects and varied starters

- Collect nearby reachable ground items during ordinary travel and collection expeditions, including caves. Verify collection, respect bag capacity, and preserve the original project during bounded detours.
- Choose a seeded random starter for new adventures, with a persisted choice and a fixed `STARTER` setting.
- Rotate postgame collection, evolution, training, and exploration projects using persistent recent choices and outcomes.
- Train party and stored partners toward level milestones, with progress measured for the selected partner.
- Increase retry delays for repeated failures and bound the retained planning history.
- Keep old checkpoint compatibility and retain existing Pokémon when configuration changes.

- Register the received Pokémon and any trade evolution in the recipient's Pokédex when staging a save-based exchange. Verified on copied Red and Blue saves. Live trading remains disabled.

## 0.2.0rc7, continuing adventures and visible progress

- Restore planner timing safely and replan stationary objectives without rewinding the game.
- Clear the loose east-corridor boulder when returning through Victory Road.
- Check every expedition's route and retire unproductive objectives with a retry cooldown.
- Show Live activity and the last achievement with its age.
- Keep playtime announcement history across checkpoint reloads.
- Package the read-only trade board and save-based trade executor.
- Consolidate the deployed Live, Pokédex, PC, journal, nickname, storage, and persistent clock work into a reproducible release.

- Add a `/pokedex` page: all 151 entries with types, base stats, learnsets, evolution families, and Kanto locations, filtered by search, type, record, and availability.
- Show the traveling party and every storage box, with each resident linked to its Pokédex entry.
- Serve entry data from `/api/pokedex` and live records from `/api/pokedex/status`, and link out to Bulbapedia, Serebii, and Wikipedia.
- Add sixteen tests covering the reference data, the live status shape, and the new endpoints.
- Stop planning Pokédex projects that need the PC when storage cannot serve them: with a full party and every box full, the run no longer walks to a PC and cycles its menu.
- Release spare stored duplicates to keep about five storage slots free, so an unattended run never runs out of room. One copy of every species always survives, the lowest-level duplicate goes first, and a current evolution project's partner is never released.
- Answer a release confirmation only while a release is the active goal, and decline it otherwise.
- Record releases in the journal at minimal priority.

## 0.2.0rc6, unidentified ghost encounters

- Flee wild Pokémon Tower encounters before obtaining the Silph Scope.
- Preserve normal decisions for trainers, identified ghosts, and battles outside the Tower.
- Add ten regression cases and verify escape from a copied stalled checkpoint.

## 0.2.0rc5, storage withdrawal fix

- Allow an evolution partner to be withdrawn from a full box when the party has space.
- Stop selecting the source box again once it is already active.
- Keep capacity handling for full parties and boxes without the requested partner.
- Add four regression tests and verify the fix against a copied game checkpoint.

## 0.2.0rc4, reliable game display

- Load and decode one game image at a time, capped at 10 display frames per second independently of game speed.
- Retain the last good image through request failures and invalid frames, with bounded timeouts and automatic recovery.
- Stop hidden-tab frame downloads and remove competing MJPEG reconnect handlers.
- Add browser-controller regression tests for serialization, decode failures, timeouts, and visibility changes.
- Leave emulator behavior, game speed, save formats, and health checks unchanged.

## 0.2.0rc3, planner reliability fix

- Share one bounded navigation search across collection candidates to prevent repeated route searches from stalling emulation after the League.
- Keep the health threshold unchanged and add regression tests for search reuse, directionality, obstacles, and search limits.
- Preserve failing health details and correct stopped-run statuses in the endurance harness.
- Detect campaign completion from the saved Hall of Fame count after leaving the ceremony.
- Include Docker, Compose, proxy, and validation files in the Python source archive.
- Correct release status claims to disclose the failed earlier endurance run.

## 0.2.0rc2, experimental public beta

- Start a clean public source history with original code under MIT.
- Publish versioned Docker image archives and source packages with checksums, without requiring registry or GitHub credentials to download.
- Document local game-data preparation, supported platforms, access controls, backup, upgrade, and rollback.
- Provide private vulnerability reporting and explicit beta limitations.
- Preserve the gameplay and checkpoint behavior of the candidate under endurance testing.

The prior engineering candidate established atomic checkpoint recovery, rootless containers, authenticated proxy deployment, dependency notices and emulator source preservation, and local preparation of game content. The first endurance run later stopped on a campaign health failure. See RELEASE_STATUS.md for current results.
