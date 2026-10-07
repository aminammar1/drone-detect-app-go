"""Media discovery (FR-D1, DESCRIPTION.md section 12).

Runtime listing, extension-filtered, name-sorted. images//videos/ are
read-only. Bare folder names resolve under the repo root, so the CLI works
from the root or from detector/.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".webm"})
STREAM_SCHEMES = ("rtsp://", "rtmp://", "http://", "https://")

MediaKind = Literal["image", "video", "stream"]


class SourceError(Exception):
    """Bad --source: missing path, empty folder, or unsupported file."""


@dataclass(frozen=True)
class SourceImage:
    """Absolute path plus repo-relative URI for the event."""

    path: Path
    uri: str
    index: int


def find_repo_root(start: Path) -> Path:
    """Repo root marker is PROJECT.md."""
    for candidate in (start, *start.parents):
        if (candidate / "PROJECT.md").is_file():
            return candidate
    return start


def resolve_under_root(raw: str, repo_root: Path) -> Path:
    """As given if absolute/existing, else under the repo root."""
    path = Path(raw).expanduser()
    if path.is_absolute() or path.exists():
        return path
    return repo_root / raw


def _as_uri(path: Path, repo_root: Path) -> str:
    """Event source.uri: posix, repo-relative when possible."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_image_sources(source: str, images_dir: Path, repo_root: Path) -> list[SourceImage]:
    """Single image file or folder. Missing/empty is fatal; bad files are caller-skipped."""
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
    """cv2 target in ref; wire path in uri."""

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


#: Combined keyword for the picker: both input folders in one list.
COMBINED_SOURCES = frozenset({"media", "all", "both", "videos+images", "images+videos"})


def _scan_folder(folder: Path, repo_root: Path) -> list[Path]:
    """Supported media files in one folder, sorted by name. Missing dir is empty."""
    if not folder.is_dir():
        return []
    return sorted(
        (
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in (IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
        ),
        key=lambda p: p.name,
    )


def resolve_media_sources(
    source: str, images_dir: Path, videos_dir: Path, repo_root: Path
) -> list[MediaSource]:
    """Webcam index, stream URL, single file, folder scan, or both folders."""
    text = source.strip()
    if text.isdigit():
        return [MediaSource(kind="stream", ref=int(text), uri=f"webcam:{text}", path=None, index=0)]
    if text.lower().startswith(STREAM_SCHEMES):
        return [MediaSource(kind="stream", ref=text, uri=text, path=None, index=0)]
    if text.lower() in COMBINED_SOURCES:
        images_root = resolve_under_root(str(images_dir), repo_root)
        videos_root = resolve_under_root(str(videos_dir), repo_root)
        files = _scan_folder(videos_root, repo_root) + _scan_folder(images_root, repo_root)
        files = sorted(files, key=lambda p: p.name)
        if not files:
            raise SourceError(
                f"no supported images or videos in {videos_root} or {images_root}. Put "
                ".mp4/.avi/.mov/.mkv/.webm videos or .jpg/.jpeg/.png/.bmp/.webp "
                "images there; a single file, webcam index, or stream URL also works."
            )
        return [_media_file(p.resolve(), repo_root, i) for i, p in enumerate(files)]
    candidate = _resolve_candidate(source, repo_root)
    if not candidate.exists():
        # Bare file name (e.g. VIDEO="my clip.mp4"): look inside the input folders.
        bare = Path(source.strip()).name
        for folder in (
            resolve_under_root(str(videos_dir), repo_root),
            resolve_under_root(str(images_dir), repo_root),
        ):
            named = folder / bare
            if named.is_file():
                candidate = named
                break
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


def describe_sources(media: list[MediaSource]) -> str:
    """Numbered list for --list-sources and the picker. Plain text, no markdown."""
    lines = []
    for i, item in enumerate(media, start=1):
        if item.kind == "stream":
            detail = str(item.ref)
        else:
            detail = item.uri
        lines.append(f"{i}. {item.kind}: {detail}")
    return "\n".join(lines)
