# Victory Road healing loop

Monitoring found Red Ember advancing frames without useful progress while seeking healing. Its damaged party repeatedly moved between Victory Road 2F and 3F. A retained checkpoint reproduced the loop for 90,016 frames without healing.

Two corrections address the observed navigation problems:

- Healing follows an available route to a Center before attempting another Victory Road boulder puzzle.
- Navigation discards saved walking steps between disconnected maps and refuses to learn new ones. The checkpoint contained an impossible step from Victory Road 2F to Lavender Town. Real doors, map connections, and the Mansion and Victory Road falls remain supported. Visit counts are retained.

Removing disconnected steps alone did not resolve the loop. The full fix, loaded from the original checkpoint without manual state edits, reaches the Indigo Plateau nurse and fully heals the party after 2,422 frames.

Tests cover the failing route, observation and restoration of disconnected steps, real exits, map connections, and scripted falls. Deployment verification and private evidence are retained in the smoke library under healing-route-upgrade.json and observations/healing-route-20260917.

All 942 regression tests passed, with 40 optional tests skipped. After a saved and backed-up deployment, live Red Ember restored HP for all six party members and replenished move PP, then entered another League run. All three campaigns resumed healthy with advancing frames, matching campaign identities, preserved Pokédex progress, and catch counters intact.
