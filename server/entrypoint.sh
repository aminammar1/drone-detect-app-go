#!/bin/sh
# Server entrypoint: fix up the data dirs, then drop privileges.
# compose bind-mounts host ./data over /app/data, hiding the chown'd dirs
# baked at build time. The mount is owned by the host uid, so the appuser
# (65532) cannot mkdir snapshots/exports on first start -> the CSV exporter
# used to os.Exit(1) and the container crash-looped with /health never up.
# Starting as root here lets us chown the mount once, then su-exec runs the
# server as appuser so request-time file writes stay non-root.
set -eu
mkdir -p /app/data/snapshots /app/data/exports
chown -R appuser:appuser /app/data 2>/dev/null || true
exec su-exec appuser:appuser /app/server/server "$@"
