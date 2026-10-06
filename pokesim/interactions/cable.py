"""Bounded virtual cable transport for two isolated, verified cartridge instances."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from .cable_metadata import BUILDS
from ..audio import enable_checkpoint_sound


from pokesim_core.gen1_cable import CableEndpoint, CableError as CableError, checked


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class CableSide(CableEndpoint):
    """Own an emulator, independent cartridge RAM, and one bounded cable endpoint."""

    def __init__(self, spec, max_queue=4, *, builds=None):
        from pokesim_core.emulator import Emulator as CoreEmulator
        self.spec = spec
        self.rom_bytes = Path(spec.rom_path).read_bytes()
        self.rom_sha1 = hashlib.sha1(self.rom_bytes).hexdigest()
        builds = BUILDS if builds is None else builds
        checked(self.rom_sha1 in builds, 'Unsupported ROM for cable adapter')
        self.build = builds[self.rom_sha1]
        self.sym = self.build['symbols']
        for name, expected in self.build['signatures'].items():
            bank, address = self.sym[name]
            offset = bank * 0x4000 + address % 0x4000
            checked(self.rom_bytes[offset:offset + 8].hex() == expected,
                    f'Unsupported instruction signature: {name}')
        state = Path(spec.checkpoint_path).read_bytes()
        save = Path(spec.cartridge_save_path).read_bytes() if spec.cartridge_save_path else b''
        self.input_hashes = {'checkpoint_sha256': sha256(state),
                             'cartridge_sha256': sha256(save) if save else None,
                             'rom_sha256': sha256(self.rom_bytes)}
        for field in ('checkpoint_sha256', 'cartridge_sha256'):
            expected = getattr(spec, field, None)
            checked(expected is None or expected == self.input_hashes[field],
                    f'Source digest mismatch: {field}')
        self.ram_stream = io.BytesIO(save or bytes(32768))
        self.pb = CoreEmulator(io.BytesIO(self.rom_bytes), ram_file=self.ram_stream,
                        window='null', sound_emulated=True, log_level='ERROR')
        try:
            self.pb.set_emulation_speed(0)
            self.pb.load_state(io.BytesIO(enable_checkpoint_sound(state)))
        except BaseException:
            self.pb.stop(save=False)
            raise
        super().__init__(self.pb, self.sym, max_queue)
