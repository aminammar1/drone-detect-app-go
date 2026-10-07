"""Source discovery for the detector (FR-D1, DESCRIPTION section 12).

Lists folders at runtime, filters by extension, sorts by name. The `images/`
and `videos/` folders are read-only inputs: never write there. A bare folder
name (e.g. `--source images`) resolves relative to the repo root, so the CLI
works both from the repo root and from `detector/`.

M3 image helpers (`SourceImage`, `resolve_image_sources`) are kept as-is;
`MediaSource` / `resolve_media_sources` add video files, webcam indexes, and
RTSP/HTTP streams for M4.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})
STREAM_SCHEMES = ("rtsp://", "rtmp://", "http://", "https://")

MediaKind = Literal["image", "video", "stream"]


class SourceError(Exception):
    """Bad `--source`: missing path, empty folder, or unsupported file."""


@dataclass(frozen=True)
class SourceImage:
    """One input image: absolute path, repo-relative URI, and sequence index."""

    path: Path
    uri: str
    index: int


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing PROJECT.md is found."""
    for candidate in (start, *start.parents):
        if (candidate / "PROJECT.md").is_file():
            return candidate
    return start


def resolve_under_root(raw: str, repo_root: Path) -> Path:
    """Resolve a configured path: as given, else relative to the repo root."""
    path = Path(raw).expanduser()
    if path.is_absolute() or path.exists():
        return path
    return repo_root / raw


def _as_uri(path: Path, repo_root: Path) -> str:
    """Event `source.uri`: forward slashes, relative to the repo root when possible."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_image_sources(source: str, images_dir: Path, repo_root: Path) -> list[SourceImage]:
    """Turn `--source` into an ordered list of images.

    `source` may be a single image file or a folder (default: IMAGES_DIR).
    Unsupported or unreadable files are skipped by the caller with a warning;
    a missing path or an empty folder is a hard error with guidance.
    """
    candidate = Path(source).expanduser()
    if not candidate.is_absolute() and not candidate.exists():
        under_root = repo_root / source
        if under_root.exists():
            candidate = under_root
    if not candidate.exists():
        raise SourceError(
            f"source not found: {source!r}. Put test images in {images_dir} "
            "(supported: .jpg .jpeg .png .bmp .webp)."
        )
    if candidate.is_file():
        if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            raise SourceError(
                f"unsupported image file: {candidate} (supported: .jpg .jpeg .png .bmp .webp)."
            )
        resolved = candidate.resolve()
        return [SourceImage(path=resolved, uri=_as_uri(resolved, repo_root), index=0)]
    files = sorted(
        (p for p in candidate.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: p.name,
    )
    if not files:
        raise SourceError(
            f"no supported images in {candidate}. Put .jpg/.jpeg/.png/.bmp/.webp "
            "files there; a single image file also works as --source."
        )
    return [
        SourceImage(path=p.resolve(), uri=_as_uri(p, repo_root), index=i)
        for i, p in enumerate(files)
    ]


@dataclass(frozen=True)
class MediaSource:
    """One input: image file, video file, or live stream.

    `ref` is the `cv2.VideoCapture` target: a file path, a stream URL, or a
    webcam index. `uri` is the event `source.uri`.
    """

    kind: MediaKind
    ref: str | int
    uri: str
    path: Path | None
    index: int


def _resolve_candidate(source: str, repo_root: Path) -> Path:
    candidate = Path(source).expanduser()
    if not candidate.is_absolute() and not candidate.exists():
        under_root = repo_root / source
        if under_root.exists():
            candidate = under_root
    return candidate


def resolve_media_sources(
    source: str, images_dir: Path, videos_dir: Path, repo_root: Path
) -> list[MediaSource]:
    """Turn `--source` into an ordered list of images, videos, or streams.

    Accepts a webcam index (`"0"`), a stream URL (`rtsp://…`, `http(s)://…`),
    a single media file, or a folder scanned for images and videos at runtime.
    """
    text = source.strip()
    if text.isdigit():
        return [MediaSource(kind="stream", ref=int(text), uri=f"webcam:{text}", path=None, index=0)]
    if text.lower().startswith(STREAM_SCHEMES):
        return [MediaSource(kind="stream", ref=text, uri=text, path=None, index=0)]
    candidate = _resolve_candidate(source, repo_root)
    if not candidate.exists():
        raise SourceError(
            f"source not found: {source!r}. Put test videos in {videos_dir} "
            "(.mp4 .avi .mov .mkv .webm) or test images in "
            f"{images_dir} (.jpg .jpeg .png .bmp .webp)."
        )
    if candidate.is_file():
        return [_media_file(candidate.resolve(), repo_root, 0)]
    files = sorted(
        (
            p
            for p in candidate.iterdir()
            if p.is_file() and p.suffix.lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
        ),
        key=lambda p: p.name,
    )
    if not files:
        raise SourceError(
            f"no supported images or videos in {candidate}. Put "
            ".jpg/.jpeg/.png/.bmp/.webp or .mp4/.avi/.mov/.mkv/.webm files "
            "there; a single file, webcam index, or stream URL also works."
        )
    return [_media_file(p.resolve(), repo_root, i) for i, p in enumerate(files)]


def _media_file(path: Path, repo_root: Path, index: int) -> MediaSource:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        kind: MediaKind = "image"
    elif suffix in VIDEO_EXTENSIONS:
        kind = "video"
    else:
        raise SourceError(
            f"unsupported media file: {path} (images: .jpg .jpeg .png .bmp "
            ".webp; videos: .mp4 .avi .mov .mkv .webm)."
        )
    return MediaSource(
        kind=kind, ref=str(path), uri=_as_uri(path, repo_root), path=path, index=index
    )
