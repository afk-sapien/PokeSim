# PokeSim 0.7.0

This release adds accounts and trade offers between people, gives every stored Pokémon a PC
value, and judges every boss by one readiness rule. A stuck run now climbs one reload ladder in
all six games, and the live page streams its screen.

- **Accounts.** With `AUTH=accounts` everyone logs in with a password, an OpenID Connect
  provider or a trusted proxy header. Admins invite people with one-time links, and owners share
  an adventure or make an expiring watch link. A Library with `AUTH` unset stays open. See
  [Users and sharing](users-and-sharing.md) and [Authentication](authentication.md).
- **Trade offers.** An owner switches on Open to offers, and people the adventure is shared
  with send offers from Make a trade. Only the owner accepts or declines, and unanswered offers
  expire after 24 hours. See [Trade offers](trading.md#trade-offers).
- **PC values.** Every stored Pokémon has a value, shown in its PC popup, and the PC releases
  the cheapest first. Catches, gifts, returns and trade arrivals are kept only when the PC would
  keep them, and trades are rated by the same rules.
- **Boss readiness.** One rule judges every boss in all six games. A team trains until its best
  fighter reaches the level a loss set, then until it matches up with the boss's ace. A party
  that is not ready heals before a boss battle and before a League rematch.
- **Reload ladder.** A stuck run reloads an earlier save, reports "Stuck?" at the third reload
  in a row and gives up on the stuck goal at the twelfth. Only a new best counts as progress,
  and the bot's waits hold through a reload.
- **Live stream.** The live page takes frames over one `/stream` request at the game's 15 fps,
  which cut the serving CPU per viewer from about 6.1% to 1.7% of a core.

See the [changelog](../CHANGELOG.md#070) for every change.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.7.0`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). pokecore moves to 0.12.0 and PyBoy RS to 0.1.5.

- The first start moves the Library database to schema 2 and keeps a copy of the old one as
  `app.sqlite.pre-schema-2-<time>`. 0.6.x cannot open the upgraded database, so rolling back
  means restoring that copy or a backup from before the upgrade. See
  [Update and roll back](operations.md#update-and-roll-back).
- Gold, Silver and Crystal save their policy as version 2. Rolling back resets its memory, such
  as goals under way and collection plans, but not the game.
- `AUTOSAVE_SECONDS` now counts game seconds, with a default of 300.
- Each adventure keeps a trace under `states/trace/`, about 7 MB each and pruned with the
  autosaves. `TRACE=0` turns it off.
- To use accounts, set `AUTH=accounts` in `.env` as `.env.example` shows.

See the [0.6.2 release notes](release-0.6.2.md) for the 0.6.2 update, the
[0.5.0 release notes](release-0.5.0.md) for its known limitations, and
[release status](../RELEASE_STATUS.md) for remaining limits.
