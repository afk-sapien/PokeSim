"""Wait for a windowed or console desktop bundle's runtime diagnostic."""
import subprocess
import sys

if __name__ == '__main__':
    subprocess.run([*sys.argv[1:], '--check-runtime'], check=True, timeout=180)
