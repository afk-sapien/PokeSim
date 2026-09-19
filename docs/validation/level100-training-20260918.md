# Prioritize level-100 completions

Live inspection found 6, 5, and 6 level-100 partners in Sprout, Ripple, and Ember, respectively, with roughly 240 total partners per adventure. The old policy excluded every training candidate whose evolution family had another owned copy. It also preferred lower levels, stopped at the next ten-level milestone, rotated away from productive targets, and assigned routine collection a higher category priority than training.

Postgame training now targets 100. The director favors partners within five levels of the highest unfinished eligible candidate, gives training a larger share of projects, and allows four consecutive training projects before an activity break. Recent productive training is not penalized solely for choosing the same target again. Ordinary repeat catches remain eligible at lower priority. Urgent supplies, missing entries, and peer demand remain supported.

Identifiable duplicates can train independently. The trainer and DV key follows the selected partner through evolution, storage, withdrawal, and party reordering. Ambiguous identities are excluded. Level-100 partners are excluded from training targets, offered partners are reserved, and requested stock remains protected. Full-party preparation prefers depositing a level-100 reserve while retaining a strong battler and essential field moves. A safe trainee with a damaging move is not switched out merely for a stronger matchup. Healing, danger-based switches, damage safety, and bounded training sessions remain intact.

Validation:

- 988 Python tests passed, 40 skipped. One existing Starlette deprecation warning remains.
- Added coverage for duplicate candidates, exact withdrawal, identity through evolution, ambiguous identities, category allocation, high-level finishing priority, completed reserve rotation, safe trainee battles, and emergency switches.
- Two private Blue save replays used the same cartridge snapshot and policy RNG, with both policies moved to a fresh planning boundary. Neither replay touched the live game.
- The candidate raised Vaporeon from 94 to 100, gaining 160,266 experience and increasing the copied game's level-100 population from 5 to 6 in 337,782 game frames and 200.65 wall seconds.
- The baseline used 517,526 game frames in 200.01 wall seconds. It raised Farfetch'd from 78 to 80 and Muk from 70 to 73, gaining 92,766 experience in total, with no new level-100 partner.
- These are equal wall-time observations, not equal frame-budget trials. The runs preserve 151 Pokédex entries and demonstrate policy behavior rather than a guaranteed ongoing completion rate.

Wheel SHA-256: `0d3944a2d3aeca3746769c82cadcc406ffcf947bac502fbc8707a8f32b750396`.

Deployment verification confirmed all original campaigns healthy with advancing frames, zero reloads, and 151 Pokédex entries. Live Blue selected its level-94 Vaporeon for a new level-100 training project. Existing projects can finish their saved milestone before selecting under the new policy. The hourly baseline now records each game's level-100 count.

Full backup: `/home/ty/.local/share/pokesim/backups/level100-training-20260918`.

Private evidence: `/home/ty/.local/share/pokesim/smoke-20260915/observations/level100-training-20260918`.
