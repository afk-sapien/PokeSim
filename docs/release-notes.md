PokeSim 0.2.0rc14 adds PC sorting across selected or all boxes by level, total DVs, total stat experience, total experience, Pokédex number, species, nickname, and box order. Choose either direction. Sorting applies before pagination and stays selected through refreshes and shared URLs. Cards show both stat totals, with the five-stat breakdown and limits in the detail view.

This release also records productive reserve training as partial progress when an idle guard abandons the attempt. The existing deadlines and retry delays remain in place. The copied-save comparison matches the previous gameplay behavior. See [the validation record](validation/partial-training-20260915.json).

Both live games are deployed at unlimited speed with verified save compatibility and cold backups. All 388 Python tests, three PC sorting tests, the screen suite, and all 12 public checks passed. See [release status](../RELEASE_STATUS.md).
