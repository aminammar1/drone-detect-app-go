"""Detector CLI entrypoint: YOLO + tracking -> detection events -> WebSocket.

End to end (server running, seeded DB)::

    uv run python -m detector.main --source images   # image folder (M3)
    uv run python -m detector.main --source videos   # video folder (M4)

`--source` takes an image file, a video file, a folder of either, a webcam
index (`0`), or a stream URL (`rtsp://…`, `http(s)://…`). Until the
fine-tuned drone weights exist (M8), point YOLO_WEIGHTS at a pretrained model
(e.g. `yolo26n.pt`, downloaded automatically) and set YOLO_TARGET_CLASSES to a
stand-in such as `airplane`; the startup log says so explicitly.
"""

import asyncio
import itertools
import logging
import math
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import typer

from detector.attributes import ModelFamilyClassifier, crop_box
from detector.config import get_settings
from detector.detect import (
    Detector,
    TrackedDetection,
    airframe_from_class,
    annotate,
    parse_target_classes,
)
from detector.events import DetectionEvent, EventSource, Identifier, Visual
from detector.sources import (
    MediaSource,
    SourceError,
    find_repo_root,
    resolve_media_sources,
    resolve_under_root,
)
from detector.tracking import TrackDeduplicator
from detector.ws_client import DetectorClient

logger = logging.getLogger("detector")

app = typer.Typer(help="Drone Detect App — YOLO detector (M4: images + video).")

#: Fallback track ids when the tracker has not associated a box yet. Far
#: above ByteTrack's range, so they never collide with real track ids.
FALLBACK_TRACK_ID_START = 10**9


def _parse_scenario_start(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


async def _fail(code: int, message: str) -> typing.NoReturn:
    """Print an error to stderr and exit with `code` (typer.Exit takes no message)."""
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=code)


class _RunContext:
    """Shared state for one CLI run (settings, detector, sender, paths)."""

    def __init__(
        self,
        source_id: str,
        zone_id: str,
        identifier: Identifier,
        snapshot_base: Path,
        repo_root: Path,
        client: DetectorClient,
    ) -> None:
        self.source_id = source_id
        self.zone_id = zone_id
        self.identifier = identifier
        self.snapshot_base = snapshot_base
        self.repo_root = repo_root
        self.client = client
        self.sent = 0

    async def emit(
        self,
        *,
        class_name: str,
        confidence: float,
        bbox: tuple[float, float, float, float],
        track_id: int,
        frame: np.ndarray,
        detected_at: datetime,
        source_kind: typing.Literal["image", "video"],
        uri: str,
        frame_index: int,
        model_family: str | None = None,
        model_confidence: float | None = None,
    ) -> None:
        """Annotate, snapshot, build the event, and queue it for sending.

        Stage B (PROJECT.md 5.4): the YOLO class maps to
        `visual.airframe_type` via `airframe_from_class`; generic classes
        (`drone`, stand-ins) omit `visual`. Stage C passes `model_family`
        from the crop classifier; it is attached only alongside an airframe.
        """
        event_id = uuid4()
        day_dir = self.snapshot_base / detected_at.date().isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = day_dir / f"{event_id}.jpg"
        if not cv2.imwrite(str(snapshot_file), frame):
            logger.warning("could not write snapshot %s", snapshot_file)
            return
        try:
            relative_snapshot = (
                snapshot_file.resolve().relative_to(self.repo_root.resolve()).as_posix()
            )
        except ValueError:
            relative_snapshot = snapshot_file.resolve().as_posix()
        airframe = airframe_from_class(class_name)
        visual: Visual | None = None
        if airframe is not None:
            visual = Visual(
                airframe_type=airframe,
                airframe_confidence=confidence,
                model_family=model_family,
                model_confidence=model_confidence,
            )
        event = DetectionEvent(
            event_id=event_id,
            detected_at=detected_at,
            source=EventSource(id=self.source_id, kind=source_kind, uri=uri),
            zone_id=self.zone_id,
            track_id=track_id,
            **{"class": class_name},
            confidence=confidence,
            bbox={"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]},
            frame_index=frame_index,
            snapshot_path=relative_snapshot,
            visual=visual,
            identifier=self.identifier,
        )
        await self.client.submit(str(event_id), event.to_json())
        self.sent += 1
        logger.info(
            "queued event_id=%s uri=%s track=%d class=%s conf=%.2f",
            event_id,
            uri,
            track_id,
            class_name,
            confidence,
        )


async def _process_image(
    ctx: _RunContext,
    detector: Detector,
    item: MediaSource,
    detected_at: datetime,
    image_track_ids: itertools.count[int],
    family: ModelFamilyClassifier | None = None,
) -> int:
    """One still image: every detection is its own event (M3 behavior)."""
    assert item.path is not None
    loop = asyncio.get_running_loop()
    frame = await loop.run_in_executor(None, cv2.imread, str(item.path))
    if frame is None:
        logger.warning("skipping unreadable image: %s", item.path)
        return 0
    detections = await loop.run_in_executor(None, detector.predict, frame)
    if not detections:
        logger.info("no target in %s", item.uri)
        return 0
    annotated = annotate(frame, detections)
    for det in detections:
        model_family, model_conf = await _classify(loop, family, annotated, det.bbox)
        await ctx.emit(
            class_name=det.class_name,
            confidence=det.confidence,
            bbox=det.bbox,
            track_id=next(image_track_ids),
            frame=annotated,
            detected_at=detected_at,
            source_kind="image",
            uri=item.uri,
            frame_index=item.index,
            model_family=model_family,
            model_confidence=model_conf,
        )
    return len(detections)


async def _classify(
    loop: asyncio.AbstractEventLoop,
    family: ModelFamilyClassifier | None,
    frame: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> tuple[str | None, float | None]:
    """Run the Stage C classifier on one box; (None, None) when disabled."""
    if family is None:
        return None, None
    crop = crop_box(frame, bbox)
    result = await loop.run_in_executor(None, family.predict_crop, crop)
    if result is None:
        return None, None
    return result


def _open_capture(ref: str | int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(ref)
    if not cap.isOpened():
        raise SourceError(f"could not open video source: {ref!r}.")
    return cap


async def _process_video(
    ctx: _RunContext,
    detector: Detector,
    item: MediaSource,
    *,
    video_clock: bool,
    scenario_start: datetime,
    cooldown: timedelta,
    display: bool,
    max_fps: float,
    family: ModelFamilyClassifier | None = None,
) -> tuple[int, int]:
    """One video file or stream: track, dedupe by track id, emit on cooldown.

    Returns (events_sent, frames_read).
    """
    loop = asyncio.get_running_loop()
    try:
        cap = await loop.run_in_executor(None, _open_capture, item.ref)
    except SourceError as exc:
        await _fail(2, str(exc))
    if item.kind == "stream" and video_clock:
        logger.warning("streams have no media timeline; using wall clock instead of --clock video")
        video_clock = False
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps):  # 0/NaN when the container hides it (some streams)
        fps = 30.0
        logger.info("FPS unknown for %s; assuming %.0f", item.uri, fps)
    dedupe = TrackDeduplicator(cooldown)
    fallback_track_ids = itertools.count(FALLBACK_TRACK_ID_START)
    frame_index = 0
    frames = 0
    sent_before = ctx.sent
    frame_interval = 1.0 / max_fps if max_fps > 0 else 0.0
    last_pace = loop.time()
    try:
        while True:
            ok, frame = await loop.run_in_executor(None, cap.read)
            if not ok:
                if item.kind == "stream":
                    logger.warning("stream ended or dropped: %s", item.uri)
                else:
                    logger.info("end of %s (%d frames)", item.uri, frame_index)
                break
            frames += 1
            if video_clock:
                detected_at = scenario_start + timedelta(seconds=frame_index / fps)
            else:
                detected_at = datetime.now(UTC)
            # Inference + tracking run in a worker thread; the event loop
            # stays free for the WebSocket and reconnects.
            tracked = await loop.run_in_executor(None, detector.track, frame)
            fresh: list[tuple[TrackedDetection, int]] = []
            for det in tracked:
                if det.track_id is None:
                    # Not associated yet: emit once with an ephemeral id.
                    fresh.append((det, next(fallback_track_ids)))
                elif dedupe.should_emit(det.track_id, detected_at):
                    fresh.append((det, det.track_id))
            if fresh:
                annotated = annotate(frame, tracked)
                for det, track_id in fresh:
                    model_family, model_conf = await _classify(loop, family, frame, det.bbox)
                    await ctx.emit(
                        class_name=det.class_name,
                        confidence=det.confidence,
                        bbox=det.bbox,
                        track_id=track_id,
                        frame=annotated,
                        detected_at=detected_at,
                        source_kind="video",
                        uri=item.uri,
                        frame_index=frame_index,
                        model_family=model_family,
                        model_confidence=model_conf,
                    )
            if display:
                cv2.imshow("drone-detect (q to quit)", annotated if fresh else frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("quit requested; stopping at frame %d", frame_index)
                    break
            if frame_interval > 0:
                wait = frame_interval - (loop.time() - last_pace)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_pace = loop.time()
            frame_index += 1
    finally:
        cap.release()
        detector.reset_tracker()
    return ctx.sent - sent_before, frames


async def _run(
    source: str,
    clock: str | None,
    identifier_serial: str,
    display: bool,
    max_fps: float,
) -> None:
    settings = get_settings()
    repo_root = find_repo_root(Path(__file__).resolve())
    images_dir = resolve_under_root(str(settings.images_dir), repo_root)
    videos_dir = resolve_under_root(str(settings.videos_dir), repo_root)
    snapshot_base = resolve_under_root(str(settings.snapshot_dir), repo_root)

    try:
        media = resolve_media_sources(source, images_dir, videos_dir, repo_root)
    except SourceError as exc:
        await _fail(2, str(exc))

    try:
        targets = parse_target_classes(settings.yolo_target_classes)
        loop = asyncio.get_running_loop()
        detector = await loop.run_in_executor(
            None,
            lambda: Detector(
                weights=Path(settings.yolo_weights),
                conf=settings.yolo_conf,
                imgsz=settings.yolo_imgsz,
                target_classes=targets,
                repo_root=repo_root,
            ),
        )
    except (FileNotFoundError, ValueError) as exc:
        await _fail(2, str(exc))

    video_clock = (clock or settings.detector_clock) == "video"
    scenario_start = _parse_scenario_start(settings.scenario_start)
    cooldown = timedelta(seconds=settings.track_cooldown_seconds)
    identifier = (
        Identifier(kind="serial", value=identifier_serial)
        if identifier_serial
        else Identifier(kind="none")
    )
    family: ModelFamilyClassifier | None = None
    if settings.attr_family_enabled:
        try:
            family = ModelFamilyClassifier(
                weights=Path(settings.attr_family_weights),
                repo_root=repo_root,
                min_conf=settings.attr_family_conf,
            )
        except (FileNotFoundError, ValueError) as exc:
            await _fail(2, str(exc))

    client = DetectorClient(settings.ws_url, settings.ws_queue_size)
    run_task = client.attach()
    ctx = _RunContext(
        source_id=settings.source_id,
        zone_id=settings.zone_id,
        identifier=identifier,
        snapshot_base=snapshot_base,
        repo_root=repo_root,
        client=client,
    )
    try:
        image_track_ids = itertools.count(1)
        total_frames = 0
        for item in media:
            if item.kind == "image":
                if video_clock:
                    detected_at = scenario_start + timedelta(seconds=item.index)
                else:
                    detected_at = datetime.now(UTC)
                await _process_image(ctx, detector, item, detected_at, image_track_ids, family)
            else:
                _, frames = await _process_video(
                    ctx,
                    detector,
                    item,
                    video_clock=video_clock,
                    scenario_start=scenario_start,
                    cooldown=cooldown,
                    display=display,
                    max_fps=max_fps,
                    family=family,
                )
                total_frames += frames
        if not await client.drain():
            await client.close()
            await asyncio.gather(run_task, return_exceptions=True)
            await _fail(1, "timed out waiting for server acks")
    finally:
        await client.close()
        await asyncio.gather(run_task, return_exceptions=True)
        if display:
            cv2.destroyAllWindows()
    typer.echo(
        f"done: sent {ctx.sent} detection event(s) from "
        f"{len(media)} source(s), {total_frames} video frame(s) read"
    )


@app.command()
def main(
    source: str = typer.Option(
        "images",
        "--source",
        help="Image/video file, folder, webcam index (0), or stream URL.",
    ),
    clock: str | None = typer.Option(
        None,
        "--clock",
        help="Time basis: 'video' (deterministic replay) or 'wall' (live). "
        "Defaults to DETECTOR_CLOCK.",
    ),
    identifier_serial: str = typer.Option(
        "",
        "--identifier-serial",
        help="Explicit drone serial attached to every event (FR-D9).",
    ),
    display: bool = typer.Option(
        False,
        "--display",
        help="Show annotated frames while running (q quits).",
    ),
    max_fps: float = typer.Option(
        0.0,
        "--max-fps",
        help="Process at most this many frames per second (0 = unlimited).",
    ),
) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if clock is not None and clock not in ("video", "wall"):
        typer.echo("error: --clock must be 'video' or 'wall'.", err=True)
        raise typer.Exit(code=2)
    if max_fps < 0:
        typer.echo("error: --max-fps must be >= 0.", err=True)
        raise typer.Exit(code=2)
    asyncio.run(_run(source, clock, identifier_serial, display, max_fps))


if __name__ == "__main__":
    app()
