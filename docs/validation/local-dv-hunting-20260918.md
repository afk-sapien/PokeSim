# Continuous DV hunting

The local multi-adventure simulation now treats repeated captures as an ongoing
collection activity. Registration and current battle strength do not disqualify a
species from another hunt.

## Selection and catches

Missing Pokédex entries and current requests from other adventures take precedence.
Routine DV hunts receive a regular share of postgame projects alongside training,
evolution, exploration and supply trips. Hunts rotate through reachable species by
oldest previous hunt, then select an encounter location by distance. A species with
many encounter locations does not receive extra selection chances for each route.

A DV hunt aims for three additional copies, with a bounded expedition time.
Incidental known species are also eligible for capture during that hunt, including
weak, low-level individuals. Capture attempts remain bounded per encounter and use
ordinary balls. Training sessions continue earning experience between hunts.

The Route 22 gate's north and south exits now match the cartridge script. Previously
its dynamic exits were ambiguous in the navigation graph, preventing journeys from
the League side to Viridian Forest and other parts of Kanto.

## Retention, evolution and training

Known DVs rank first within each species. Total DVs determine rank, with the weakest
DV breaking a tie, then current level and other practical investment. Ordinary
storage cleanup keeps the best copy of each species and every perfect individual.
Party members, user locks, offered partners and active project protections remain.
Lower-DV surplus copies can be released as storage space is needed.

Evolution chooses the best DV parent and can improve an already registered evolved
species through ordinary level or stone evolution. Projects follow the selected
individual through PC moves and evolution. Training targets the best DV copies
within a species and continues toward level 100. Perfect partners receive priority.
Distinct species or custom nicknames can disambiguate partners with identical
trainer and DV data. Truly ambiguous individuals remain excluded from targeted
training.

These policy changes apply to the local multi-adventure runtime source at
`/tmp/pokesim-multi-adventure`. The separate desktop distribution checkout at
`/home/ty/Repos/pokesim` has a different lineage. The deployment evidence includes a
patch against the prior local runtime, the candidate wheel and tests.

## Validation

The complete suite passed 1,025 tests with 40 skips. A copied Blue campaign reached
Route 2 and acquired two additional Caterpie at levels 3 and 5 during its bounded
hunt. It also caught low-level Pidgey and Rattata repeatedly. The old policy's
comparison hunt timed out without a capture. These runs used different routes and
frame totals, so they establish behavior rather than a capture-rate benchmark.

A copied Red campaign's long Victory Road journey deferred for lack of recent
progress before reaching its destination. The route graph and ladder fixes improve
access, but do not guarantee that every dungeon expedition will finish within one
project. Ordinary retry backoff remains active, and the hourly monitor continues
checking progress, supplies, storage and trades.

## Deployment

All three original campaigns resumed healthy with advancing frames, 151 Pokédex
entries each, unchanged settings and preserved capture totals. The deployment
contains six changed Python modules and preserves the existing Live and Pokédex
interface assets.

Wheel SHA-256: `04e8ea5c4c6bbd4b183d26ed0523eb2702f18468ffb68a31d385dfb28e32131b`.

Full cold backup and rollback wheel:
`/home/ty/.local/share/pokesim/backups/dv-hunting-20260918`.

Evidence and installed wheel:
`/home/ty/.local/share/pokesim/smoke-20260915/observations/dv-hunting-20260918`.
