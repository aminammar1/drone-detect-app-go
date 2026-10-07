"""Simulated Remote ID beacons (FR-T4, DESCRIPTION.md section 6).

One beacon per beacon_interval_s per broadcasting appearance. Timestamps
are event time, so preload and realtime correlate identically.
"""

# /// script
# requires-python = ">=3.14"
# dependencies = ["websockets"]
# ///

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Emit simulated Remote ID beacons.")
    p.add_argument("--scenario", default=os.getenv("SCENARIO_FILE", "scenarios/demo1.json"))
    p.add_argument("--mode", choices=("preload", "realtime"), default="preload")
    p.add_argument(
        "--beacon-ws-url",
        default=os.getenv("BEACON_WS_URL", "ws://localhost:8080/ws/beacons"),
    )
    return p.parse_args()


def load_scenario(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            scenario = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read scenario {path}: {exc}") from exc
    for key in ("scenario_id", "start_time", "zone_id", "appearances"):
        if key not in scenario:
            raise SystemExit(f"scenario {path} is missing {key!r}")
    try:
        scenario["_start"] = datetime.fromisoformat(scenario["start_time"])
    except ValueError as exc:
        raise SystemExit(f"scenario {path} has a bad start_time: {exc}") from exc
    if scenario["_start"].tzinfo is None:
        scenario["_start"] = scenario["_start"].replace(tzinfo=UTC)
    scenario.setdefault("beacon_interval_s", 1.0)
    return scenario


def beacons_for(appearance: dict, scenario: dict) -> list[dict]:
    """All beacons for one appearance, stamped in event time."""
    if not appearance.get("broadcasts_remote_id", False):
        return []
    if not appearance.get("serial_number"):
        print(f"  [warn] {appearance.get('label')}: broadcasts but has no serial; skipped")
        return []
    zone = appearance.get("zone_id", scenario["zone_id"])
    interval = scenario["beacon_interval_s"]
    start: datetime = scenario["_start"]
    beacons, t = [], appearance["from_s"]
    while t <= appearance["to_s"] + 1e-9:
        beacons.append(
            {
                "type": "beacon",
                "serial_number": appearance["serial_number"],
                "zone_id": zone,
                "timestamp": (start + timedelta(seconds=t)).isoformat().replace("+00:00", "Z"),
                "source": "remote_id_sim",
            }
        )
        t += interval
    return beacons


async def send_all(beacons: list[dict], ws_url: str) -> None:
    from websockets.asyncio.client import connect

    async with connect(ws_url) as ws:
        for beacon in beacons:
            await ws.send(json.dumps(beacon))
    print(f"preloaded {len(beacons)} beacons")


async def send_realtime(scenario: dict, ws_url: str) -> None:
    """Wall-clock pacing: sim second t goes out at start+t."""
    from websockets.asyncio.client import connect

    timeline: list[tuple[float, dict]] = []
    for appearance in scenario["appearances"]:
        for beacon in beacons_for(appearance, scenario):
            sim_t = (
                datetime.fromisoformat(beacon["timestamp"]) - scenario["_start"]
            ).total_seconds()
            timeline.append((sim_t, beacon))
    timeline.sort(key=lambda item: item[0])
    if not timeline:
        print("no beacons to send (nobody broadcasts)")
        return
    print(f"realtime: {len(timeline)} beacons over {timeline[-1][0]:.1f}s")
    wall_start = asyncio.get_running_loop().time()
    async with connect(ws_url) as ws:
        for sim_t, beacon in timeline:
            delay = wall_start + sim_t - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
            await ws.send(json.dumps(beacon))
    print("realtime run finished")


async def run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    print(f"scenario {scenario['scenario_id']}: {args.mode} -> {args.beacon_ws_url}")
    if args.mode == "preload":
        beacons = [
            beacon
            for appearance in scenario["appearances"]
            for beacon in beacons_for(appearance, scenario)
        ]
        await send_all(beacons, args.beacon_ws_url)
    else:
        await send_realtime(scenario, args.beacon_ws_url)
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
