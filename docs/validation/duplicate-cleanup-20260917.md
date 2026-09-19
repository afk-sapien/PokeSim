# One-time duplicate cleanup

The user requested removal of accumulated excess Pokémon after the capture
diversity repair. This maintenance changes existing inventories only.

For species with more than five copies, retain the three strongest individuals
using the existing quality ranking. Also retain the best total DVs, all party
members, locked or offered individuals, and the current training or evolution
project's protected species. Groups of five or fewer remain unchanged.

| Adventure | Stored before | Stored after | Removed | Machoke remaining |
| --- | ---: | ---: | ---: | ---: |
| Red Sprout | 234 | 149 | 85 | 4 |
| Blue Ripple | 235 | 150 | 85 | 3 |
| Red Ember | 234 | 130 | 104 | 4 |

Total removed: 274, including 145 Machoke.

## Verification

- Paused all three adventures with no active trades, backed up their databases
  and checkpoints, then stopped the app before editing disposable copies.
- Compacted selected slots within their existing boxes and refreshed box-bank
  checksums. Compared every retained record, nickname, and original trainer name
  byte for byte against the source.
- Verified that all WRAM differences fell within the active box region and that
  party data was unchanged. Reloaded each output checkpoint in a separate emulator
  and compared the complete parsed snapshot.
- Preserved checkpoint metadata and checked the current trade and reward barriers
  before adoption. No emulation frames ran during the edits.
- Restarted the existing local app. All campaigns retained their identities,
  Pokédex progress, six party members, and capture totals. All three advanced in
  the live follow-up sample.
- Targeted maintenance, capture diversity, and box tests passed. Private tests
  requiring separately configured cartridge fixtures were skipped in that run.

Private backups, exact removal lists, and live verification are under
`/home/ty/.local/share/pokesim/smoke-20260915/observations/duplicate-cleanup-20260917`.
The installed application package did not change.
