# League rematch rewind after PC withdrawal

Read-only diagnostics on the home server found repeated invalid-state reloads in
PokeSim 0.4.16. The live run reached Victory Road, then returned to a checkpoint
at Viridian Pokémon Center. Worker logs showed a reload about once per minute,
with autosaves rejected while the party remained invalid.

The retained checkpoint contained five healthy party members. Replaying its
ordinary PC withdrawal added Vaporeon with stored HP above its recalculated
maximum. The live state reported 463 HP against a 461 maximum. The existing
healing policy did not treat excess HP as needing a nurse, while snapshot
validation correctly rejected it. This made the same withdrawal and journey
repeat after each reload.

The correction requests normal Pokémon Center healing whenever a party member
has HP above its maximum. Snapshot validation remains strict. The emulator gives
a bounded healing window at a verified Center when excess HP is the only
validation problem. The window scales for speeds below 1×. Other invalid states
retain their existing deadline, and invalid snapshots still cannot be autosaved.
No RAM values, DVs, Pokémon identities, or live saves are edited.

## Replay evidence

The checkpoint and ROM stayed on the home server. A separate headless emulator
loaded them in memory without saving, sending notifications, or participating in
trades. Its policy used the proposed excess-HP healing condition. This was a
policy replay, not a deployment of the changed application.

- The original policy reproduced the invalid withdrawal at frame 486.
- With the correction, normal nurse interaction restored a valid party by frame 1,222.
- The replay entered Victory Road 1F at frame 12,554, 2F at 26,790, and 3F at 31,502.
- It completed the remaining switches, exited onto Route 23 at frame 50,854, and reached Indigo Plateau at frame 52,014.
- The complete corrected replay took 101.2 seconds of wall time with no save reloads.

The diagnostic replay left the real simulation and retained files unchanged.
The subsequent authorized home-server deployment is recorded below.

## Regression coverage

The targeted strategy, RAM validity, event observation, recovery, and emulator
checks passed 110 tests. Another 97 travel, collection, training, League rotation,
and snapshot cache tests passed. New tests cover healing before departure, preserving
strict validity until healing completes, bounded recovery at Max and slower
speeds, and retaining ordinary reload deadlines outside Centers or when other
fields are invalid.

## Historical DV investigation

Further read-only inspection checked 803 retained event checkpoints and 691
additional reward, interaction, and recovery checkpoints on the server. This
identified a change in the stored individual data, rather than an incorrect HP
formula:

- The level-five Eevee and its Vaporeon evolution had stored DV bytes `57 fd`.
- At level 100 with maximum stat experience, those DVs correctly produce 463 HP.
- A later boxed record has DV bytes `57 fe`, with all other 32 record bytes unchanged.
- Special DV increased from 13 to 14. Its parity change lowers derived HP DV from
  15 to 14, so the recalculated maximum becomes 461 while stored current HP stays 463.

The last healthy retained reward checkpoint is
`custom-rewards/f786ab2389e64fad9240c2d1422fd89e/result.state`.
The first changed record found in the retained sequence is
`interactions/cd069024df6b4dc5a170d1862587dbf7/source.state`.
Their filesystem timestamps are approximately five minutes apart. The changed
byte is already present before that Cable Club exchange, so the exchange itself
cannot explain the initial change. Earlier checkpoints also show that leveling
to 100 and evolution completed with the original DVs.

A 300,022-frame isolated policy replay from the healthy reward checkpoint did
not reproduce the DV mutation. A second replay exercised additional storage
cleanup and withdrawal of the same Dewgong that left storage in the historical
window. These are diagnostic replays with different controller state, not an
exact replay of the live process. They do not prove that PC handling, cartridge
behavior, or other application paths are free of the originating bug.

The healing correction fixes the reproducible reload loop. The instruction or
application operation that first changed the DV byte remains unproven. Do not
describe the originating DV corruption as fixed, and do not rewrite an individual
or its identity based only on excess HP.


## Home-server recovery hotfix

On October 3, the owner authorized applying the recovery update to the home
server. A local image based on published 0.4.16 carries only the three recovery
changes in `policies/battle.py`, `ram.py`, and `emulator.py`. The build verifies
the original source hashes before patching. Other pending changes remain local.

- Image: `pokesim-local:0.4.16-hp-recovery-20261003`
- Image ID: `sha256:9d17a1a8494b8ee4d83fd9c821c26444e085c67b348e503d804c2e30f04c3821`
- Server build context: `/opt/pokesim/hotfixes/withdrawal-hp-20261003`
- Server deployment receipt: `/opt/pokesim/backups/hotfix-0.4.16-hp-recovery-20261003T170844Z.json`
- Verified cold backup: `pre-0.4.16-hp-recovery-20261003T170844Z.tar.gz`, 291,111,980 bytes and 70,277 entries.

Compose now selects this local image through `POKESIM_IMAGE`. The deployment
script retains the previous environment file and restores the previous image if
startup fails. A future released image containing the fix should replace this
local image selection through the normal upgrade process.

The focused local suite passed 56 tests. The built server image also passed
isolated excess-HP healing and bounded-recovery checks with read-only game data.
After restart, Red, Blue, Fresh Start, and Release Check resumed running. Bababa
remained stopped. Red healed MOPWATER to 461/461 HP and resumed the League
rematch objective. No save or DV values were manually rewritten.

Live verification then confirmed all five League trainer victories and
`Champion! League victory #379` at Unix time 1791047689.1303492. Red had zero
reloads since the update and continued into a new training project. A new
autosave at frame 814,417,998 was written at Unix time 1791047761.8872416,
confirming that valid progress is being persisted beyond the old rewind loop.
The original cause of the historical DV-byte change remains unresolved.
