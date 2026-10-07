"""Scenario-driven fake detector for M5 server tests (FR-T3).

Reads the same scenario file as remote_id_sim.py (DESCRIPTION.md section 6)
and sends one detection per appearance with the appearance's simulated
`visual` and NO explicit identifier, so identity must come from beacon
correlation. Each appearance carries its `expected` decision, which is
checked against the ack. Also demonstrates idempotency (resends the first
event) and validation (one deliberately invalid event expects an error).

Run AFTER preloading beacons (server running, DB seeded):
    uv run tools\\remote_id_sim.py --scenario scenarios\\demo1.json --mode preload
    uv run tools\\fake_detector.py --scenario scenarios\\demo1.json
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
import uuid
from datetime import UTC, datetime, timedelta


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send scenario detections to the server.")
    p.add_argument("--scenario", default=os.getenv("SCENARIO_FILE", "scenarios/demo1.json"))
    p.add_argument("--ws-url", default=os.getenv("WS_URL", "ws://localhost:8080/ws/detector"))
    return p.parse_args()


def load_scenario(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        scenario = json.load(f)
    start = datetime.fromisoformat(scenario["start_time"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    scenario["_start"] = start
    return scenario


def build_event(scenario: dict, appearance: dict, track_id: int) -> dict:
    """One detection per appearance, early in its window, identifier always none."""
    detected_at = scenario["_start"] + timedelta(seconds=appearance["from_s"] + 0.5)
    event: dict = {
        "type": "detection",
        "event_id": str(uuid.uuid4()),
        "detected_at": detected_at.isoformat().replace("+00:00", "Z"),
        "source": {
            "id": scenario.get("source_id", "cam-01"),
            "kind": "video",
            "uri": scenario.get("video", "fake_detector"),
        },
        "zone_id": appearance.get("zone_id", scenario["zone_id"]),
        "track_id": track_id,
        "class": "drone",
        "confidence": 0.9,
        "bbox": {"x1": 120, "y1": 80, "x2": 260, "y2": 170},
        "frame_index": track_id * 100,
        "identifier": {"kind": "none"},
    }
    sim_visual = appearance.get("visual")
    if sim_visual:
        event["visual"] = {
            "airframe_type": sim_visual["airframe_type"],
            "airframe_confidence": sim_visual.get("airframe_confidence", 0.88),
            "model_family": sim_visual.get("model_family", ""),
            "model_confidence": sim_visual.get("model_confidence", 0.61),
        }
        if not event["visual"]["model_family"]:
            del event["visual"]["model_family"]
            del event["visual"]["model_confidence"]
    return event


async def run(args: argparse.Namespace) -> int:
    from websockets.asyncio.client import connect

    scenario = load_scenario(args.scenario)
    appearances = scenario["appearances"]

    failures = 0
    first_event: dict | None = None
    print(f"scenario {scenario['scenario_id']}: {len(appearances)} appearances")
    print(f"{'appearance':<20} {'zone':<17} {'beacon':<20} {'want':<13} got")
    async with connect(args.ws_url) as ws:
        for i, appearance in enumerate(appearances, start=1):
            event = build_event(scenario, appearance, i)
            if first_event is None:
                first_event = event
            await ws.send(json.dumps(event))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except TimeoutError:
                print(f"[{appearance['label']}] TIMEOUT waiting for ack")
                failures += 1
                continue
            ack = json.loads(raw)
            want = appearance["expected"]["decision"]
            ok = ack.get("type") == "ack" and ack.get("decision") == want
            reason_ok = ack.get("reason") == appearance["expected"]["reason"]
            if not ok or not reason_ok:
                failures += 1
            mark = "PASS" if ok and reason_ok else "FAIL"
            serial = appearance.get("serial_number") or "(silent)"
            zone = appearance.get("zone_id", scenario["zone_id"])
            print(
                f"[{mark}] {appearance['label']:<18} {zone:<17} {serial:<20} "
                f"{want:<13} {ack.get('decision')} ({ack.get('reason')})"
            )

        # Idempotency: resend the first event verbatim, expect the same ack.
        assert first_event is not None
        await ws.send(json.dumps(first_event))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        same = (
            ack.get("type") == "ack"
            and ack.get("decision") == appearances[0]["expected"]["decision"]
        )
        print(f"[{'PASS' if same else 'FAIL'}] resend {first_event['event_id']}")
        failures += 0 if same else 1

        # Validation: confidence outside [0,1] must get an error reply.
        bad = build_event(scenario, appearances[0], 999)
        bad["event_id"] = str(uuid.uuid4())
        bad["confidence"] = 2.0
        await ws.send(json.dumps(bad))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        valid_err = reply.get("type") == "error" and reply.get("code") == "invalid_event"
        print(f"[{'PASS' if valid_err else 'FAIL'}] invalid event reply={json.dumps(reply)}")
        failures += 0 if valid_err else 1

    total = len(appearances) + 2
    print(f"done: {total - failures}/{total} checks passed")
    return 0 if failures == 0 else 1


def main() -> None:
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
