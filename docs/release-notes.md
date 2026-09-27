# PokeSim 0.4.12 experimental beta

The automatic player can now take an occasional break for the Kanto Marathon.

## A race around Kanto

- Follow an eleven-checkpoint course from Pallet Town to Celadon and back,
  visiting seven towns through ordinary navigation and battles.
- Track elapsed game time, observed steps, battles, healing stops, and personal bests.
  Race progress survives save and restart cycles.
- Celebrate the start and finish with compact journal entries and screenshots.
  The current objective shows the next checkpoint and a short progress line.
- Keep missing Pokédex entries and urgent supplies ahead of recreation. Each attempt
  has a time limit, with at least six simulated hours before another can start.

Both Red and Blue completed the full course in local copied-save replays. See the
[marathon guide](marathon.md) for eligibility, measurement limits, and saved records.

## Upgrading

Back up the library and select `ghcr.io/afk-sapien/pokesim:0.4.12` in your Compose file,
then run `docker compose pull` and `docker compose up -d --wait`. Keep your existing
data mount and project name. Native installations can rerun the installer.

Existing adventures and checkpoints remain compatible. Marathon fields start empty
in older saves. There is no database migration. PokeSim Core remains at 0.1.2.
Docker images remain Linux amd64. Use the native Python installer on supported ARM64 systems.
