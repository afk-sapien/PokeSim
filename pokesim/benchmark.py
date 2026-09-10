"""Repeatable policy evaluation using emulated time and fixed frame budgets."""
import argparse
import hashlib
import io
import json
import platform
from importlib.metadata import version
from collections import Counter
from pathlib import Path
from statistics import mean

from . import config, game_data
from .policies import POLICIES, make_policy
from .policies.base import PolicyContext
from .policies.progression import milestones
from .ram import read_snapshot
from .screen import Screen, W_OPTIONS


def policy_fingerprint():
    root = Path(__file__).parent
    paths = sorted((root / "policies").glob("*.py")) + [root / name for name in
            ("screen.py", "ram.py", "strategy_data.py", "benchmark.py", "game_data.py")]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    for name in game_data.FILES:
        digest.update((game_data.bundle_path() / name).read_bytes())
    return digest.hexdigest()


class Metrics:
    def __init__(self):
        self.milestones = {}
        self.blackouts = 0
        self.dead = False
        self.dead_since = None
        self.areas = set()
        self.modes = Counter()

    def observe(self, snapshot, elapsed):
        if not snapshot.valid or not snapshot.started:
            return
        self.areas.add(snapshot.map)
        dead = snapshot.all_fainted or snapshot.in_battle == 255
        if dead and self.dead_since is None:
            self.dead_since = elapsed
        if dead and not self.dead and elapsed - self.dead_since >= 30:
            self.blackouts += 1
            self.dead = True
        if not dead:
            self.dead = False
            self.dead_since = None
        for name, complete in milestones(snapshot).items():
            if complete:
                self.milestones.setdefault(name, elapsed)


def run(rom, policy_name, seed, frames, checkpoint=None, target=None, trace=None):
    from pyboy import PyBoy
    pb = PyBoy(str(rom), window="null", sound_emulated=False)
    pb.set_emulation_speed(0)
    policy = make_policy(policy_name, seed)
    rom_sha = hashlib.sha1(Path(rom).read_bytes()).hexdigest()
    if hasattr(policy, "nav"):
        policy.nav.use_world = rom_sha in config.KNOWN_ROM_SHA1
    metrics = Metrics()
    frame = 0
    last_pos = None
    stuck_frame = battle_frame = invalid_frame = None
    saves = []
    next_save = 3600
    reloads = 0
    last_reload = -3600
    last_trace = None
    try:
        if checkpoint:
            with Path(checkpoint).open("rb") as f:
                pb.load_state(f)
        first = read_snapshot(pb.memory, frame)
        initial = sorted(name for name, done in milestones(first).items() if done)
        metrics.observe(first, 0)
        while frame < frames:
            snapshot = read_snapshot(pb.memory, frame)
            metrics.observe(snapshot, frame)
            if target and target in metrics.milestones:
                break
            if snapshot.started:
                pb.memory[W_OPTIONS] = (pb.memory[W_OPTIONS] & ~7) | 1
                if not config.BATTLE_ANIMATIONS:
                    pb.memory[W_OPTIONS] |= 128
            pos = (snapshot.map, snapshot.x, snapshot.y)
            if pos != last_pos or snapshot.in_battle or not snapshot.started:
                stuck_frame = frame
                last_pos = pos
            battle_frame = (frame if battle_frame is None else battle_frame) if snapshot.in_battle in (1, 2) else None
            invalid_frame = (frame if invalid_frame is None else invalid_frame) if not snapshot.valid else None
            if frame >= next_save and snapshot.valid:
                state = io.BytesIO()
                pb.save_state(state)
                saves.append((frame, state.getvalue()))
                saves = saves[-20:]
                next_save = frame + 3600
            trouble = next((since for since, budget in ((invalid_frame, 300), (battle_frame, 54000), (stuck_frame, 36000))
                            if since is not None and frame - since >= budget), None)
            if trouble is not None and frame - last_reload >= 3600 and saves:
                older = [sv for sv in saves if sv[0] < trouble - 1800] or saves[:1]
                pb.load_state(io.BytesIO(older[-1][1]))
                policy.on_restore()
                reloads += 1
                last_reload = frame
                last_pos = None
                stuck_frame = battle_frame = invalid_frame = None
                continue
            ctx = PolicyContext(snapshot, (frame - (stuck_frame or 0)) / 60, frame / 60, pb.memory)
            actions = policy.step(ctx)
            mode = getattr(policy, "mode", policy_name)
            signature = (pos, snapshot.in_battle, mode, tuple(p.level for p in snapshot.party), snapshot.items, Screen(pb.memory).text)
            if trace and signature != last_trace:
                trace.write(json.dumps({"frame": frame, "position": pos, "mode": mode,
                                        "screen": Screen(pb.memory).text, "strategy": policy.details()}) + "\n")
                last_trace = signature
            for action in actions:
                if frame >= frames:
                    break
                if action.button is not None:
                    pb.button_press(action.button)
                for part in (action.hold, action.gap):
                    remaining = min(part, frames - frame)
                    while remaining:
                        chunk = min(remaining, 4)
                        pb.tick(chunk, render=False)
                        frame += chunk
                        remaining -= chunk
                        metrics.modes[mode] += chunk
                        metrics.observe(read_snapshot(pb.memory, frame), frame)
                    if action.button is not None:
                        pb.button_release(action.button)
            if not actions:
                remaining = min(12, frames - frame)
                pb.tick(remaining, render=False)
                frame += remaining
        final = read_snapshot(pb.memory, frame)
        return {"policy": policy_name, "seed": seed, "frames": frame, "frame_budget": frames,
                "checkpoint": str(checkpoint) if checkpoint else None, "target": target,
                "success": target in metrics.milestones if target else None,
                "initial_milestones": initial, "milestones": metrics.milestones,
                "blackouts": metrics.blackouts, "recovery_reloads": reloads, "manual_interventions": 0,
                "policy_recoveries": policy.details().get("recoveries", 0), "areas": len(metrics.areas),
                "mode_frames": dict(metrics.modes), "final": final.to_dict(), "final_screen": Screen(pb.memory).text,
                "strategy": policy.details(), "rom_sha1": rom_sha, "python": platform.python_version(),
                "pyboy": version("pyboy"), "battle_animations": config.BATTLE_ANIMATIONS,
                "policy_fingerprint": policy_fingerprint(),
                "checkpoint_sha256": hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest() if checkpoint else None}
    finally:
        pb.stop(save=False)


def aggregate(runs):
    groups = {}
    for result in runs:
        groups.setdefault((result["scenario"], result["policy"]), []).append(result)
    summary = []
    for (scenario, policy), results in groups.items():
        names = sorted({m for result in runs for m in result["milestones"]}
                       | {result["target"] for result in runs if result.get("target")})
        summary.append({"scenario": scenario, "policy": policy, "runs": len(results),
                        "mean_blackouts": mean(r["blackouts"] for r in results),
                        "mean_reloads": mean(r["recovery_reloads"] for r in results),
                        "milestones": {name: {"completion_rate": sum(name in r["milestones"] for r in results) / len(results),
                                              "mean_frames_on_success": mean(r["milestones"][name] for r in results if name in r["milestones"])
                                              if any(name in r["milestones"] for r in results) else None}
                                       for name in names}})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=config.ROM_PATH)
    parser.add_argument("--policies", nargs="+", choices=sorted(POLICIES), default=["strategic", "smart_random"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--frames", type=int, default=200000)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--target", choices=["starter", "parcel", "pokedex", "boulder", "cascade", "champion"])
    parser.add_argument("--scenarios", type=Path, help="JSON list of name, checkpoint, target, and frames")
    parser.add_argument("--output", type=Path, default=Path("data/benchmark.json"))
    parser.add_argument("--trace", type=Path, help="Decision trace as JSONL for a single run")
    args = parser.parse_args()
    if args.frames <= 0:
        parser.error("--frames must be positive")
    scenarios = json.loads(args.scenarios.read_text()) if args.scenarios else [dict(
        name="checkpoint" if args.checkpoint else "boot", checkpoint=args.checkpoint, target=args.target, frames=args.frames)]
    if args.trace and len(scenarios) * len(args.policies) * len(args.seeds) != 1:
        parser.error("--trace requires one scenario, policy, and seed")
    results = []
    for scenario in scenarios:
        checkpoint = scenario.get("checkpoint")
        if checkpoint and args.scenarios and not Path(checkpoint).is_absolute():
            checkpoint = args.scenarios.parent / checkpoint
        budget = int(scenario.get("frames", args.frames))
        if budget <= 0:
            parser.error("scenario frame budgets must be positive")
        for policy in args.policies:
            for seed in args.seeds:
                trace = args.trace.open("w") if args.trace else None
                try:
                    result = run(args.rom, policy, seed, budget, checkpoint, scenario.get("target"), trace)
                finally:
                    if trace:
                        trace.close()
                result["scenario"] = scenario["name"]
                results.append(result)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps({"runs": results, "summary": aggregate(results)}, indent=2) + "\n")
                print(f"{scenario['name']} {policy} seed={seed}: {result['milestones']} blackouts={result['blackouts']} reloads={result['recovery_reloads']}", flush=True)


if __name__ == "__main__":
    main()
