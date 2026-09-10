PokeSim 0.2.0rc5 is an experimental self-hosting beta for Linux amd64.

Fix a storage loop that repeatedly switched between boxes while trying to withdraw an evolution partner. A full source box now permits withdrawal when the party has a free slot. The policy also leaves the box selector when the intended box is already active. Full-party deposit capacity checks remain in place.

A copied checkpoint reproduced 41 box switches without a withdrawal under the previous policy. With the fix and the same seeded evolution objective, the partner was withdrawn in 468 frames with no box switches. All 204 Python tests pass, including four new regressions covering the corrected behavior and capacity safeguards. Save formats are unchanged.

This release includes the rc4 display fix. The browser downloads and decodes one image at a time, retains the last good frame on errors, and retries automatically.

Supply your own supported Pokémon Red ROM and prepare game data locally using the README. Pokémon ROMs, sprites, and generated game datasets are excluded. PyBoy includes its own small demo ROM, which is not a Pokémon game. Public downloads require no GitHub account or registry login.

This is still an early beta. The existing rc3 endurance run continues, but does not validate this policy change or the rc4 polling viewer. No completed 48-hour pass is claimed for rc5. The policy can still get stuck or make poor choices. ARM, Blue, and ROM hacks are not validated release targets.

See [installation instructions](https://github.com/afk-sapien/PokeSim/blob/main/README.md) and [current validation results](https://github.com/afk-sapien/PokeSim/blob/main/RELEASE_STATUS.md). Use GitHub issues for feedback and private vulnerability reporting for security problems.
