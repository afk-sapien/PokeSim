"""Own one adventure's process lock, database, and emulator until shutdown finishes."""
import logging
from pathlib import Path

from .platform_io import lock_file

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, directory, ntfy=None):
        self.directory = Path(directory).resolve()
        self.ntfy = ntfy
        self.lock = None
        self.store = None
        self.emu = None

    def __enter__(self):
        from .emulator import Emulator
        from .store import Store

        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / 'adventure.lock').open('a+b')
        try:
            try:
                lock_file(self.lock)
            except BlockingIOError as error:
                raise RuntimeError(f'This adventure is already open: {self.directory}') from error
            self.store = Store(self.directory)
            self.emu = Emulator(self.store, self.ntfy)
            self.emu.start()
            return self
        except BaseException:
            try:
                self.close()
            except Exception:
                log.exception('Cleanup after startup failure also failed')
            raise

    def close(self):
        failure = None
        try:
            if self.emu is not None:
                emu = self.emu
                try:
                    if emu.thread.is_alive():
                        try:
                            emu.stop()
                        finally:
                            # The worker retains its database and lock until it exits.
                            # Desktop stop can time out while this owner keeps waiting.
                            if emu.thread.is_alive():
                                emu.thread.join()
                    elif emu.thread.ident is None:
                        emu.pb.stop(save=False)
                    if emu.fatal_error:
                        failure = RuntimeError(emu.fatal_error)
                except Exception as error:
                    failure = error
                finally:
                    self.emu = None
        finally:
            try:
                if self.store is not None:
                    self.store.close()
                    self.store = None
            finally:
                if self.lock is not None:
                    self.lock.close()
                    self.lock = None
        if failure is not None:
            raise failure

    def __exit__(self, kind, value, traceback):
        try:
            self.close()
        except Exception:
            if kind is None:
                raise
            log.exception('Shutdown failed while handling an earlier error')
