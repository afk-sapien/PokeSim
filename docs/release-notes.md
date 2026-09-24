# PokeSim 0.3.8 experimental beta

Fewer black cards in the Journal, and a trading page that stays up.

## Journal pictures

Badges, warps and catches often happen while the screen is fading, so their Journal card used to
be a solid black or white square. Now an entry that lands on a blank screen waits, up to ten
seconds of game time, for the picture to come back, and uses that one. Its phone notification waits
with it, so the picture on your phone matches. A place that really is dark, like a cave without
Flash, keeps what it has after the wait.

Cards already stored blank stay as they are.

## Trading

Starting a trade asks both adventures what they can offer, and a busy adventure can take close to a
minute to answer. While it thought, the trading page went blank and starting an
adventure had to wait. Now nothing waits on that answer: the page keeps loading, and the trade is
double-checked before it is recorded, so an adventure stopped in the meantime is never traded.

Picking which trade to make next is about eleven times faster, which the manager does every ten
seconds while adventures run.

## Upgrading

Nothing to migrate: no database, save or policy change.
