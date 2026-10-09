"""Preflight for make server / make yolo. Stdlib only. Exit 0 = ready, 1 = missing requirement."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8000"))
VENV_PY = ROOT / "detector" / ".venv" / "Scripts" / "python.exe"
MEDIA_EXTS = {
    "videos": {".mp4", ".avi", ".mov", ".mkv", ".webm"},
    "images": {".jpg", ".jpeg", ".png", ".bmp", ".webp"},
}

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def run(cmd: list[str], timeout: int = 60) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout + proc.stderr).strip().splitlines()
        return proc.returncode == 0, out[0] if out else ""
    except FileNotFoundError:
        return False, "not on PATH"
    except subprocess.TimeoutExpired:
        return False, "timed out"


def check_tool(name: str, version_args: list[str], fix: str, required: bool = True) -> None:
    path = shutil.which(name)
    if path is None:
        record("FAIL" if required else "WARN", name, f"not on PATH. Fix: {fix}")
        return
    ok, first_line = run([path, *version_args])
    record("OK" if ok else ("FAIL" if required else "WARN"), name, first_line or path)


def find_uv() -> str | None:
    """PATH first, else known install locations."""
    found = shutil.which("uv")
    if found:
        return found
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "uv.exe",
        Path(os.environ.get("USERPROFILE", "")) / ".cargo" / "bin" / "uv.exe",
        Path.home() / ".local" / "bin" / "uv",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def check_uv() -> None:
    on_path = shutil.which("uv")
    if on_path:
        ok, first_line = run([on_path, "--version"])
        record("OK" if ok else "FAIL", "uv", first_line or on_path)
        return
    found = find_uv()
    fix = 'setx PATH "%USERPROFILE%\\.local\\bin;%PATH%" then restart the terminal'
    if found:
        record("WARN", "uv", f"works at {found} but not on PATH — `make seed/sim/fake` need it on PATH. Fix: {fix}")
    else:
        record("FAIL", "uv", f"not installed. Fix: install uv (docs.astral.sh/uv), then: {fix}")


def check_mongo() -> None:
    mongosh = shutil.which("mongosh")
    if mongosh is None:
        record("FAIL", "mongosh", "not on PATH. Fix: install MongoDB Community Server + Compass/mongosh.")
        return
    ok, out = run([mongosh, "--quiet", "--eval", "db.runCommand({ping:1})"], timeout=30)
    if ok and "ok: 1" in out:
        record("OK", "mongodb", "ping ok: 1 at mongodb://localhost:27017")
    else:
        record("FAIL", "mongodb", f"ping failed ({out}). Fix: start the MongoDB Windows service.")


def check_venv_imports() -> None:
    if not VENV_PY.exists():
        record("FAIL", "detector venv", f"missing {VENV_PY}. Fix: cd detector && uv sync")
        return
    mods = "ultralytics, cv2, websockets, pydantic, pydantic_settings, typer, numpy, lap, pytest"
    ok, out = run(
        [str(VENV_PY), "-c", f"import {mods}; print('imports ok')"],
        timeout=300,
    )
    record("OK" if ok and "imports ok" in out else "FAIL", "detector venv imports", out or str(VENV_PY))


def check_env_file() -> None:
    if (ROOT / ".env").exists():
        record("OK", ".env", "present")
    else:
        record("FAIL", ".env", "missing. Fix: Copy-Item .env.example .env")


def read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = (ROOT / ".env").read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def url_port(url: str) -> str:
    """Port from ws://host:port/... ('' when absent or unparsable)."""
    try:
        host = url.split("://", 1)[1].split("/", 1)[0]
        return host.rsplit(":", 1)[1] if ":" in host else ""
    except IndexError:
        return ""


def check_detector_auth() -> None:
    """The classic HTTP-403 trap: server token set, client not sending it."""
    env = read_dotenv()
    token = env.get("DETECTOR_TOKEN", "")
    if token:
        record("OK", "detector token", "set in .env (detector + fake send X-Detector-Token automatically)")
    else:
        record("OK", "detector token", "empty (auth disabled, fine for local dev)")
    want = str(PORT)
    for key in ("WS_URL", "BEACON_WS_URL"):
        got = url_port(env.get(key, ""))
        if got and got != want:
            record(
                "WARN",
                f"{key} port",
                f".env points at :{got} but `make` runs on PORT={want} — "
                "non-make runs will talk to the wrong server",
            )
    if env.get("EXPORT_BACKEND", "csv") == "sheets" and not env.get("GOOGLE_SHEET_ID", ""):
        record("FAIL", "sheets export", "EXPORT_BACKEND=sheets but GOOGLE_SHEET_ID is empty")
    identified_only = env.get("EXPORT_IDENTIFIED_ONLY", "true").lower() not in ("0", "false", "no")
    if identified_only:
        record(
            "WARN" if not token else "OK",
            "sheets filter",
            "EXPORT_IDENTIFIED_ONLY=true: YOLO-only runs (no beacons) are "
            "unidentified and stay out of the sheet — run `make sim` first or set it to false for testing",
        )


def check_media() -> None:
    for folder, exts in MEDIA_EXTS.items():
        d = ROOT / folder
        if not d.is_dir():
            record("WARN", folder, f"folder missing — create {folder}/ and add test files")
            continue
        files = sorted(p.name for p in d.iterdir() if p.suffix.lower() in exts)
        record("OK" if files else "WARN", folder, f"{len(files)} file(s): {', '.join(files[:3])}")


def check_port() -> None:
    with socket.socket() as s:
        busy = s.connect_ex(("127.0.0.1", PORT)) == 0
    record(
        "OK",
        f"port {PORT}",
        "BUSY — server already running there, good (or stop it / use PORT=...)" if busy else "free",
    )


def check_optional() -> None:
    adc = Path(os.environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
    record("OK" if adc.exists() else "WARN", "google ADC", "present" if adc.exists() else "missing — Sheets export falls back to CSV (fine for local demo)")
    weights = ROOT / "detector" / "models" / "drone.pt"
    record(
        "OK" if weights.exists() else "WARN",
        "drone.pt",
        "trained weights present" if weights.exists() else "missing — YOLO runs with yolo26n.pt + airplane stand-in class",
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    check_tool("make", ["--version"], "choco install make -y (from an ADMIN shell)")
    check_uv()
    check_tool("go", ["version"], "install the latest stable Go toolchain")
    check_tool("mongosh", ["--version"], "install MongoDB Community Server (includes mongosh)")
    check_mongo()
    check_env_file()
    check_detector_auth()
    check_venv_imports()
    check_media()
    check_port()
    check_optional()

    failed = warn = 0
    for status, name, detail in results:
        mark = {"OK": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
        print(f"{mark} {name}: {detail}")
        failed += status == "FAIL"
        warn += status == "WARN"
    print(f"\n{len(results) - failed - warn} ok, {warn} warning(s), {failed} failure(s)")
    if failed:
        print("Fix the [FAIL] lines above, then re-run: make check")
        return 1
    print(
        "Ready: optionally run `uv run tools/seed_db.py --keep`, then `make server` + `make yolo` "
        "(second terminal)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
