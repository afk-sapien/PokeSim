# Acquisition coverage and reward unlocks

## Behavior

- New simulations choose Hitmonlee or Hitmonchan randomly and persist that choice.
  Existing dojo choices remain respected, including completed gifts and active plans.
- An unclaimed dojo gift remains a valid quest even when its species was acquired
  through another route.
- One League victory still earns one level-5 gift. The twelve-species full pool
  uses equal chances among unlocked species. Fossils require a fossil-family
  acquisition, Eevee requires an Eevee-family acquisition, and dojo fighters require
  beating the Karate Master. Mr. Mime and Jynx each require their first acquisition.
- Unlocks persist independently of checkpoint restores. Existing progress qualifies,
  without creating rewards for historical League wins.
- Automatic cable trading can share a unique boxed Pokémon for a recipient's new
  registration. A unique trade-evolution parent may also be exchanged for its evolved
  form when that registers the sender's missing evolution. Party, locks, current
  projects, and repeat-trade protections remain enforced.
- NPC trade projects retrieve the selected boxed reserve, preserve its identity, and
  protect locked partners, strongest battlers, and unique field moves. Corrected the
  Mr. Mime and Jynx NPC targets, prevented trade selection from intercepting field
  move menus, and allowed productive travel battles within the expedition budget.
- Live adventure and Library views show total League wins separately from rewards.
  Pokédex acquisition notes identify unlocked League gift sources.

## Validation

- Full Python regression suite: 930 passed, 40 skipped.
- JavaScript suites: 56 passed.
- Private cartridge cable suite: 36 passed, including restart and movement checks.
- Disposable live-checkpoint replays acquired Mr. Mime in 27,824 frames and Jynx
  in 45,986 frames through actual PC, travel, and NPC trade inputs.
- Read-only live inventory analysis verified eligible Kadabra and Haunter in all
  three games and useful version-exclusive exchanges in both directions.
- Desktop and mobile browser checks verified the win counter, Library counters,
  no mobile overflow, and no JavaScript errors.
- Saved and backed up all three campaigns before installing the package. Live
  checks confirmed preserved campaign IDs, capture totals, Pokédex progress, and
  resumed healthy workers with advancing frames.

Wheel SHA256:
`4788ee55f5cdb65f0a7e8b5f0a4cbe43f3f657fde7b883d435ea209a9ebb9a69`

Private evidence and replays:
`/home/ty/.local/share/pokesim/smoke-20260915/observations/acquisition-coverage-20260917`

Deployment verification:
`/home/ty/.local/share/pokesim/smoke-20260915/acquisition-coverage-upgrade.json`
