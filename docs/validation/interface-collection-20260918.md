# Collection goals and interface deployment

Deployed September 18, 2026 to the existing three-adventure application on local port 8991.

Changes include persistent level-100 and perfect-DV milestones, perfect-partner protection, the Live trainer card and Adventure notebook, the full PC collection without pagination, and the shared trading history with sprites and verified evolutions.

Validation passed 1,011 Python tests with 40 skips and all eight JavaScript test files. The package was assembled from the verified installed wheel with only the 23 changed feature files. Runtime SHA-256: `3d66dd403bab12c4680a48427fe8bae2459fb916c4a2ba0093afa473d56770f8`.

All games were paused and saved before a clean service stop. A complete cold backup was taken, and the candidate loaded each latest copied checkpoint before installation. The same service restarted with its existing data directory, global settings and navigation backend.

All three campaign identities were preserved. Each resumed healthy with advancing frames, 151 registrations, preserved capture totals and zero reloads. Browser checks confirmed the Live notebook, compact trainer card, all 241 Red Sprout partners, Pokédex milestone indicators, and completed-trade sprites. No script errors were observed.

Private backup: `/home/ty/.local/share/pokesim/backups/interface-collection-20260918`.
Private deployment evidence and wheel: `/home/ty/.local/share/pokesim/smoke-20260915/observations/interface-collection-20260918`.
