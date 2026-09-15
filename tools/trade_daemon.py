"""Run the bounded coordinator cycle in an operator-managed container."""
import subprocess
import sys
import time

while True:
    result = subprocess.run([sys.executable, '/coordinator/trade_pair.py', '--root', '/docker/pokesim-trading'])
    print(f'Trade opportunity check finished with status {result.returncode}', flush=True)
    time.sleep(60)
