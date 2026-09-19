"""Application entry point with explicit private and legacy launch modes."""
from __future__ import annotations

import logging
import sys
import threading

import uvicorn


from . import config
from .notify import Ntfy
from .runtime import Runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pokesim")


def legacy_main():
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


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {'--worker', 'worker'}:
        from .runtime.worker import main as worker_main
        return worker_main()
    if args and args[0] == '--link-session':
        from .interactions.link_worker import main as link_main
        return link_main(args[1:])
    admin_index = 0
    while admin_index < len(args):
        if args[admin_index] == '--data-dir':
            admin_index += 2
        elif args[admin_index].startswith('--data-dir='):
            admin_index += 1
        else:
            break
    if admin_index < len(args) and args[admin_index] in {'adventures', 'import', 'import-pair', 'backup', 'restore'}:
        from .app.cli import main as cli_main
        return cli_main(args)
    if args and args[0] == 'legacy':
        if len(args) != 1:
            raise SystemExit('Legacy launch uses environment configuration and accepts no arguments')
        return legacy_main()
    if args and args[0] == '--check-runtime':
        from .desktop import legacy_main as desktop_check
        return desktop_check(args)
    if args and args[0] == 'app':
        args.pop(0)
    if args and args[0] == 'desktop':
        args[0] = '--desktop'
    if args and args[0] == 'serve':
        args.pop(0)
    from .app.manager import main as manager_main
    return manager_main(args)


if __name__ == '__main__':
    main()
