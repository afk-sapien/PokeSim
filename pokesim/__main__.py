import logging
import threading

import uvicorn

from . import config
from .notify import Ntfy
from .runtime import Runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pokesim")


def main():
    try:
        config.validate()
        from .game_data import load, FILES
        for name in FILES:
            load(name)
    except (ValueError, OSError, RuntimeError) as error:
        raise SystemExit(f"Cannot start pokesim: {error}") from error
    from .web.app import create_app
    ntfy = (Ntfy(config.NTFY_URL, config.NTFY_TOKEN, config.NTFY_MIN_PRIORITY, config.NTFY_MUTE)
            if config.NTFY_URL else None)
    try:
        with Runtime(config.DATA_DIR, ntfy) as runtime:
            emu = runtime.emu
            app = create_app(emu, runtime.store)
            server = uvicorn.Server(uvicorn.Config(
                app, host=config.HOST, port=config.PORT, log_level="warning",
                timeout_graceful_shutdown=5))
            monitor_done = threading.Event()

            def monitor():
                while not monitor_done.wait(1):
                    if not emu.thread.is_alive():
                        if not emu.stopping and not emu.fatal_error:
                            emu.fatal_error = "Emulator worker stopped unexpectedly. See server logs."
                        server.should_exit = True
                        return

            watcher = threading.Thread(target=monitor, name="emulator-monitor", daemon=True)
            watcher.start()
            try:
                server.run()
            finally:
                monitor_done.set()
                watcher.join()
                log.info("shutting down, saving state")
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"PokeSim stopped: {error}") from error


if __name__ == "__main__":
    main()
