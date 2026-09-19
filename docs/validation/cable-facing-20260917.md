# Cable Club input readiness

The recurring monitor found four consecutive aborted trades. Three failed during travel and one failed while connecting. The connection failure was reproduced from the retained inputs for interaction `7677b5ef475b49129cc766049827d323` on disposable emulator copies.

The original driver sent one four-frame Up input and assumed both players faced the attendant. Blue remained facing left while Red entered the connection handshake. Sending another Up input allowed both sides to connect. Entry now checks facing direction and the walking counter independently for both participants before starting the handshake.

The same replay exposed a restart validation failure. The fixed down-and-up movement probe could remain blocked at its origin. Verification now selects an adjacent walkable tile using live NPC positions, retries short inputs, and can try a different direction if it remains at the origin. It still requires actual movement to the exact neighboring tile and back, correct Center identity, and conserved party and Pokédex data. An unexpected tile or a game that never moves still fails validation.

The reproduced exchange now returns a verified manifest. Both sides completed the trade, preserved their boxes, received the negotiated individual, returned to their original Centers, and passed checkpoint and cartridge restart movement checks. Replay outputs are private local evidence at `/tmp/pokesim-cable-facing-adaptive` and were not adopted by the live games.

Regression suite: 859 passed, 40 skipped. Additional private cartridge checks and live deployment results are recorded in the application observation directory.

The three travel failures remain a separate investigation. They ended safely before cable execution. The monitor will continue comparing attempts and gameplay progress to isolate their cause.
