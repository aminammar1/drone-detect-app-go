# Detector (Python/uv + YOLO26) — headless inference, no display.
# Build:   docker build -f detector/Dockerfile -t drone-detector .
#          (build context MUST be the repo root: detector/ is a subpackage)
# Run:     docker run --rm drone-detector --help
# Weights (*.pt) are gitignored and NOT baked in. Either mount them:
#   -v ./detector/models:/app/detector/models:ro
# or point at a pretrained stand-in: -e YOLO_WEIGHTS=yolo26n.pt -e YOLO_TARGET_CLASSES=airplane
# Media is read-only input: -v ./videos:/app/videos:ro -v ./images:/app/images:ro
# Server URL inside compose: -e WS_URL=ws://server:8080/ws/detector

FROM python:3.14-slim-bookworm
ENV UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app/detector
COPY detector/pyproject.toml detector/uv.lock detector/README.md detector/.python-version ./
RUN uv sync --frozen --no-install-project
COPY detector/src/ ./src/
COPY detector/tests/ ./tests/
RUN uv sync --frozen
ENV WS_URL="ws://server:8080/ws/detector" \
    YOLO_WEIGHTS=/app/detector/models/drone.pt \
    YOLO_TARGET_CLASSES=drone \
    YOLO_CONF=0.35 \
    YOLO_IMGSZ=640 \
    SNAPSHOT_DIR=/app/data/snapshots \
    VIDEOS_DIR=/app/videos \
    IMAGES_DIR=/app/images \
    DETECTOR_CLOCK=video
ENTRYPOINT ["uv", "run", "--frozen", "--", "python", "-m", "detector.main"]
CMD ["--help"]
