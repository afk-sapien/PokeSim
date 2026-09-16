# PokeSim 0.2.0rc31 candidate

This source candidate adds desktop setup, game-local trading and partner locks, a
separate one-time Champion Mew reward, and shared desktop/server lifecycle handling.

Server shutdown now reports final-save failures. An adventure directory lock prevents
two updated runtimes from opening the same game. Shopping and PC interactions have
separate state owners, and runtime status includes source build identity.

Validation includes synthetic Python scenarios, real Chromium flows, private ROM
opening tests, and copied-save comparisons. These checks do not establish uninterrupted
multi-day gameplay or native bundle qualification on every operating system.

This candidate has not been published or deployed. Supply your own supported ROM and
back up the complete data directory before upgrading. Review these notes and the
matching validation evidence against the exact tag before publishing.
