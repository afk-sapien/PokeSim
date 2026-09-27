# Pokémon stats and Power

How individual stats, Power, DV ratings, training, and Elite Four wins are calculated.
For collection browsing and protecting partners, see [PC storage](pc-storage.md).

## Power

**Power** is PokeSim's estimate of overall strength at the current level. It serves
a similar purpose to [Pokémon GO's CP](https://niantic.helpshift.com/hc/en/6-pokemon-go/faq/125-what-are-combat-power-cp-and-hit-points-hp/),
but uses a custom formula for the original games. Values come from the Generation I
stat calculation using species, individual DVs, and stat experience, as when
withdrawing from the PC. HP means maximum HP, so damage, fainting, and temporary
battle effects do not change the score.

```text
Offense = 0.75 × max(Attack, Special) + 0.25 × min(Attack, Special)
Durability = 2 × Defense × Special / (Defense + Special)
Speed factor = 1 + Speed / 500
Power = floor(Offense × sqrt(HP × Durability) × Speed factor / 50)
```

Offense favors the stronger attacking stat while giving some credit for flexibility.
Special contributes to both offense and defense, reflecting its dual role in the
[original battle engine](https://github.com/pret/pokered/blob/master/engine/battle/core.asm).
Durability uses the harmonic mean of physical and special defense, assuming equal
exposure to each. This limits the benefit of one enormous defensive stat. HP and
durability have diminishing returns through the square root. Speed gives a modest
bonus. Dividing by 50 sets a readable display scale and does not affect ordering.
These weights are design choices for a general ranking, not a cartridge mechanic
or a measured win probability.

At level 100 with perfect DVs and full training, Mewtwo scores 4,877, Zapdos and
Moltres 3,592, Dragonite 3,553, Articuno 3,533, and Cloyster 2,674. Species receive
no bonuses for being legendary or a starter. Individual training and DVs can change
the order. Moves, type matchups, status strategies, and battle bonuses are excluded,
so a higher score does not guarantee a win. Missing individual data gives an
unavailable score and sorts last in either direction.

## Stat total

**Stat total** remains available as a separate sort. It adds max HP, Attack,
Defense, Speed, and Special with equal weight and appears in the stats table's
Total row. The API's `power` field now carries the weighted score, while
`stat_total` carries the former unweighted sum.

## DVs and star ratings

DVs are fixed individual values from 0 to 15. HP's DV is derived from the other four
DVs. The displayed total includes all five, for a maximum of 75. DV stars summarize
that total: 1 star for 0–37, 2 for 38–59, 3 for 60–74, and 4 for a perfect 75.
Level and training do not affect the star rating.

## Training

Stat experience grows through training, up to 65,535 in each of the five stats.
Reaching level 100 does not by itself mean every stat has maximum training.

## Elite Four wins

**Elite Four wins** credits a Pokémon for membership in the Hall of Fame party after
defeating the Elite Four and Champion. Verified historical victories are included,
and the count follows the individual through managed trades. Missing history is not
estimated. See [individual Elite Four wins](guide.md#individual-elite-four-wins) for
identity matching and unavailable counts.
