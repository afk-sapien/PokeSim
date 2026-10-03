# PokeSim 0.4.17 experimental beta

Customize notifications, Pokémon names and artwork, manage backups, and enjoy
clearer live controls and collection pages. This release also fixes two gameplay
stalls during travel and League rematches.

- Optionally install the colored Red/Blue community sprite pack from Settings.
  Includes download progress, previews and a switch back to default portraits.
  Artwork downloads only after the user chooses it and is not bundled with PokeSim.
- Keep unfinished sprite downloads out of backups, preventing failures when a download finishes during backup creation.
- Refresh replaced sprites without requiring users to clear their browser cache.
- Add live per-adventure speed controls and clearer Pause, Resume, and Save now actions.

- Heal HP mismatches after PC withdrawal before leaving the Pokémon Center, preventing repeated rematch rewinds.
- Fix adventures waiting forever when a poison faint message interrupts a map crossing.

- Listen to live game audio at any simulation speed, including Max with the Sound button.
  Sound starts off and stops when you leave the tab.
- Choose trainer and rival names when creating an adventure. Both fields start
  with random suggestions and have individual reroll buttons.
- Start with a suggested adventure name, edit it, or generate another.
- Keep the PC collection full width in smaller desktop windows. Both collection
  and box grids adjust their column counts to the available space.
- Give Pokémon portraits brighter type-colored backgrounds with soft spotlights across the live
  team, PC, and Pokédex.
- Edit nickname prefixes, suffixes, complete names, and built-in exclusions in a compact Settings dialog.
- Load an adventure from a verified backup as a separate stopped copy without overwriting current progress.
- Present repeat visits and Mew walking requirements as progress cards in Adventure Stats, with separate ready, pending and League-win states.
- Delete saved backups with confirmation, browse five per page, and see total backup storage.
- Expand the built-in nickname pool from 1,616 to 6,117 unique names using
  100 prefixes and 70 suffixes. Existing Pokémon keep their names.
- Add named ntfy, Discord and Telegram integrations in Library → Notifications, including several of each. Discord uses a channel webhook.
  Telegram uses a bot token and chat ID.
- Keep the existing adventure and event filters, screenshots, journal links and
  separate test buttons for each integration. Settings apply to running adventures.
- Existing ntfy settings keep working. Disabling a destination preserves its
  saved credentials. Saved bot tokens and webhook URLs stay hidden.
- Discord messages suppress mentions. Provider errors and ordinary HTTP request
  logs do not expose the new provider credentials.
- Update the Docker build tool uv to 0.12.21.

Resolves sound support (#34) and additional notification providers (#33). Includes
the uv build-tool update from PR #32.

See the [notification setup guide](guide.md#notifications). Each integration chooses its own events and adventures. Multiple destinations can
receive the same event. Notifications are best effort, and the journal remains the
record of events when a provider is unavailable or rate limited.

## Upgrading

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.17`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Desktop users can follow the
[installation guide](desktop.md). Adventure progress and speeds are unchanged.

Core remains at 0.1.4. These integrations belong to the application, not the
shared game mechanics package. Gameplay remains an experimental beta.
