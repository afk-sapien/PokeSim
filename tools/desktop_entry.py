"""Entry point for bundled desktop applications."""
from multiprocessing import freeze_support

from pokesim.desktop import main

if __name__ == '__main__':
    freeze_support()
    main()
