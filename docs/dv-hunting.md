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

## Historical validation

The [original September 18 validation report](https://github.com/afk-sapien/PokeSim/blob/5ea6630aab466cbf1f02abde4e3912ee3e90f0b6/docs/validation/local-dv-hunting-20260918.md)
records the copied-save experiments and deployment at that time. Its temporary
checkout paths and release lineage are historical. For current inspection and
counting rules, see [Pokémon stats](pokemon-stats.md) and
[collection goals](collection-goals.md).
