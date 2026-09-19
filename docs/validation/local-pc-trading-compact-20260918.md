# Compact PC and Trading layout validation

Published four static files to the existing local runtime without a service restart.
The accompanying patch records the runtime changes relative to the deployed files.
PC and legacy Trading changes are also applied to the main checkout. The shared
Trading template exists only in the multi-adventure runtime source.

- PC summary and view selection share one row on desktop.
- Search, sort and order inputs align at 215 pixels from the top.
- The Pokemon grid begins at 323.5 pixels on desktop.
- Shared Trading cards measure 101 pixels high on desktop.
- PC Boxes, All Pokemon and shared Trading have no horizontal overflow in 390 and 320 pixel frames.
- Name and Pokedex number searches, DV sorting, view switching, power disclosure and Pokemon details were checked in the browser.
- All eight runtime and all five main checkout JavaScript test files passed.
- The original service PID stayed unchanged. All three games advanced, remained healthy and reported zero reloads.

Backup and checksums:
`/home/ty/.local/share/pokesim/backups/pc-trading-compact-20260918/deployment.json`

Runtime source:
`/tmp/pokesim-multi-adventure`

The hourly monitor includes the new static override checksums.

Follow-up: Party spans both desktop columns above six equal rows of boxes. Browser measurements verified a 190 pixel Party row and paired 92 pixel box buttons.
