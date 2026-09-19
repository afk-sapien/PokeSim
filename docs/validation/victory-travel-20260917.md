# Cable Club travel through Victory Road

Monitoring reproduced two aborted automatic trades on retained Blue Ripple checkpoints. The partner's Seafoam journeys succeeded.

The travel navigator correctly treated remote boulder gates as closed, but it required a fully open route to a Pokémon Center before beginning the journey. From Route 23 this failed immediately. From Victory Road 1F it solved the local puzzle, then failed because later floors still needed work.

Directed travel now uses an additional journey planner to identify the next map on a route that will require remote puzzles. The actual movement planner still verifies that the next map is reachable with the current gates closed. Current-floor puzzles and their necessary ladder or drop steps run before this fallback, preventing trips back and forth between floors. The original Center destination stays unchanged.

Regression coverage checks approaching a remote puzzle from Route 23 and 1F, requiring a Strength partner, preserving current closed gates, and solving the current floor before leaving. Existing coverage protects direct exits, temporary obstacles, and remote gate state.

Private replay checkpoints and before/after results are retained in the smoke library's observations/victory-travel-20260917 directory. These use ordinary game inputs and do not change the live campaigns.

Validation and deployment results are recorded in the library's victory-travel-upgrade.json file.

## Results

All 935 regression tests passed, with 40 optional tests skipped. Four disposable checkpoint journeys reached the intended PC square with no active battle, textbox, or walking animation. The previously failing Blue journeys took 59,152 and 65,098 emulated frames. The two Red partner journeys took 11,332 and 6,158 frames.
