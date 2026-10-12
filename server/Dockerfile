# Server (Go + Gin) — multi-stage, static binary on Alpine.
# Build:   docker build -f server/Dockerfile -t drone-server .
#          (build context MUST be the repo root: go.mod lives in server/)
# Run:     docker run -p 8000:8080 --env-file .env drone-server
# Contracts: DESCRIPTION.md sections 3/8. Env names must stay in sync
# with server/internal/config/config.go (SERVER_ADDR, MONGO_URI, ...).

FROM golang:1.27-bookworm AS builder
WORKDIR /src/server
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /out/server ./cmd/server

FROM alpine:3.22
RUN apk add --no-cache ca-certificates wget su-exec \
    && mkdir -p /app/data/snapshots /app/data/exports \
    && adduser -D -u 65532 appuser \
    && chown -R appuser:appuser /app
COPY --from=builder /out/server /app/server/server
COPY server/entrypoint.sh /app/server/entrypoint.sh
RUN chmod +x /app/server/entrypoint.sh
WORKDIR /app/server
# NOTE: intentionally root here; entrypoint.sh chowns the ./data bind mount
# (owned by the host uid, hiding the build-time chown) then su-execs to
# appuser before running the server. Do NOT add USER appuser above this line.
EXPOSE 8080
ENV SERVER_ADDR=":8080" \
    GIN_MODE=release \
    MONGO_URI="mongodb://mongo:27017" \
    MONGO_DB=drone_detect_app \
    EXPORT_BACKEND=csv \
    SNAPSHOT_DIR=/app/data/snapshots
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1
ENTRYPOINT ["/app/server/entrypoint.sh"]
