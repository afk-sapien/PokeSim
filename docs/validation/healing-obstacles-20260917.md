# Healing routes with reset obstacles

Follow-up monitoring found another healing loop after the first healing correction. All three adventures had reached different positions in Victory Road with exhausted parties. They continued moving but stopped training and completing League runs.

A direct healing route must be usable with the current gates and boulders. Two assumptions violated that requirement:

- General journey planning assumes remote boulder puzzles can eventually be solved. That assumption cannot justify skipping the current puzzle to follow an immediately usable exit.
- Learned walking edges bypassed current object occupancy. A previously clear tile could now contain the dropped boulder, but the planner still preferred the remembered walk through it. The resulting movement also pushed the boulder in the wrong direction.

Healing now checks a separate route using actual switch flags on every floor. Changes to gates and live object positions invalidate that route. If it is not open, normal puzzle solving continues. Learned walking steps also respect current object occupancy for every navigation user.

Regression tests cover remote closed gates, changed switch flags invalidating a cached route, a boulder returning to a previously walked tile, and the tile becoming usable after that boulder moves away. The existing exit priority, real warp, scripted fall, and disconnected-map tests remain in place.

Private checkpoints from all three affected adventures and their replay results are retained in observations/healing-obstacles-20260917 in the smoke library. Deployment verification is recorded in healing-obstacles-upgrade.json.

## Verification

All 945 regression tests passed, with 40 optional tests skipped. Saved checkpoints from Sprout, Ripple, and Ember healed successfully after 24,806, 20,010, and 24,870 frames respectively. After a saved and backed-up deployment, all three live games reached Indigo Plateau and restored their parties and attack PP. Campaign identities, Pokédex progress, and catch counters remained intact.
