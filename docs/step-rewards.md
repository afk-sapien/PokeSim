# Walking rewards and return visits

Walking unlocks another activity. The AI still visits the original location,
collects the gift, revives the fossil, or supplies a Pokémon for an NPC trade.
Existing Pokémon are never removed by an event reset.

| Activity | Default requirement | What happens |
| --- | --- | --- |
| Eevee | 100,000 steps | Another gift in Celadon Mansion |
| Fossil | 100,000 steps | Collect Helix or Dome in Mt. Moon, or Old Amber in Pewter, then visit Cinnabar's lab |
| Fighting Dojo | 100,000 steps | Defeat the Karate Master again and choose Hitmonlee or Hitmonchan |
| NPC exchange | 100,000 steps per completed exchange | Repeat the trade, supplying an eligible partner |
| Legendary return | 1,000,000 steps | Revisit previously acquired Articuno, Zapdos, Moltres, or Mewtwo |
| First Mew | Become Champion | A custom level-5 gift joins the PC |
| Later Mew | 1,000,000 steps, then a new League victory | Another custom level-5 Mew joins the PC |
| League reward | Each new League victory | A random level-5 Bulbasaur, Charmander, or Squirtle |

The repeat native activities begin after becoming Champion and completing their
original event. Fossil expeditions unlock after acquiring a fossil Pokémon.
The supported repeating NPC exchanges are Mr. Mime, Farfetch'd, Lickitung, and
Jynx. These use the original cartridge trades, including the requested species
and native individual stats. They do not generate randomized trade DVs.

Each gift, fossil, dojo, and exchange activity holds one opportunity. Unclaimed
opportunities do not accumulate. Claiming one starts its next walking requirement.
The fossil opportunity is claimed when the fossil item is collected. The AI then
brings it to the lab. A fossil already in the bag or lab delays another expedition.
Legendary returns retain their existing periodic milestones and one unclaimed
opportunity per legendary.

Mew's walking requirement starts after the initial gift or, for existing owners,
when this feature first observes their Champion progress. Reaching the requirement
unlocks an opportunity that needs a later League victory. Older wins cannot redeem
it. Full storage delays delivery without losing the opportunity. Delivery starts
the next walking requirement, and saved reward receipts prevent duplicate gifts.
Previously owned Mew still prevents another *initial* gift.

## Settings

Stop an adventure and open its Library settings to change the intervals. Zero
disables that kind of return. Fossil and dojo preferences offer **Auto** or a
specific choice. Auto prioritizes missing families and then weaker known DVs.
Choices are fixed when an opportunity opens, so changing a preference affects
future opportunities. The AI continues without waiting for user input.

Journal Stats shows walking requirements and ready activities. Detailed rules
stay in this document rather than in settings help text.

## Existing adventures

Existing games start fresh counters when this feature first observes their
eligible events. Past steps do not generate a reward backlog. Existing partners,
League win counts, pending reward counts, and legendary return claims remain.
Future League reward selections contain starters only. Native return claims are
stored separately from checkpoints and reconcile their event flags after restores.
Changing an interval starts a fresh walking requirement for waiting activities.
Already available native visits remain reserved. Disabling Mew resets its walking
requirement and any unredeemed League opportunity.
