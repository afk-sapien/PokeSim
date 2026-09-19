# Continued catching and shared collection priorities

Registered species remain eligible for renewable wild-catching expeditions.
Missing entries and unmet requests from other running adventures take priority
over routine repeat hunts. Within routine choices, absent stock is preferred and
abundant or recently caught species have lower weight. Repeat choices retain a
positive weight and acquire one additional individual before replanning.

Repeat completion uses current stock rather than the existing Pokédex flag.
The stock baseline and recent-repeat history survive checkpoint reloads. Normal
repeat hunts require five ordinary balls and stop after five attempts against an
encounter. Master Balls remain reserved for missing legendary encounters.
Safari repeats use Safari Balls. Existing safety, route, storage, and project
budgets still apply.

The coordinator refreshes each running game's requests from the other games'
missing entries. Requests expire after three minutes without refresh and are
not restored from checkpoints. The policy avoids training away requested copies
and protects the required stock from duplicate release. A single game receives
an empty request set and continues its own collecting.

Validation passed 969 Python tests with 40 skipped. New checks cover repeated
acquisition, saved-project completion, priorities, finite ball use, duplicate
counts, expiring requests, one or multiple games, and safe storage cleanup.

The original Blue checkpoint followed the same active training session for
360,022 frames with both policies. A second comparison cleared that active
project in both copied policy states to exercise the next planning boundary.
Neither comparison changed cartridge memory directly. Within approximately
120,000 frames at that boundary, the candidate completed two separate Bellsprout
hunts. The baseline acquired no Bellsprout. Both retained 151 registered entries
and six party members. The first candidate route exceeded its expedition budget,
then a later reachable route succeeded. The comparisons do not establish
long-term endurance or guaranteed completion of every expedition.

Candidate wheel SHA256:
`098b0d65279e65f61326bcf5d8236dab6118d7c909e55462fb7e0756826d2fe8`.
It changes five runtime modules from the exact previously installed wheel,
retaining the preceding storage-confirmation repair.

All three latest copied saves loaded before installation. The live games resumed
with healthy workers, advancing frames, unchanged campaign identities and
Pokédex counts, zero recovery reloads, and no trade holds. Blue received requests
for two Bellsprout from the two Red adventures. Those live requests do not by
themselves establish that the resulting catches and exchanges have completed.

Private evidence is retained under `observations/repeat-catching-20260918` in the
local smoke data directory. The full cold backup is retained at
`/home/ty/.local/share/pokesim/backups/repeat-catching-20260918`.
