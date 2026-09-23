# PokeSim 0.3.2 experimental beta

Another repair release, from a review of the parts of 0.3.1 that had never been read: the trade
coordinator, the broker, and the per-adventure runtime. Everything here is about an application
that has been running for weeks rather than minutes — what it accumulates, and what it does when
something will not finish.

## The backup you are told to take before upgrading could not finish

`create_backup` copies `assets`, `adventures` and `interactions` into a staging directory, then
checksums and zips it. That directory came from `TemporaryDirectory()` with no location, so it
landed in `/tmp` — which the shipped Compose file mounts as a **256 MB tmpfs** on a read-only
root. Any library past about a quarter of a gigabyte filled RAM and failed, and a real library
passes that in a few hours of play. The live server this was found on is 1.6 GB.

The failure is worse than a failed backup. `create_backup` stops every running adventure before
it copies and restarts them in its `finally`, so the one operation an operator is told to perform
before upgrading was the one guaranteed to fail on the deployment that needed it. Both legacy
import paths had the same defect, one of them extracting up to two gigabytes. All three now stage
inside the application folder, which is what the restore path and three other callers already
did.

## Trading no longer accumulates forever

Every Cable Club attempt writes two save states, two cartridge saves and two screenshots under
`interactions/` — about half a megabyte — and nothing ever removed them. The live server had 377
of them, 174 MB. Because a backup copies that whole tree, backup number *k* embedded all *k*
exchanges' save states.

The newest twenty resolved exchanges are now kept. An unresolved one is never touched, whatever
its age, because recovery still needs its outputs. Nothing reads a resolved interaction: the
preview refuses a terminal phase and the manager only serves a frame for an exchange that has no
decision yet. Zero keeps everything, as it does for autosaves and stall bundles. The legacy
coordinator has kept the last twenty transactions all along; the application one never got it.

Separately, every notable event stores a full save state beside its screenshot — roughly 40 MB an
hour — and `prune_events` has always existed to trim it. But `event_retention_days` was missing
from the Library's settings whitelist, so a managed adventure could not set it and the pruning
call was dead code. The live server had 560 MB of event save states across two adventures. It is
settable per adventure now; the default is still to keep everything.

## A stuck exchange stops hammering the machine

An interrupted exchange that cannot be finished — a participant record lost to a restore, say —
was re-driven every 30 seconds indefinitely, and every pass restarts the worker through the
recovery path that deliberately ignores a stop request. That is the same bypass that made the
September incident unbreakable. The interval now doubles from 30 seconds to a ten-minute ceiling
and resets on success, and after the third failure the status says the trade is not finishing
instead of repeating that progress is saved.

Recovery still never gives up. A ceiling would mean abandoning an exchange already committed on
one side, which is the one path that can actually lose a Pokémon; that needs a design, not a
constant. The remaining risk is written down in the release status.

Related: `runtime.call` raises `TimeoutError` when the emulator thread has not reached a queued
operation in 45 seconds, and its message asks the caller to retry. `TimeoutError` is an
`OSError`, not a `RuntimeError`, so it escaped the handler and became a 500 with a full traceback
in the worker log. It answers with the retryable status and the explanation now. The live logs
show it firing during ordinary play, not only around shutdown.

## Verification

A mature save — eight badges, all 151 registered, 1,600 game hours — was replayed forward 900,014
frames on this build: **no rewinds, no errors, 18 achievements**, and the Pokédex unchanged at
151. The Pokédex masking added in 0.3.1 was also checked against **54 real checkpoints across 27
adventures**, with no case where it would hide an entry.

## Upgrading

Nothing to migrate. No database change, no policy state change, and existing checkpoints resume
untouched. Replace the image or the package where it is deployed.

Finished interaction directories are pruned the next time an exchange resolves, so a library with
a long trading history returns that disk space on its own. Existing journals keep every event
they have already recorded; setting `event_retention_days` only affects pruning from then on.
