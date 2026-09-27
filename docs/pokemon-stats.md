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

## DV rarity and potential Power

**DV quality (est.)** is the percentage of uniformly weighted DV combinations
with a total at least as high as this partner's. Lower is rarer. **Higher roll**
is the percentage with a strictly higher total. The existing percentage of
maximum DV points is not a percentile.

PokeSim Core enumerates all 65,536 combinations of Attack, Defense, Speed, and
Special, each from 0 to 15, deriving HP from their low bits. HP is never treated
as an independent fifth roll. A 65/75 total has an inclusive tail of about
0.417% and a strictly better tail of about 0.270%. Perfect DVs have an inclusive
tail of 1/65,536 and no strictly better outcome. Invalid or inconsistent DVs
receive no rarity estimate.

This is a uniform reference model. Cartridge RNG timing and acquisition methods
can affect observed odds. These values do not include the chance of encountering
a species, catching it, or finding an exact individual. They are not predictions
of how long a hunt will take.

**Potential Power** applies the Power formula at level 100 and maximum stat
experience, holding this individual's species and DVs fixed. It does not predict
an evolution or include moves and matchups. Compare potential within a species
when considering a replacement. Current Power still measures present strength.

## Training

Stat experience grows through training, up to 65,535 in each of the five stats.
Reaching level 100 does not by itself mean every stat has maximum training.

Optional postgame training now considers rarity and investment:

- Top-0.5% candidates have the highest non-perfect training priority, followed
  by top-5% candidates, then ordinary candidates. Perfect partners retain priority.
- For lower-level candidates outside the top 5%, a reachable repeatable hunt can
  take up to three expeditions before training proceeds. Failed or abandoned
  hunts count, and the budget persists in checkpoints. There is no hunt delay
  without a currently available hunt or for a partner already at level 80.
- A duplicate of an existing level-100 partner needs at least 2% more potential
  Power to justify training again. Perfect finds are the collection exception.
- Within a quality tier, remaining experience to level 100, replacement gain,
  and travel distance affect selection. These weights estimate effort, not hours.
  Ten-level training steps and activity rotation remain in place.
- Missing Pokédex entries and urgent supplies keep their existing precedence.

Automatic release keeps both the best potential and the strongest current copy
of each species. A veteran becomes expendable only after another copy catches
up in current Power. Every top-0.5% find remains protected from automatic release.
Automatic peer and NPC trading also protect these rare finds, the strongest
known partner at level 80 or above, and a meaningful replacement for that partner.
An explicit peer offer can override investment protection, while existing locks
and perfect-Pokémon protections still apply. Unknown data never earns a rarity
classification, and legacy inventories retain their conservative fallback.

These cutoffs are PokeSim policy choices, not mechanics of the original game.
All detailed explanations remain in this guide. Pokémon details show only the
compact rarity estimate and potential Power alongside their existing stats.

## Elite Four wins

**Elite Four wins** credits a Pokémon for membership in the Hall of Fame party after
defeating the Elite Four and Champion. Verified historical victories are included,
and the count follows the individual through managed trades. Missing history is not
estimated. See [individual Elite Four wins](guide.md#individual-elite-four-wins) for
identity matching and unavailable counts.
