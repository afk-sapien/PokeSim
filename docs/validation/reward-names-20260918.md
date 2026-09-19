# Random names for League rewards

Newly delivered Elite Four and Champion reward Pokémon now receive a random nickname from the existing caught-Pokémon name pool. The cartridge nickname is populated during reward staging, so PC, party, trade, and save data use the same name. The managed reward journal includes the nickname and species.

Nickname selection uses a separate hash of the existing reward seed. Delivery retries generate the same nickname without changing reward species, trainer identity, DVs, moves, experience, or other Pokémon data. Both the managed delivery path and legacy reward staging use the new option. Existing Pokémon and the one-time Mew gift retain their current naming behavior.

Validation: 981 tests passed and 40 skipped, with one existing Starlette warning. Across all 11 reward species and 20 seeds each, names came from the normal name pool, differed from the default species names, fit Generation I's ten-character limit, encoded to eleven-byte cartridge fields, and remained identical on retry. Stats and original trainer data remained byte-for-byte identical to the equivalent unnamed gift.

Wheel SHA-256: `c5a14f707348d484e3b6644e4e99d718637c0fa2dc6b868471924841addbf0ca`.

Deployment verification after startup confirmed all three original campaigns advancing with 151 Pokédex entries, healthy workers, and zero reloads. All existing partners were retained.

Full backup: `/home/ty/.local/share/pokesim/backups/reward-names-20260918`.

Private evidence: `/home/ty/.local/share/pokesim/smoke-20260915/observations/reward-names-20260918`.
