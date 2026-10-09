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
import re
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
    Detection,
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
PREVIEW_WINDOW_NAME = "drone-detect (q/esc or close window to stop)"


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
        # event_id -> absolute snapshot path; generic unidentified snapshots
        # are pruned unless a visual family prediction makes them reviewable.
        self.emitted: dict[str, Path] = {}
        # event_id -> track_id, so late acks can name the on-screen box.
        self.event_tracks: dict[str, int] = {}
        self.visual_events: set[str] = set()
        # track_id -> "Maker Model" from an identified ack; drives box labels.
        self.track_names: dict[int, str] = {}
        # track_id -> family prediction; remains visibly marked as a prediction.
        self.visual_names: dict[int, tuple[str, float]] = {}
        self._seen_acks: set[str] = set()
        self.stop_requested = False

    def save_snapshot(self, frame: np.ndarray, name: str) -> tuple[str, Path] | None:
        """Write one annotated frame; returns (event path, absolute path)."""
        # Folder is the wall-clock session date (findable today); the event
        # time stays in detected_at, the DB row, and the sheet.
        day_dir = self.snapshot_base / self.session_date.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = day_dir / f"{name}.jpg"
        if not cv2.imwrite(str(snapshot_file), frame):
            logger.warning("could not write snapshot %s", snapshot_file)
            return None
        try:
            relative_snapshot = (
                snapshot_file.resolve().relative_to(self.repo_root.resolve()).as_posix()
            )
        except ValueError:
            relative_snapshot = snapshot_file.resolve().as_posix()
        return relative_snapshot, snapshot_file

    async def emit(
        self,
        *,
        class_name: str,
        confidence: float,
        bbox: tuple[float, float, float, float],
        track_id: int,
        frame: np.ndarray | None = None,
        snapshot: tuple[str, Path] | None = None,
        detected_at: datetime,
        source_kind: typing.Literal["image", "video"],
        uri: str,
        frame_index: int,
        model_family: str | None = None,
        model_confidence: float | None = None,
    ) -> str | None:
        """Snapshot, build the event, queue it. Generic classes omit visual; family needs an airframe.

        Pass `snapshot` (from save_snapshot) to share one file across several
        events; otherwise a per-event file is written from `frame`.
        """
        event_id = uuid4()
        if snapshot is None:
            if frame is None:
                logger.warning("no frame or snapshot for event; skipping")
                return None
            snapshot = self.save_snapshot(frame, str(event_id))
            if snapshot is None:
                return None
        relative_snapshot, snapshot_file = snapshot
        airframe = airframe_from_class(class_name)
        visual: Visual | None = None
        if airframe is not None or model_family is not None:
            visual = Visual(
                airframe_type=airframe,
                airframe_confidence=confidence if airframe is not None else None,
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
        self.event_tracks[str(event_id)] = track_id
        if model_family is not None and model_confidence is not None:
            self.visual_events.add(str(event_id))
        logger.info(
            "queued event_id=%s uri=%s track=%d class=%s conf=%.2f visual_family=%s visual_conf=%s",
            event_id,
            uri,
            track_id,
            class_name,
            confidence,
            model_family or "unknown",
            f"{model_confidence:.2f}" if model_confidence is not None else "unknown",
        )
        return str(event_id)

    def prune_unidentified(self, acks: dict[str, dict]) -> tuple[int, int]:
        """Prune unreviewable unidentified snapshots after server acks.

        Judged per snapshot file, not per event: several events from one
        image share a file. It survives when any event is identified or carries
        a visual family prediction worth keeping for review.
        Missing acks (timeout/offline) are kept: never delete data the
        server never judged. Returns (kept, pruned) event counts.
        """
        by_path: dict[Path, list[str]] = {}
        for event_id, path in self.emitted.items():
            by_path.setdefault(path, []).append(event_id)
        kept = 0
        pruned = 0
        for path, event_ids in by_path.items():
            msgs = [acks.get(event_id) for event_id in event_ids]
            if all(msg is None for msg in msgs):
                kept += len(event_ids)
                continue
            identified = any(
                msg is not None
                and msg.get("type") != "error"
                and (msg.get("identity") or {}).get("result") == "identified"
                for msg in msgs
            )
            has_visual_prediction = any(event_id in self.visual_events for event_id in event_ids)
            if identified or has_visual_prediction:
                kept += len(event_ids)
            else:
                self._delete_snapshot(event_ids[0], path)
                pruned += len(event_ids)
        return kept, pruned

    def refresh_names(self, acks: dict[str, dict]) -> int:
        """Fold newly arrived identified acks into track_id -> model names.

        Only unseen acks are scanned, so calling this every displayed frame
        stays cheap on long streams. Returns newly named tracks.
        """
        named = 0
        for event_id, msg in acks.items():
            if event_id in self._seen_acks:
                continue
            self._seen_acks.add(event_id)
            if msg.get("type") != "ack" or not msg.get("drone"):
                continue
            track_id = self.event_tracks.get(event_id)
            if track_id is None:
                continue
            drone = msg["drone"]
            name = f"{drone.get('manufacturer', '')} {drone.get('model', '')}".strip()
            if name and self.track_names.get(track_id) != name:
                self.track_names[track_id] = name
                named += 1
                logger.info("track=%d identified as %s", track_id, name)
        return named

    def stamp_identified(self, acks: dict[str, dict]) -> int:
        """Stamp the model name + decision onto kept snapshots.

        File/image runs send their events at the end, so acks arrive after
        the preview is gone; the snapshot file is where the name lands.
        One stamp per file (shared snapshots), first identified ack wins.
        Returns stamped files.
        """
        by_path: dict[Path, list[str]] = {}
        for event_id, path in self.emitted.items():
            by_path.setdefault(path, []).append(event_id)
        stamped = 0
        for path, event_ids in by_path.items():
            if not path.is_file():
                continue
            best: dict | None = None
            for event_id in event_ids:
                msg = acks.get(event_id)
                if msg and msg.get("type") == "ack" and msg.get("drone"):
                    best = msg
                    break
            if best is None:
                continue
            frame = cv2.imread(str(path))
            if frame is None:
                continue
            drone = best["drone"]
            line = (
                f"{drone.get('manufacturer', '')} {drone.get('model', '')} "
                f"{drone.get('serial_number', '')} | {best.get('decision', '')}"
            ).strip()
            cv2.rectangle(
                frame, (0, 0), (min(len(line) * 12 + 16, frame.shape[1]), 34), (0, 0, 0), -1
            )
            cv2.putText(
                frame,
                line,
                (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            if cv2.imwrite(str(path), frame):
                stamped += 1
        if stamped:
            logger.info("stamped %d snapshot(s) with identified model names", stamped)
        return stamped

    @staticmethod
    def _delete_snapshot(event_id: str, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("could not prune snapshot event_id=%s (%s)", event_id, exc)
            return
        logger.info("pruned non-identified snapshot event_id=%s", event_id)


def _snapshot_stem(path: Path) -> str:
    """Filesystem-safe snapshot base name derived from an image file."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem)[:64].strip("._") or "image"
    return f"{stem}-{uuid4().hex[:8]}"


async def _process_image(
    ctx: _RunContext,
    detector: Detector,
    item: MediaSource,
    detected_at: datetime,
    image_track_ids: itertools.count[int],
    family: ModelFamilyClassifier | None = None,
) -> int:
    """Stills have no tracking: every detection is its own event.

    One snapshot per image (all boxes annotated), shared by the image's
    events; pruning keeps it when a visual prediction is available.
    """
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
    classified: list[tuple[Detection, int, str | None, float | None]] = []
    for det in detections:
        track_id = next(image_track_ids)
        model_family, model_conf = await _classify(loop, family, frame, det.bbox)
        classified.append((det, track_id, model_family, model_conf))
        if model_family is not None and model_conf is not None:
            ctx.visual_names[track_id] = (model_family, model_conf)
    display_detections = [
        TrackedDetection(
            class_name=det.class_name,
            confidence=det.confidence,
            bbox=det.bbox,
            track_id=track_id,
        )
        for det, track_id, _, _ in classified
    ]
    annotated = annotate(frame, display_detections, visual_labels=ctx.visual_names or None)
    snapshot = ctx.save_snapshot(annotated, _snapshot_stem(item.path))
    if snapshot is None:
        logger.warning("skipping %s: snapshot write failed", item.uri)
        return 0
    for det, track_id, model_family, model_conf in classified:
        await ctx.emit(
            class_name=det.class_name,
            confidence=det.confidence,
            bbox=det.bbox,
            track_id=track_id,
            snapshot=snapshot,
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


def _close_windows() -> None:
    """Tear down OpenCV windows; highgui errors must never fail a run."""
    try:
        cv2.destroyAllWindows()
    except Exception as exc:  # noqa: BLE001 -- teardown only
        logger.debug("destroyAllWindows failed: %s", exc)


def _preview_stop_requested(window_name: str = PREVIEW_WINDOW_NAME) -> bool:
    """Honor keyboard and title-bar close requests while a preview is running."""
    key = cv2.waitKey(1) & 0xFF
    if key in (ord("q"), 27):
        return True
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error, AttributeError:
        # Some OpenCV backends cannot report window visibility. Keyboard
        # cancellation still works there.
        return False


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
                visual_by_track: dict[int, tuple[str, float]] = {}
                for det, track_id in fresh:
                    model_family, model_conf = await _classify(loop, family, frame, det.bbox)
                    if model_family is not None and model_conf is not None:
                        ctx.visual_names[track_id] = (model_family, model_conf)
                        visual_by_track[track_id] = (model_family, model_conf)
                annotated: np.ndarray | None = None
                if tracked and (display or fresh):
                    ctx.refresh_names(ctx.client.acks)
                    annotated = annotate(
                        frame,
                        tracked,
                        labels=ctx.track_names or None,
                        visual_labels=ctx.visual_names or None,
                    )
                for det, track_id in fresh:
                    model_family, model_conf = visual_by_track.get(track_id, (None, None))
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
                    if display and family is not None and tid not in ctx.visual_names:
                        model_family, model_conf = await _classify(loop, family, frame, det.bbox)
                        if model_family is not None and model_conf is not None:
                            ctx.visual_names[tid] = (model_family, model_conf)
                if display and tracked:
                    ctx.refresh_names(ctx.client.acks)
                    annotated = annotate(
                        frame,
                        tracked,
                        labels=ctx.track_names or None,
                        visual_labels=ctx.visual_names or None,
                    )
                else:
                    annotated = None
            if display:
                cv2.imshow(PREVIEW_WINDOW_NAME, annotated if annotated is not None else frame)
                if _preview_stop_requested():
                    ctx.stop_requested = True
                    logger.info("preview closed; stopping at frame %d", frame_index)
                    break
            # Throttle live streams only; files run full speed (an 11 s clip
            # must not take 30 s+ because of preview pacing).
            if live and frame_interval > 0:
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
        if model_family is None or model_conf is None:
            model_family, model_conf = ctx.visual_names.get(summary.track_id, (None, None))
        best = TrackedDetection(
            class_name=summary.class_name,
            confidence=summary.confidence,
            bbox=summary.bbox,
            track_id=summary.track_id,
        )
        visual_labels = (
            {summary.track_id: (model_family, model_conf)}
            if model_family is not None and model_conf is not None
            else None
        )
        annotated_best = annotate(summary.frame, [best], visual_labels=visual_labels)
        if model_family is not None and model_conf is not None:
            ctx.visual_names[summary.track_id] = (model_family, model_conf)
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
    logger.info(
        "run settings: conf=%.2f imgsz=%d stride=%d min_frames=%d max_fps=%.1f display=%s auth=%s",
        eff_conf,
        eff_imgsz,
        eff_stride,
        eff_min_frames,
        max_fps,
        display,
        "token" if settings.detector_token else "off",
    )
    client = DetectorClient(settings.ws_url, settings.ws_queue_size, token=settings.detector_token)
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
                    if ctx.stop_requested:
                        break
            except SourceError as exc:
                skipped += 1
                logger.warning("skipping %s: %s", item.uri, exc)
                continue
            except Exception as exc:  # noqa: BLE001 -- one bad file never aborts the run
                skipped += 1
                logger.warning("skipping %s after error: %s", item.uri, exc)
                continue
        # Windows are done once every file is read: close them before the
        # ack wait, so a slow/blocked server never leaves a "not responding"
        # preview window behind.
        if display:
            _close_windows()
        if ctx.sent:
            logger.info(
                "waiting for %d server ack(s) (%d event(s) sent)...",
                ctx.sent - len(client.acks),
                ctx.sent,
            )
        drained = await client.drain()
        kept, pruned = ctx.prune_unidentified(client.acks)
        stamped = ctx.stamp_identified(client.acks)
        if not drained:
            await client.close()
            await asyncio.gather(run_task, return_exceptions=True)
            await _fail(1, "timed out waiting for server acks")
    finally:
        await client.close()
        await asyncio.gather(run_task, return_exceptions=True)
        if display:
            _close_windows()
    typer.echo(
        f"done: sent {ctx.sent} detection event(s) from "
        f"{len(media) - skipped} source(s) ({skipped} skipped), "
        f"{total_frames} video frame(s) read; "
        f"snapshots kept={kept} pruned={pruned} (non-identified) "
        f"stamped={stamped} (identified model names)"
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
    try:
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
    except KeyboardInterrupt:
        # Ctrl+C during a run: _run's finally already closed the sender and
        # the windows, so just exit quietly instead of dumping a traceback.
        typer.echo("stopped by user.")
        raise typer.Exit(code=130)


if __name__ == "__main__":
    app()
