"""Entry point for bundled application and supervised child processes."""
from multiprocessing import freeze_support

from pokesim.desktop import main

if __name__ == '__main__':
    freeze_support()
    main()
