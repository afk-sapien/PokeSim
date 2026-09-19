"""A single owner for emulator, database, and lifetime of an adventure."""
from __future__ import annotations

from pathlib import Path
import threading

from ..platform_io import lock_file


class AdventureLock:
    def __init__(self, data_dir):
        self.path = Path(data_dir).resolve() / 'runtime.lock'
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            lock_file(stream)
        except BaseException:
            stream.close()
            raise
        self.stream = stream
        return self

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()


class SimulationRuntime:
    """Keep the lock until the emulator has exited and storage is closed."""
    def __init__(self, settings, *, managed=True):
        self.settings = settings
        self.managed = managed
        self.store = None
        self.emulator = None
        self.lock = AdventureLock(settings.data_dir)
        self._guard = threading.Lock()

    def start(self):
        with self._guard:
            if self.emulator is not None:
                raise RuntimeError('This simulation runtime has already started')
            self.lock.acquire()
            try:
                self.settings.install(managed=self.managed)
                from ..game_data import FILES, load
                for name in FILES:
                    load(name)
                from ..store import Store
                from ..emulator import Emulator
                from ..notify import LiveNtfy, Ntfy
                self.store = Store(Path(self.settings.data_dir))
                if self.managed:
                    from .participant import recover_storage
                    recover_storage(self.store)
                    from .reward_delivery import recover_storage as recover_rewards
                    recover_rewards(self.store)
                sender = (self.settings.ntfy_url, self.settings.ntfy_token,
                          self.settings.ntfy_min_priority, set(self.settings.ntfy_mute))
                # A managed adventure receives its destination and filters from the Library while it runs.
                ntfy = LiveNtfy(*sender) if self.managed else Ntfy(*sender) if self.settings.ntfy_url else None
                self.emulator = Emulator(self.store, ntfy, isolated_ram=self.managed)
                self.emulator.start()
            except BaseException:
                self._close()
                raise
        return self

    def call(self, function, timeout=30):
        return self.emulator.call(function, timeout=timeout)

    def create_app(self):
        from ..web.app import create_app
        return create_app(self.emulator, self.store)

    def _close(self):
        emu = self.emulator
        if emu is not None:
            if emu.thread.is_alive():
                # On timeout keep the database and ownership lock open.
                emu.stop()
            elif emu.thread.ident is None:
                emu.pb.stop(save=False)
        if self.store is not None:
            self.store.close()
            self.store = None
        self.lock.close()

    def close(self):
        with self._guard:
            self._close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
