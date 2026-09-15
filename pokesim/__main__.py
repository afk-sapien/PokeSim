"""Application entry point with explicit private and legacy launch modes."""
from __future__ import annotations

import logging
import sys
import threading


def legacy_main():
    """Run one standalone adventure through the same owned runtime."""
    import uvicorn
    from . import config
    from .runtime import SimulationRuntime, SimulationSettings
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    config.validate()
    settings = SimulationSettings.from_environment()
    done = threading.Event()
    with SimulationRuntime(settings, managed=False) as runtime:
        server = uvicorn.Server(uvicorn.Config(
            runtime.create_app(), host=config.HOST, port=config.PORT, log_level='warning',
            timeout_graceful_shutdown=5))

        def monitor():
            while not done.wait(0.25):
                if not runtime.emulator.thread.is_alive():
                    if not runtime.emulator.stopping and not runtime.emulator.fatal_error:
                        runtime.emulator.fatal_error = 'Emulator worker stopped unexpectedly. See server logs.'
                    server.should_exit = True
                    return

        threading.Thread(target=monitor, name='emulator-monitor', daemon=True).start()
        try:
            server.run()
        finally:
            done.set()
        if runtime.emulator.fatal_error:
            raise SystemExit(1)


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
