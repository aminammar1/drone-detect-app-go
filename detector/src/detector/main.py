"""Detector CLI: YOLO + tracking -> events -> WebSocket.

--source takes an image/video file, folder, webcam index, or stream URL.
Video files emit one summary event per confirmed track at end of footage
(best frame only); streams stay live. Snapshots land in the session-date
folder and only identified tracks keep theirs (server ack gates pruning).
One bad video never aborts a multi-file run. Without fine-tuned weights,
YOLO_WEIGHTS points at a pretrained model with a stand-in
YOLO_TARGET_CLASSES; startup logs it as proxy mode.
"""

import asyncio
import itertools
import logging
import math
import typing
from datetime import UTC, date, datetime, timedelta
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
    describe_sources,
    find_repo_root,
    resolve_media_sources,
    resolve_under_root,
)
from detector.tracking import TrackDeduplicator, TrackSummarizer
from detector.ws_client import DetectorClient

logger = logging.getLogger("detector")

app = typer.Typer(help="Drone Detect App — YOLO detector (images + video).")

#: Far above ByteTrack range; never collides with real ids.
FALLBACK_TRACK_ID_START = 10**9


def _parse_scenario_start(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


async def _fail(code: int, message: str) -> typing.NoReturn:
    """typer.Exit takes no message, so echo first."""
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=code)


class _RunContext:
    """Per-run shared state."""

    def __init__(
        self,
        source_id: str,
        zone_id: str,
        identifier: Identifier,
        snapshot_base: Path,
        repo_root: Path,
        client: DetectorClient,
        session_date: date,
    ) -> None:
        self.source_id = source_id
        self.zone_id = zone_id
        self.identifier = identifier
        self.snapshot_base = snapshot_base
        self.repo_root = repo_root
        self.client = client
        self.session_date = session_date
        self.sent = 0
        # event_id -> absolute snapshot path; pruned when the server says
        # the track is not an identified drone.
        self.emitted: dict[str, Path] = {}

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
    ) -> str | None:
        """Snapshot, build the event, queue it. Generic classes omit visual; family needs an airframe."""
        event_id = uuid4()
        # Folder is the wall-clock session date (findable today); the event
        # time stays in detected_at, the DB row, and the sheet.
        day_dir = self.snapshot_base / self.session_date.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = day_dir / f"{event_id}.jpg"
        if not cv2.imwrite(str(snapshot_file), frame):
            logger.warning("could not write snapshot %s", snapshot_file)
            return None
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
        self.emitted[str(event_id)] = snapshot_file
        logger.info(
            "queued event_id=%s uri=%s track=%d class=%s conf=%.2f",
            event_id,
            uri,
            track_id,
            class_name,
            confidence,
        )
        return str(event_id)

    def prune_unidentified(self, acks: dict[str, dict]) -> tuple[int, int]:
        """Delete snapshots the server did not confirm as identified.

        Missing acks (timeout/offline) are kept: never delete data the
        server never judged. Returns (kept, pruned).
        """
        kept = 0
        pruned = 0
        for event_id, path in self.emitted.items():
            msg = acks.get(event_id)
            if msg is None:
                kept += 1
                continue
            if msg.get("type") == "error":
                self._delete_snapshot(event_id, path)
                pruned += 1
                continue
            identity = msg.get("identity") or {}
            if identity.get("result") == "identified":
                kept += 1
            else:
                self._delete_snapshot(event_id, path)
                pruned += 1
        return kept, pruned

    @staticmethod
    def _delete_snapshot(event_id: str, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not prune snapshot event_id=%s (%s)", event_id, exc)
            return
        logger.info("pruned non-identified snapshot event_id=%s", event_id)


async def _process_image(
    ctx: _RunContext,
    detector: Detector,
    item: MediaSource,
    detected_at: datetime,
    image_track_ids: itertools.count[int],
    family: ModelFamilyClassifier | None = None,
) -> int:
    """Stills have no tracking: every detection is its own event."""
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
    """One box to (family, conf); (None, None) when disabled."""
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
    stride: int = 1,
    min_frames: int = 3,
    family: ModelFamilyClassifier | None = None,
) -> tuple[int, int]:
    """Video files: one summary emit per confirmed track at end of footage.

    Streams never end, so they keep the live dedupe path instead. Bad files
    are skipped. Returns (events, frames). Inference runs every `stride`-th
    frame; `detected_at` still uses the true frame position (deterministic).
    """
    loop = asyncio.get_running_loop()
    try:
        cap = await loop.run_in_executor(None, _open_capture, item.ref)
    except SourceError as exc:
        logger.warning("skipping %s: %s", item.uri, exc)
        return 0, 0
    except Exception as exc:  # noqa: BLE001 -- one bad file never aborts the run
        logger.warning("skipping %s: could not open (%s)", item.uri, exc)
        return 0, 0
    if item.kind == "stream" and video_clock:
        logger.warning("streams have no media timeline; using wall clock instead of --clock video")
        video_clock = False
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps):  # 0/NaN when the container hides it.
        fps = 30.0
        logger.info("FPS unknown for %s; assuming %.0f", item.uri, fps)
    live = item.kind == "stream"
    dedupe = TrackDeduplicator(cooldown)
    summarizer = TrackSummarizer(min_frames=min_frames)
    fallback_track_ids = itertools.count(FALLBACK_TRACK_ID_START)
    frame_index = 0
    frames = 0
    sent_before = ctx.sent
    infer_total_ms = 0.0
    infer_frames = 0
    frame_interval = 1.0 / max_fps if max_fps > 0 else 0.0
    last_pace = loop.time()
    try:
        while True:
            ok, frame = await loop.run_in_executor(None, cap.read)
            if not ok:
                if live:
                    logger.warning("stream ended or dropped: %s", item.uri)
                else:
                    logger.info("end of %s (%d frames)", item.uri, frame_index)
                break
            frames += 1
            if video_clock:
                detected_at = scenario_start + timedelta(seconds=frame_index / fps)
            else:
                detected_at = datetime.now(UTC)
            tracked: list[TrackedDetection] = []
            if frame_index % stride == 0:
                # Worker thread; keeps the loop free for socket I/O.
                infer_start = loop.time()
                try:
                    tracked = await loop.run_in_executor(None, detector.track, frame)
                except Exception as exc:  # noqa: BLE001 -- corrupt frame must not kill the file
                    logger.warning(
                        "skipping frame %d of %s: inference failed (%s)",
                        frame_index,
                        item.uri,
                        exc,
                    )
                    frame_index += 1
                    continue
                infer_ms = (loop.time() - infer_start) * 1000.0
                infer_total_ms += infer_ms
                infer_frames += 1
            if live:
                fresh: list[tuple[TrackedDetection, int]] = []
                for det in tracked:
                    if det.track_id is None:
                        # Unassociated: emit once with an ephemeral id.
                        fresh.append((det, next(fallback_track_ids)))
                    elif dedupe.should_emit(det.track_id, detected_at):
                        fresh.append((det, det.track_id))
                # Annotate only when someone looks at it or it ships.
                annotated: np.ndarray | None = None
                if tracked and (display or fresh):
                    annotated = annotate(frame, tracked)
                for det, track_id in fresh:
                    model_family, model_conf = await _classify(loop, family, frame, det.bbox)
                    assert annotated is not None
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
            else:
                for det in tracked:
                    tid = det.track_id
                    if tid is None:
                        # Single-frame ghost until associated; min_frames drops it.
                        tid = next(fallback_track_ids)
                    # frame is this read's own array, never mutated later.
                    summarizer.update(
                        tid,
                        class_name=det.class_name,
                        confidence=det.confidence,
                        bbox=det.bbox,
                        frame=frame,
                        frame_index=frame_index,
                        detected_at=detected_at,
                    )
                annotated = annotate(frame, tracked) if display and tracked else None
            if display:
                cv2.imshow(
                    "drone-detect (q to quit)", annotated if annotated is not None else frame
                )
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("quit requested; stopping at frame %d", frame_index)
                    break
            if frame_interval > 0:
                wait = frame_interval - (loop.time() - last_pace)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_pace = loop.time()
            frame_index += 1
        if not live:
            await _emit_summaries(ctx, summarizer, item, family)
    finally:
        cap.release()
        detector.reset_tracker()
    if infer_frames:
        avg_ms = infer_total_ms / infer_frames
        logger.info(
            "inference %s: %.1f ms/frame avg over %d frames (%d sampled, imgsz=%d, stride=%d)",
            item.uri,
            avg_ms,
            infer_frames,
            infer_frames,
            detector.imgsz,
            stride,
        )
    return ctx.sent - sent_before, frames


async def _emit_summaries(
    ctx: _RunContext,
    summarizer: TrackSummarizer,
    item: MediaSource,
    family: ModelFamilyClassifier | None,
) -> int:
    """One event per confirmed track, best frame only. Returns events sent."""
    loop = asyncio.get_running_loop()
    ready = summarizer.confirmed()
    logger.info(
        "track summary %s: %d confirmed of %d observed (min_frames=%d)",
        item.uri,
        len(ready),
        summarizer.tracked_count,
        summarizer._min_frames,
    )
    sent = 0
    for summary in ready:
        model_family, model_conf = await _classify(loop, family, summary.frame, summary.bbox)
        best = TrackedDetection(
            class_name=summary.class_name,
            confidence=summary.confidence,
            bbox=summary.bbox,
            track_id=summary.track_id,
        )
        annotated_best = annotate(summary.frame, [best])
        event_id = await ctx.emit(
            class_name=summary.class_name,
            confidence=summary.confidence,
            bbox=summary.bbox,
            track_id=summary.track_id,
            frame=annotated_best,
            detected_at=summary.detected_at,
            source_kind="video",
            uri=item.uri,
            frame_index=summary.frame_index,
            model_family=model_family,
            model_confidence=model_conf,
        )
        if event_id is not None:
            sent += 1
    return sent


def _pick_sources(media: list[MediaSource]) -> list[MediaSource]:
    """Prompt which source to run."""
    typer.echo("multiple sources found:")
    typer.echo(describe_sources(media))
    choice = typer.prompt("pick a number (or 'all')", default="all").strip().lower()
    if choice in ("all", "a", ""):
        return media
    try:
        picked = int(choice) - 1
    except ValueError:
        typer.echo(f"ignoring invalid choice {choice!r}; processing all sources.", err=True)
        return media
    if 0 <= picked < len(media):
        return [media[picked]]
    typer.echo(f"choice {choice!r} out of range; processing all sources.", err=True)
    return media


async def _run(
    source: str,
    clock: str | None,
    identifier_serial: str,
    display: bool,
    max_fps: float,
    pick: bool,
    list_sources: bool,
    conf: float | None,
    imgsz: int | None,
    stride: int | None,
    min_frames: int | None,
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

    if list_sources:
        typer.echo(describe_sources(media))
        return
    if pick and len(media) > 1:
        media = _pick_sources(media)

    eff_conf = conf if conf is not None else settings.yolo_conf
    eff_imgsz = imgsz if imgsz is not None else settings.yolo_imgsz
    try:
        targets = parse_target_classes(settings.yolo_target_classes)
        loop = asyncio.get_running_loop()
        detector = await loop.run_in_executor(
            None,
            lambda: Detector(
                weights=Path(settings.yolo_weights),
                conf=eff_conf,
                imgsz=eff_imgsz,
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

    eff_stride = stride if stride is not None else settings.yolo_stride
    eff_min_frames = min_frames if min_frames is not None else settings.track_min_frames
    session_date = datetime.now(UTC).date()
    client = DetectorClient(settings.ws_url, settings.ws_queue_size)
    run_task = client.attach()
    ctx = _RunContext(
        source_id=settings.source_id,
        zone_id=settings.zone_id,
        identifier=identifier,
        snapshot_base=snapshot_base,
        repo_root=repo_root,
        client=client,
        session_date=session_date,
    )
    try:
        image_track_ids = itertools.count(1)
        total_frames = 0
        skipped = 0
        kept = 0
        pruned = 0
        for item in media:
            try:
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
                        stride=eff_stride,
                        min_frames=eff_min_frames,
                        family=family,
                    )
                    total_frames += frames
            except SourceError as exc:
                skipped += 1
                logger.warning("skipping %s: %s", item.uri, exc)
                continue
            except Exception as exc:  # noqa: BLE001 -- one bad file never aborts the run
                skipped += 1
                logger.warning("skipping %s after error: %s", item.uri, exc)
                continue
        drained = await client.drain()
        kept, pruned = ctx.prune_unidentified(client.acks)
        if not drained:
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
        f"{len(media) - skipped} source(s) ({skipped} skipped), "
        f"{total_frames} video frame(s) read; "
        f"snapshots kept={kept} pruned={pruned} (non-identified)"
    )


@app.command()
def main(
    source: str = typer.Option(
        "images",
        "--source",
        help="Image/video file, folder, webcam index (0), stream URL, or "
        "'media' for videos+images. Bare file names are searched in videos/ and images/.",
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
    pick: bool = typer.Option(
        False,
        "--pick",
        help="When --source resolves to several files, ask which one to run.",
    ),
    list_sources: bool = typer.Option(
        False,
        "--list-sources",
        help="List the files --source resolves to, then exit without running YOLO.",
    ),
    conf: float | None = typer.Option(
        None,
        "--conf",
        help="YOLO confidence threshold (overrides YOLO_CONF; lower = more boxes, slower).",
    ),
    imgsz: int | None = typer.Option(
        None,
        "--imgsz",
        help="YOLO image size (overrides YOLO_IMGSZ; 480 = fast, 960+ = small drones, slow).",
    ),
    stride: int | None = typer.Option(
        None,
        "--stride",
        help="Video inference stride: run YOLO every Nth frame (overrides YOLO_STRIDE; 2-3 is faster, tracks may fragment).",
    ),
    min_frames: int | None = typer.Option(
        None,
        "--min-frames",
        help="Video file summary: tracks seen in fewer frames never emit (overrides TRACK_MIN_FRAMES).",
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
    if conf is not None and not 0.0 <= conf <= 1.0:
        typer.echo("error: --conf must be between 0 and 1.", err=True)
        raise typer.Exit(code=2)
    if imgsz is not None and imgsz <= 0:
        typer.echo("error: --imgsz must be > 0.", err=True)
        raise typer.Exit(code=2)
    if stride is not None and stride < 1:
        typer.echo("error: --stride must be >= 1.", err=True)
        raise typer.Exit(code=2)
    if min_frames is not None and min_frames < 1:
        typer.echo("error: --min-frames must be >= 1.", err=True)
        raise typer.Exit(code=2)
    asyncio.run(
        _run(
            source,
            clock,
            identifier_serial,
            display,
            max_fps,
            pick,
            list_sources,
            conf,
            imgsz,
            stride,
            min_frames,
        )
    )


if __name__ == "__main__":
    app()
