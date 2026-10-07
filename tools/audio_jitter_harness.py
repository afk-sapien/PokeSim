"""Measure live-audio gaps in a real browser through a delaying, jittery proxy.

The harness starts (or attaches to) a running PokeSim app, puts a small asyncio proxy in front
of it that delays /api/audio responses and the /stream video, opens the page in Chromium,
presses the Sound button and instruments every Web Audio buffer source the page schedules.
Nothing about the page's own code is assumed, so the same numbers can be taken before and
after an audio change by pointing --checkout at either tree.

Needs Playwright with Chromium (``uv run --extra browser-test``), a legally obtained Red or
Blue ROM, and a built game-data directory.

    uv run python tools/audio_jitter_harness.py --rom roms/pokered.gb --game-data data/game-data
    uv run python tools/audio_jitter_harness.py --url http://127.0.0.1:8930 --scenario jitter-1x
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

# name -> (base delay s, uniform jitter s, stall probability, stall s)
PROFILES = {
    'clean': (0.0, 0.0, 0.0, 0.0),
    'jitter': (0.030, 0.120, 0.03, 0.300),
    'harsh': (0.050, 0.200, 0.03, 0.800),
}

# name -> (profile, speed, manual)
SCENARIOS = {
    'clean-1x': ('clean', 1, False),
    'jitter-1x': ('jitter', 1, False),
    'harsh-1x': ('harsh', 1, False),
    'jitter-manual': ('jitter', 1, True),
    'clean-manual': ('clean', 1, True),
    'clean-0.5x': ('clean', 0.5, False),
    'clean-2x': ('clean', 2, False),
    'clean-4x': ('clean', 4, False),
    'clean-16x': ('clean', 16, False),
    'clean-unlimited': ('clean', 0, False),
}

INSTRUMENT = """
(() => {
  const log = {starts: [], stops: [], fetches: [], t0: performance.now()}
  window.__audioLog = log
  let ids = 0
  const proto = AudioBufferSourceNode.prototype
  const start = proto.start, stop = proto.stop
  proto.start = function (when = 0, ...rest) {
    this.__id = ++ids
    log.starts.push({id: this.__id, now: this.context.currentTime, when,
                     dur: this.buffer ? this.buffer.duration : 0, rate: this.playbackRate.value})
    return start.call(this, when, ...rest)
  }
  proto.stop = function (...args) {
    log.stops.push({id: this.__id, now: this.context.currentTime})
    return stop.apply(this, args)
  }
  const fetch = window.fetch
  window.fetch = async function (...args) {
    const response = await fetch.apply(this, args)
    try {
      const url = String(args[0] && args[0].url || args[0])
      if (url.includes('/api/audio')) {
        log.fetches.push({t: performance.now() - log.t0, seq: Number(response.headers.get('X-Audio-Sequence')),
                          state: response.headers.get('X-Audio-State'), speed: Number(response.headers.get('X-Audio-Speed'))})
      }
    } catch (_) {}
    return response
  }
})()
"""


class Link:
    """Per-direction delay model that never reorders a connection's data."""

    def __init__(self, profile, seed):
        self.base, self.jitter, self.stall_p, self.stall = PROFILES[profile]
        self.random = random.Random(seed)
        self.stalls = 0

    def delay(self):
        wait = self.base + self.random.random() * self.jitter
        if self.random.random() < self.stall_p:
            wait += self.stall
            self.stalls += 1
        return wait


class Proxy:
    def __init__(self, upstream, profile, seed=1):
        self.upstream = urlsplit(upstream)
        self.link = Link(profile, seed)
        self.loop = asyncio.new_event_loop()
        self.server = None
        self.port = 0
        self.ready = threading.Event()

    async def handle(self, reader, writer):
        up_writer = None
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            lines = head.decode('latin-1').split('\r\n')
            method, target, _ = lines[0].split(' ', 2)
            headers = [line for line in lines[1:] if line]
            length = 0
            kept = []
            for line in headers:
                name = line.split(':', 1)[0].lower()
                if name == 'content-length':
                    length = int(line.split(':', 1)[1])
                if name in ('connection', 'host', 'accept-encoding', 'keep-alive'):
                    continue
                kept.append(line)
            kept += [f'Host: {self.upstream.netloc}', 'Connection: close', 'Accept-Encoding: identity']
            body = await reader.readexactly(length) if length else b''
            up_reader, up_writer = await asyncio.open_connection(self.upstream.hostname, self.upstream.port)
            up_writer.write((f'{method} {target} HTTP/1.1\r\n' + '\r\n'.join(kept) + '\r\n\r\n').encode('latin-1') + body)
            await up_writer.drain()
            audio = target.startswith('/api/audio')
            video = target.startswith('/stream')
            first = True
            release = 0.0
            while True:
                chunk = await up_reader.read(65536)
                if not chunk:
                    break
                if (audio and first) or video:
                    # A later chunk may never overtake an earlier one on the same connection.
                    release = max(release, time.monotonic() + self.link.delay())
                    pause = release - time.monotonic()
                    if pause > 0:
                        await asyncio.sleep(pause)
                first = False
                writer.write(chunk)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.LimitOverrunError):
            pass
        finally:
            for stream in (writer, up_writer):
                if stream is not None:
                    stream.close()

    def start(self):
        def run():
            asyncio.set_event_loop(self.loop)

            async def boot():
                self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
                self.port = self.server.sockets[0].getsockname()[1]
                self.ready.set()
            self.loop.run_until_complete(boot())
            self.loop.run_forever()
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert self.ready.wait(10)
        return f'http://127.0.0.1:{self.port}'

    def stop(self):
        async def close():
            self.server.close()
            current = asyncio.current_task()
            for task in asyncio.all_tasks():
                if task is not current:
                    task.cancel()
            await asyncio.sleep(0.05)
            self.loop.stop()
        asyncio.run_coroutine_threadsafe(close(), self.loop)
        self.thread.join(5)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def launch(args):
    port = free_port()
    checkout = Path(args.checkout).resolve()
    data = tempfile.mkdtemp(prefix='pokesim-audio-harness-')
    url = f'http://127.0.0.1:{port}'
    env = dict(os.environ, ROM_PATH=str(Path(args.rom).resolve()), GAME_DATA_DIR=str(Path(args.game_data).resolve()),
               DATA_DIR=data, PORT=str(port), HOST='127.0.0.1', PUBLIC_URL=url, PYTHONPATH=str(checkout))
    process = subprocess.Popen([sys.executable, '-m', 'pokesim', 'legacy'], cwd=checkout, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url + '/healthz', timeout=1).read()
            return process, url
        except OSError:
            if process.poll() is not None:
                raise SystemExit('The app exited during startup')
            time.sleep(0.5)
    process.kill()
    raise SystemExit('The app did not start in 90 seconds')


def control(url, action, value=None):
    request = urllib.request.Request(
        url + '/api/control', json.dumps({'action': action, 'value': value}).encode(),
        {'content-type': 'application/json', 'origin': url})
    urllib.request.urlopen(request, timeout=5).read()


def analyse(log, seconds, speed):
    starts = log['starts']
    stops = {item['id']: item['now'] for item in log['stops']}
    sources = []
    for item in starts:
        begin = max(item['when'], item['now'])
        end = begin + item['dur'] / item['rate'] if item['rate'] else begin
        stopped = stops.get(item['id'])
        if stopped is not None:
            if stopped <= begin:
                continue
            end = min(end, stopped)
        sources.append({**item, 'begin': begin, 'end': end,
                        'late': item['when'] < item['now'] - 0.001})
    sources.sort(key=lambda item: item['begin'])
    gaps = []
    cursor = None
    for item in sources:
        if cursor is not None and item['begin'] > cursor + 0.002:
            gaps.append((cursor, item['begin'] - cursor))
        cursor = item['end'] if cursor is None else max(cursor, item['end'])
    # Ignore the first second so priming does not count as a fault.
    first = sources[0]['begin'] if sources else 0
    steady = [gap for at, gap in gaps if at > first + 1.0]
    lead = sorted(max(0.0, item['begin'] + (item['end'] - item['begin']) - item['now'])
                  for item in sources if item['begin'] > first + 3)
    rates = [round(item['rate'], 4) for item in sources]
    seqs = [item['seq'] for item in log['fetches'] if item['seq'] >= 0]
    produced = (seqs[-1] - seqs[0]) / 60 if len(seqs) > 1 else 0.0
    scheduled = sum(item['dur'] for item in starts if item['id'] not in stops)
    return {
        'sources': len(starts),
        'gaps': len(steady),
        'gap_ms_total': round(sum(steady) * 1000),
        'gap_ms_max': round(max(steady, default=0) * 1000),
        'late_starts': sum(1 for item in sources if item['late']),
        'queue_clears': len(log['stops']),
        'media_dropped_s': round(max(0.0, produced - scheduled * 1.0), 2) if produced else None,
        'rate_distinct': len(set(rates)),
        'rate_stdev': round(statistics.pstdev(rates), 4) if rates else 0,
        'lead_ms_mean': round(statistics.mean(lead) * 1000) if lead else 0,
        'lead_ms_min': round(lead[0] * 1000) if lead else 0,
        'lead_ms_p50': round(lead[len(lead) // 2] * 1000) if lead else 0,
        'startup_s': round(first, 2),
        'seconds': seconds,
    }


def run_scenario(browser, upstream, name, seconds, seed):
    profile, speed, manual = SCENARIOS[name]
    proxy = Proxy(upstream, profile, seed)
    url = proxy.start()
    control(upstream, 'speed', speed)
    control(upstream, 'take_control' if manual else 'resume')
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script(INSTRUMENT)
    try:
        page.goto(url, wait_until='domcontentloaded')
        page.locator('#sound').click()
        t0 = time.monotonic()
        time.sleep(seconds)
        log = page.evaluate('window.__audioLog')
        result = analyse(log, round(time.monotonic() - t0, 1), speed)
        result['status'] = page.locator('#sound-status').inner_text() if page.locator('#sound-status').count() else ''
        result['proxy_stalls'] = proxy.link.stalls
        result['errors'] = errors
    finally:
        context.close()
        proxy.stop()
        control(upstream, 'speed', 1)
        control(upstream, 'resume')
    return {'scenario': name, 'profile': profile, 'speed': speed, 'manual': manual, **result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', help='Attach to an app that is already running (it must allow control posts from its own origin).')
    parser.add_argument('--checkout', default='.', help='PokeSim checkout to launch (default: the current directory).')
    parser.add_argument('--rom', default='roms/pokered.gb')
    parser.add_argument('--game-data', default='data/game-data')
    parser.add_argument('--scenario', action='append', choices=sorted(SCENARIOS), help='Repeatable. Default: all.')
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--json', help='Also write the results to this file.')
    args = parser.parse_args(argv)
    from playwright.sync_api import sync_playwright
    process = None
    upstream = args.url
    if not upstream:
        process, upstream = launch(args)
    results = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
            for name in args.scenario or list(SCENARIOS):
                result = run_scenario(browser, upstream, name, args.seconds, args.seed)
                results.append(result)
                print(json.dumps(result), flush=True)
            browser.close()
    finally:
        if process:
            process.terminate()
            process.wait(20)
    columns = ['scenario', 'gaps', 'gap_ms_total', 'gap_ms_max', 'late_starts', 'queue_clears',
               'media_dropped_s', 'rate_distinct', 'rate_stdev', 'lead_ms_mean', 'lead_ms_min', 'startup_s', 'status']
    print('\n' + '\t'.join(columns))
    for item in results:
        print('\t'.join(str(item.get(column, '')) for column in columns))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
