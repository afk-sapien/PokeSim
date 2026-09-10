import logging
import threading

import uvicorn

from . import config
from .notify import Ntfy
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pokesim")


def main():
    try:
        config.validate()
        from .game_data import load, FILES
        for name in FILES:
            load(name)
        store = Store(config.DATA_DIR)
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(f"Cannot start pokesim: {error}") from error
    emu = None
    monitor_done = threading.Event()
    try:
        from .emulator import Emulator
        from .web.app import create_app
        ntfy = (Ntfy(config.NTFY_URL, config.NTFY_TOKEN, config.NTFY_MIN_PRIORITY, config.NTFY_MUTE)
                if config.NTFY_URL else None)
        emu = Emulator(store, ntfy)
        emu.start()
        app = create_app(emu, store)
        server = uvicorn.Server(uvicorn.Config(
            app, host=config.HOST, port=config.PORT, log_level="warning",
            timeout_graceful_shutdown=5))

        def monitor():
            while not monitor_done.wait(1):
                if not emu.thread.is_alive():
                    if not emu.stopping and not emu.fatal_error:
                        emu.fatal_error = "Emulator worker stopped unexpectedly. See server logs."
                    server.should_exit = True
                    return

        threading.Thread(target=monitor, name="emulator-monitor", daemon=True).start()
        server.run()
        if emu.fatal_error:
            raise SystemExit(1)
    finally:
        monitor_done.set()
        if emu is not None:
            log.info("shutting down, saving state")
            if emu.thread.is_alive():
                emu.stop()
            else:
                emu.pb.stop(save=False)
        store.close()


if __name__ == "__main__":
    main()
