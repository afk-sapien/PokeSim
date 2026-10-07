# Pokémon stats and Power

How individual stats, Power, DV ratings, training, and Elite Four wins are calculated.
For collection browsing and protecting partners, see [PC storage](pc-storage.md).

## Stat Power

**Stat Power** is PokeSim's estimate of overall strength at the current level. It serves
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

## Battle Power

**Battle Power** rates the four known moves at the current level and is the default
sort in the PC's All Pokémon view. Stat Power and Potential Stat Power remain
available separately. Existing `power` API fields and historical collection
statistics retain their original stat-only meaning. The new API field is
`battle_power`.

For each of the 15 Generation I types, the estimate chooses the best damaging move
against a single-type reference opponent at the same level L, with 3L + 10 HP and
2L + 5 Defense and Special. It averages expected damage as a percentage of reference
HP, accounting for the attacking stat, STAB, type effectiveness, accuracy, critical
hits, multi-hit moves, charging, recharge, recoil, and a steep self-destruction penalty.
Recovery and distinct useful status effects add at most 20 percent to that offense
estimate. Redundant moves do not add damage merely by filling another slot.

```text
Battle Power = floor(moveset score × sqrt(HP × Durability) × Speed factor / 10)
```

The estimates reuse the battle policy's damage model. They are a general benchmark,
not a battle simulator or a win probability. References have no dual typing, and
opponent frequency, PP endurance, setup sequences, Transform, Counter, Bide, and
one-hit knockout strategies are not modeled. Utility-only movesets score zero.
Missing or unknown move data is unavailable. Damage, current PP, and temporary
status do not change the score. The scale is separate from Stat Power.

A Starmie with only Tackle therefore rates much lower than the same individual
with Surf, even though their Stat Power is identical. Duplicate release and trading
continue to protect natural potential and trained veterans using the existing rules.

## Move development

The strategic policy uses the moveset estimate when deciding which move to replace
on learning. Field HMs remain protected. Before using an evolution stone it checks
for valuable future level-up moves that the evolved species would miss, then trains
toward the next such move. For example, Staryu can wait for Water Gun or Recover.
Already missed moves are not retroactively restored.

Outside the League and urgent healing, the policy can teach owned HM03 (Surf) or
HM04 (Strength) into an empty party move slot when the estimated improvement is
substantial. Another party member already knowing the HM does not block this.
The policy uses normal cartridge menus, preserves existing moves, and spaces retries.
Navigation teaching of Cut, Surf, and Strength continues as before.

After becoming Champion, managed adventures on supported Red and Blue cartridges
can buy replacements for the 38 limited TMs at the Celadon Department Store 2F
counter. The AI considers healthy compatible party members at level 50 or above. A move
must improve the current moveset score by more than 8 percent and one score
point. It then projects that exact replacement to level 100 with maximum stat
experience, keeping the individual's real DVs and current species. The projected
Battle Power gain must also exceed 8 percent and one point.

The planner greedily chooses the largest absolute projected Battle Power gain
across eligible TM and party pairs, then reassesses after every successful use.
Current moveset gain and lower price break ties. It does not multiply by current
level or prefer the highest final score over the biggest improvement. This lets
a level-50 partner receive a more valuable upgrade ahead of a level-100 partner.
The projection does not assume future evolutions, moves, or changes to DVs, and
boxed partners are not automatically withdrawn for TM teaching. It teaches useful limited TMs
already in the bag first, keeps field HMs, and avoids buying a move that the
recipient can still learn by leveling. Existing occupied move slots can be
replaced when that improves the moveset.

The custom counter charges ₽50,000 for Toxic, Body Slam, Ice Beam, Blizzard,
Thunderbolt, Earthquake, Dig, Psychic, and Fire Blast. Swords Dance, Seismic Toss,
Mega Drain, SolarBeam, Thunder, Softboiled, Rest, Thunder Wave, and Rock Slide cost
₽25,000. The other limited TMs cost ₽10,000. Purchases leave at least ₽20,000 for
supplies and require a free bag slot. Only one copy is bought for a chosen
recipient. The twelve renewable cartridge TMs retain their existing availability
and are outside this shopping planner.

Shopping trips begin between collection projects and yield to healing, supply
restocking, storage needs, and League battles. A trip has a bounded travel budget.
At the counter, PokeSim stages the money deduction and TM in a cloned checkpoint,
then commits the checkpoint, journal entry, and Purchased counter together. A
restart recovers an unfinished committed purchase. Earlier checkpoints cannot
rewind across that purchase. Teaching uses the cartridge menus and consumes the
TM normally, incrementing Used only on success. There is no replacement cartridge
shop screen or ROM patch. The journal identifies the custom Champion counter.

Limited TMs are normally protected from automatic selling. If all 20 bag slots
are occupied and no ordinary surplus can be sold, the player sells the limited
TM stack with the lowest Champion replacement cost to free one slot for story
items. Key items, HMs, balls, and medicine are excluded from this fallback.
Champion purchases leave at least one bag slot free. Optional HM teaching still
uses empty slots only. Reusable HMs are never consumed.

The same custom Champion counter also replenishes Moon Stones (₽5,000), PP Ups
(₽25,000), Elixirs (₽5,000), and Max Elixirs (₽10,000). The planner keeps at most
one of each in the bag. Moon Stones require a held evolution candidate. PP Ups
require a healthy level 60+ partner with a strong damaging move that can still
gain PP. Explosion and one-hit knockout moves are excluded. Item use happens
through the normal cartridge menus. Elixirs remain emergency League supplies,
and the collection planner handles Moon Stone evolutions.

After becoming Champion, another 1,000,000 tracked walking steps unlock one
Master Ball purchase for ₽100,000 and one bundle of five Rare Candies for
₽25,000. Each offer has its own countdown, holds only one unclaimed purchase,
and starts its next million steps when purchased. Waiting longer does not bank
extra purchases. Existing Champion adventures start these countdowns when first
running this update. Stats → Items shows the remaining steps and ready offers.
The automatic player waits for enough money, bag space, and an eligible party,
and does not buy another copy while that item remains in the bag. Rare Candies
are used on unfinished level 30+ partners. Master Balls retain the existing
legendary and shiny capture rules.

These purchases keep the same ₽20,000 reserve and checkpoint recovery protection
as TMs. Offer redemption and Purchased counts commit with the item and payment.
A five-candy bundle counts as five purchased items. Native successful consumption
increments Used separately. Returning to an older checkpoint cannot reclaim an
offer or undo its payment.

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
and the count follows the individual through managed trades. A **+** marks a verified minimum when history is incomplete. Missing history is not
estimated. See [individual Elite Four wins](guide.md#individual-elite-four-wins) for
identity matching and unavailable counts.
