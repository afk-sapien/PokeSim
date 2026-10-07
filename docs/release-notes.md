# PokeSim 0.4.20 experimental beta

This patch fixes a storage loop found after 0.4.19.

- Read PP as a standalone word when classifying menus. A PC box list containing a
  nickname such as DAMPPILOT was mistaken for the PP Up move picker, so the policy
  backed out of the list every cycle and the Release goal never freed storage.
  Adventures stuck on "Make room in storage" resume releasing Pokémon.

## Upgrading and validation

Back up the complete library. Set `POKESIM_IMAGE=ghcr.io/afk-sapien/pokesim:0.4.20`
and run `docker compose pull` followed by `docker compose up -d --wait`.
Keep the existing data mount and project name. Python users can follow the
[installation guide](desktop.md). Core remains pinned at 0.1.4.

Existing saves remain supported. Gameplay remains an experimental beta.
See [release status](../RELEASE_STATUS.md) for remaining limitations.
