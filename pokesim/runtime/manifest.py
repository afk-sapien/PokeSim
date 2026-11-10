"""The manifest every checkpoint writer puts beside a save state.

The application's autosaves, the named saves before a rewind or restart, the headless runs'
saves and each trace segment's header all carry it, so a replay reads the same fields from any
of them. ``write_checkpoint`` adds the format and the checksum of the bytes on disk.
"""
from __future__ import annotations

from pokecore.emulator_state import checkpoint_metadata

from .. import __version__, config


def checkpoint_manifest(pb, policy, *, rom_sha1, frame, generation=1, policy_name=None, run_memory=None,
                        play_clock=None, store=None, legendary_recovery=None, history=None):
    """The manifest for the game ``pb`` holds now.

    Gen II saves with the clock locked to game time, so the lock goes into the manifest and Core
    leaves off the legacy PyBoy tag. The optional parts are left out when a writer has none.
    """
    manifest = {'app_version': __version__}
    if generation == 2:
        # Imported here, so a Red, Blue or Yellow process never loads the Gen II package.
        from pokecore.gen2.clock import clock_elapsed, clock_lock_state
        lock = clock_lock_state(pb)
        manifest.update(checkpoint_metadata(rtc_clock=lock), rtc_clock=lock, generation=2)
    else:
        manifest.update(checkpoint_metadata())
    manifest.update(rom_sha1=rom_sha1, frame=frame, policy=policy_name or config.POLICY,
                    policy_state=policy.state_dict(),
                    run_memory=run_memory.to_dict() if run_memory is not None else {})
    if play_clock is not None:
        manifest['play_clock'] = play_clock.state_dict()
    if store is not None:
        manifest['trade_id'] = store.get('trade_barrier')
        manifest['reward_id'] = store.get('custom-reward-barrier-v1')
    if legendary_recovery is not None:
        manifest['legendary_recovery'] = legendary_recovery.state_dict()
    if generation == 2:
        manifest.update(gen2_history=history, rtc_elapsed=clock_elapsed(pb),
                        settled=policy.menu is None and not getattr(policy, 'backing_out', False))
    return manifest
