"""Summarize recorded endurance samples without exporting raw game state."""
import argparse
import json
import re
import statistics
from pathlib import Path


def memory_mib(value):
    match = re.match(r'([0-9.]+)([KMG]?i?B)', value.split('/')[0].strip())
    if not match:
        raise ValueError(f'Unknown memory format: {value}')
    size, unit = match.groups()
    return float(size) * {'B': 1 / 1048576, 'kB': 1000 / 1048576, 'KB': 1000 / 1048576,
                          'KiB': 1 / 1024, 'MB': 1000000 / 1048576, 'MiB': 1,
                          'GB': 1000000000 / 1048576, 'GiB': 1024}[unit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    status = json.loads((args.directory / 'status.json').read_text())
    sample_path = args.directory / 'samples.jsonl'
    samples = [json.loads(line) for line in sample_path.read_text().splitlines()] if sample_path.exists() else []
    result = {key: status.get(key) for key in ('status', 'started_at', 'updated_at', 'finished_at', 'image', 'configuration', 'failures')}
    result['failed_health'] = {label: point['health'] for label, point in status.get('failed_sample', {}).get('runs', {}).items()
                               if 'health' in point and not point['health'].get('ok')}
    result['sample_count'] = len(samples)
    result['observed_seconds'] = samples[-1]['elapsed_seconds'] - samples[0]['elapsed_seconds'] if samples else 0
    result['runs'] = {}
    for label, run in status['runs'].items():
        points = [sample['runs'][label] for sample in samples if label in sample['runs']]
        run_status = run['status']
        if status['status'] == 'failed' and run_status == 'running':
            run_status = 'not_completed'
        if not points:
            result['runs'][label] = {'status': run_status, 'samples': 0}
            continue
        result['runs'][label] = {'status': run_status, 'uninterrupted': run.get('uninterrupted'),
                                'final_frame': points[-1]['frame'], 'final_reloads': points[-1]['reloads'],
                                'cpu_median_percent': round(statistics.median(float(p['cpu_percent'].rstrip('%')) for p in points), 2),
                                'cpu_max_percent': max(float(p['cpu_percent'].rstrip('%')) for p in points),
                                'memory_first_mib': round(memory_mib(points[0]['memory']), 1),
                                'memory_last_mib': round(memory_mib(points[-1]['memory']), 1),
                                'memory_max_mib': round(max(memory_mib(p['memory']) for p in points), 1),
                                'data_first_bytes': points[0]['data_bytes'], 'data_last_bytes': points[-1]['data_bytes'],
                                'viewer_groups': {}}
        for viewers in (0, 1, 4):
            group = [s['runs'][label] for s in samples if s['viewers'] == viewers and label in s['runs']]
            if group:
                result['runs'][label]['viewer_groups'][viewers] = {
                    'samples': len(group),
                    'cpu_median_percent': round(statistics.median(float(p['cpu_percent'].rstrip('%')) for p in group), 2),
                    'memory_median_mib': round(statistics.median(memory_mib(p['memory']) for p in group), 1),
                }
    result['stream_payload_mbps'] = {}
    for viewers in (1, 4):
        rates = []
        for previous, current in zip(samples, samples[1:]):
            seconds = current['elapsed_seconds'] - previous['elapsed_seconds']
            if previous['viewers'] == current['viewers'] == viewers and seconds > 0:
                rates.append(current['stream_bytes_since_previous_sample'] * 8 / seconds / 1000000)
        if rates:
            result['stream_payload_mbps'][viewers] = round(statistics.median(rates), 3)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
