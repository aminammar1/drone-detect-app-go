"""Tests for image source discovery (runtime listing, never hard-coded names)."""

from pathlib import Path

import pytest

from detector.sources import (
    SourceError,
    find_repo_root,
    resolve_image_sources,
    resolve_media_sources,
)


def _touch(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).write_bytes(b"fake")


def test_folder_discovery_sorts_and_filters(tmp_path: Path) -> None:
    _touch(tmp_path, "b.png", "a.jpg", "notes.txt", "c.webp")
    found = resolve_image_sources(str(tmp_path), tmp_path, tmp_path)
    assert [s.path.name for s in found] == ["a.jpg", "b.png", "c.webp"]
    assert [s.index for s in found] == [0, 1, 2]


def test_single_file_source(tmp_path: Path) -> None:
    _touch(tmp_path, "one.bmp")
    (found,) = resolve_image_sources(str(tmp_path / "one.bmp"), tmp_path, tmp_path)
    assert found.path.name == "one.bmp"
    assert found.index == 0


def test_unsupported_single_file_rejected(tmp_path: Path) -> None:
    _touch(tmp_path, "clip.mp4")
    with pytest.raises(SourceError, match="unsupported"):
        resolve_image_sources(str(tmp_path / "clip.mp4"), tmp_path, tmp_path)


def test_missing_source_names_the_folder(tmp_path: Path) -> None:
    images_dir = tmp_path / "images"
    with pytest.raises(SourceError, match="Put test images"):
        resolve_image_sources("images", images_dir, tmp_path)


def test_empty_folder_rejected(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="no supported images"):
        resolve_image_sources(str(tmp_path), tmp_path, tmp_path)


def test_bare_folder_name_resolves_under_repo_root(tmp_path: Path) -> None:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    _touch(images_dir, "shot.png")
    (found,) = resolve_image_sources("images", images_dir, tmp_path)
    assert found.uri == "images/shot.png"


def test_find_repo_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.md").write_text("x")
    nested = tmp_path / "detector" / "src"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == tmp_path


def _media(source: str, tmp_path: Path):
    return resolve_media_sources(source, tmp_path / "images", tmp_path / "videos", tmp_path)


def test_webcam_index_is_a_stream(tmp_path: Path) -> None:
    (found,) = _media("0", tmp_path)
    assert (found.kind, found.ref, found.uri) == ("stream", 0, "webcam:0")


def test_rtsp_and_http_urls_are_streams(tmp_path: Path) -> None:
    for url in ("rtsp://cam.local:8554/live", "http://cam.local:8080/mjpeg"):
        (found,) = _media(url, tmp_path)
        assert found.kind == "stream"
        assert found.ref == url


def test_single_video_file(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    (found,) = _media(str(clip), tmp_path)
    assert found.kind == "video"
    assert found.uri == "clip.mp4"


def test_folder_mixes_images_and_videos_sorted(tmp_path: Path) -> None:
    for name in ("b.mp4", "a.jpg", "notes.txt"):
        (tmp_path / name).write_bytes(b"fake")
    found = _media(str(tmp_path), tmp_path)
    assert [(s.path.name, s.kind) for s in found] == [("a.jpg", "image"), ("b.mp4", "video")]


def test_missing_media_source_names_both_folders(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="Put test videos"):
        _media("videos", tmp_path)
