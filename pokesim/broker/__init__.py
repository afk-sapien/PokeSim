"""Read-only trade broker: watches two pokesim instances and publishes the swaps they could agree.

The broker never writes. It polls each instance's `/api/pokedex/status`, works out which spare
Pokémon each run could part with, and pairs them into proposals. Executing a trade is a later
milestone with its own backend; nothing here touches a save file or a running emulator.
"""
