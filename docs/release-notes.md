# PokeSim 0.2.0 experimental beta

This release is about adventures that keep going, and about hearing from them.

**Phone notifications without an account.** The Library has a Notifications page. Choose an
[ntfy](https://ntfy.sh) server and topic, generate a random topic, add an access token only if your
server needs one, and send a test. Pick which adventures notify and which kinds of news are sent.
Changes reach running adventures at once, and the token is never shown again. The `NTFY_*`
variables still work as defaults until you save settings in the Library.

**Stalls are found, reported and fixed.** An adventure with no achievement for two hours of game
time and fifteen real minutes records a Stuck? journal entry with the saved moment, shows it on
Live and on its Library card, and sends it like any other news. A capture or earned experience
counts as progress, so a long hunt or a training session is not a stall.

Full-speed test adventures found these dead ends, and each now plays through:

- Short of the Safari Zone entry fee, the run sells a spare valuable instead of arguing at the gate.
- Automatic trading keeps the last partner that can learn Surf, and a Cut, Surf or Strength partner
  is found in any PC box, not only the open one.
- Exits on a map's edge, such as Victory Road's, are left by walking outward.
- The last partner standing fights on instead of trying to switch to itself.
- A frozen battler is cured, replaced, or a partner is revived. Freeze never thaws in these games.
- The Silph Co nurse is approached directly, and is not asked to heal once the building is freed.
- Two party members of one species are told apart when changing the lead.
- Route 23 checks badges, restocking is only planned at shops that can be reached, and a bag too
  full to buy Poke Balls spends its vitamins and Rare Candies.
- Full Heals are bought before the League. A battle that the original game cannot end, such as
  Lance's Dragonair using Agility forever against a frozen last partner, is left by reloading, and
  a League attempt that is already lost restarts from the moment it began.

`tools/find_stalls.py` plays a fresh cartridge or a copied checkpoint at full speed, about a minute
per game hour, and keeps a replayable bundle for every stall. Eleven fresh Red and Blue adventures
reached the Hall of Fame with it on this code.

Install the Python package with `pokesim-desktop`, or run one Docker container. Prepared
adventures work offline. Supply your own supported ROM. Packages exclude Pokemon ROMs, saves,
generated game datasets, and portrait packs.

After publication, install the container from `ghcr.io/afk-sapien/pokesim:0.2.0`
using the attached `compose.yaml` and `env.example`. Follow the
[container installation guide](https://github.com/afk-sapien/PokeSim/blob/v0.2.0/docs/self-hosting.md#install-a-published-container).
No GitHub login or local image build is needed. To upgrade, set `POKESIM_IMAGE` to the new
version, then `docker compose pull && docker compose up -d`. Adventures and settings are kept.

Downloads for this release are Python packages, a Linux amd64 Docker image archive,
Compose configuration, checksums, and a source manifest. Standalone executable
bundles are outside this release scope. Native package checks use PyBoy's demo
ROM and do not establish full cartridge gameplay reliability on every platform.

Back up existing adventures before upgrading. Publishing does not upgrade existing
installations. See [installation and migration](desktop.md) and [server setup](self-hosting.md).

The automatic player can still get stuck. This remains an experimental beta without
a new uninterrupted multi-day gameplay claim.
