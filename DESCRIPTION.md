# Drone Detect App — Detailed Description & Contracts

This document is the **source of truth** for requirements, data model, message formats, and logic.
If code and this document disagree, update one of them in the same change.

**Versions:** always the latest stable of every dependency. The dated snapshot lives in `PROJECT.md` section 2.
Do not copy version numbers into other files.

---

## 1. Functional requirements

### Detector (Python, `uv`, Ultralytics YOLO26)

- **FR-D1** Accept input from: a single image, a folder of images, a video file, a folder of videos, a webcam index, or an RTSP/HTTP stream.
  The project's own input data lives in **`videos/`** (videos) and **`images/`** (images) at the repo root (see section 12). A folder passed to `--source` is scanned for supported files and processed in name order.
- **FR-D2** Run YOLO inference with configurable weights path, confidence threshold, and image size.
- **FR-D3** Track detected drones across frames and assign a stable `track_id` (per run only; never an identity).
- **FR-D4** Emit **one** `detection` event per new track, and re-emit only after a configurable cooldown (default 30 s) if the same track is still visible.
- **FR-D5** Save a cropped or annotated snapshot to `data/snapshots/` and include the path in the event.
- **FR-D6** Maintain a WebSocket connection with automatic reconnect (exponential backoff). Buffer events in a bounded in-memory queue while disconnected.
- **FR-D7** Time basis: `--clock video` sets `detected_at = scenario_start + position_in_video` (deterministic replay); `--clock wall` uses the real clock (live camera).
- **FR-D8** Optionally attach `visual` attributes (`airframe_type`, `model_family` with confidences) when a classifier is available. Omit the field otherwise.
- **FR-D9** Optionally attach an explicit `identifier` (CLI flag or mapping file). Otherwise send `identifier.kind = "none"`.

### Server (Go + Gin)

- **FR-S1** `GET /ws/detector` — WebSocket for detectors (events up, acks down).
- **FR-S2** `GET /ws/beacons` — WebSocket for Remote ID beacon sources (simulator now, real receiver later).
- **FR-S3** `GET /ws/alerts` — WebSocket for live alert clients.
- **FR-S4** `GET /healthz`.
- **FR-S5** Validate every incoming message (schema, required fields, confidence in [0, 1]). Reject invalid ones with an `error` message; never crash. Gin `Recovery` middleware is mandatory.
- **FR-S6** Keep a **beacon buffer** keyed by event time, with retention `BEACON_RETENTION_S`.
- **FR-S7** Run the **Identity Resolver** (section 4) and then the **decision logic** (section 5) for each detection.
- **FR-S8** Persist the detection with identity details and the decision. Reply with `ack`.
- **FR-S9** Broadcast an `alert` for `unauthorized` and `unidentified` decisions (and for `authorized` if `ALERT_ON_AUTHORIZED=true`).
- **FR-S10** Queue each detection for Google Sheets export; flush in batches; fall back to local CSV and retry.
- **FR-S11** Graceful shutdown: stop accepting connections, flush the export queue, close MongoDB.

### Tools (Python `uv` scripts)

- **FR-T1** `seed_db.py`: idempotent mock data (wipes the `drone_detect_app` database unless `--keep`). Realistic manufacturers/models, plausible serials, and **consistent attributes** (e.g. a fixed-wing model must have `airframe_type = fixed_wing`).
- **FR-T2** Seed data contains: fully authorized drones, zone-limited authorizations, expired authorizations, revoked/stolen drones, unauthorized drones, and drones with `remote_id_enabled = false`.
- **FR-T3** `fake_detector.py`: sends scripted detection events (explicit identifier and/or simulated `visual`) to test the server without YOLO.
- **FR-T4** `remote_id_sim.py`: reads a scenario file and emits beacons (`--mode preload` sends all instantly using event-time timestamps; `--mode realtime` paces them with the wall clock).

---

## 2. Data model (MongoDB, database `drone_detect_app`)

### `owners`
```json
{
  "_id": "ObjectId",
  "name": "Amira Haddad",
  "type": "individual | company | government",
  "organization": "Haddad Surveying Ltd",
  "email": "amira@example.com",
  "phone": "+216 00 000 000",
  "country": "TN",
  "created_at": "ISODate"
}
```

### `drones`
```json
{
  "_id": "ObjectId",
  "serial_number": "1581F5FJC231Q0012345",
  "manufacturer": "DJI",
  "model": "Mavic 3",
  "model_version": "Classic",
  "model_family": "Mavic",
  "airframe_type": "quadcopter | hexacopter | octocopter | fixed_wing | vtol | helicopter",
  "category": "consumer | professional | industrial | racing | other",
  "weight_g": 895,
  "color": "grey",
  "owner_id": "ObjectId -> owners",
  "year_manufactured": 2023,
  "year_sold": 2023,
  "sale_history": [
    { "year": 2023, "from": "Dealer X", "to_owner_id": "ObjectId" }
  ],
  "status": "active | revoked | stolen | decommissioned",
  "remote_id_enabled": true,
  "notes": "",
  "created_at": "ISODate"
}
```
`category` is the regulatory/use category. `airframe_type` and `model_family` are the **visually checkable** attributes used by the resolver.
Indexes: unique `serial_number`; index `owner_id`, `status`, `(airframe_type, model_family)`.

### `zones`
```json
{
  "_id": "north-gate",
  "name": "North Gate",
  "description": "Entrance area, camera cam-01",
  "restriction_level": "low | medium | high | no-fly",
  "camera_ids": ["cam-01"]
}
```

### `authorizations`
```json
{
  "_id": "ObjectId",
  "drone_id": "ObjectId -> drones",
  "zone_id": "north-gate",
  "valid_from": "ISODate",
  "valid_to": "ISODate",
  "purpose": "survey | inspection | filming | delivery | security",
  "issued_by": "Security Office",
  "status": "active | revoked"
}
```
Index: compound `(drone_id, zone_id)`.

### `detections`
```json
{
  "_id": "ObjectId",
  "event_id": "uuid",
  "detected_at": "ISODate",
  "received_at": "ISODate",
  "source": { "id": "cam-01", "kind": "video", "uri": "videos/test1.mp4" },
  "zone_id": "north-gate",
  "track_id": 17,
  "class": "drone",
  "confidence": 0.91,
  "bbox": { "x1": 120, "y1": 80, "x2": 260, "y2": 170 },
  "frame_index": 1234,
  "snapshot_path": "data/snapshots/2026-06-09/uuid.jpg",
  "visual": { "airframe_type": "quadcopter", "airframe_confidence": 0.88, "model_family": "Mavic", "model_confidence": 0.61 },
  "identifier": { "kind": "serial | remote_id | qr | none", "value": "…" },
  "identity": {
    "method": "explicit | beacon | beacon+visual | none",
    "result": "identified | none | ambiguous | mismatch",
    "candidates": 1,
    "confidence": 0.9
  },
  "drone_id": "ObjectId | null",
  "decision": "authorized | unauthorized | unidentified",
  "reason": "no active authorization for zone north-gate",
  "export_status": "pending | exported | failed"
}
```
Indexes: unique `event_id` (retries are idempotent); index `detected_at`, `decision`, `export_status`.

**Beacons are not stored in MongoDB.** They live only in the server's in-memory buffer.

---

## 3. WebSocket protocol (JSON, one message per frame)

Every message has a `type` field. Timestamps are RFC 3339 UTC.

### 3.1 Detector → Server: `detection`
```json
{
  "type": "detection",
  "event_id": "b2f4c8a0-6e0b-4c61-9a4e-3a9d7c1f0e11",
  "detected_at": "2026-06-09T14:03:22.418Z",
  "source": { "id": "cam-01", "kind": "video", "uri": "videos/test1.mp4" },
  "zone_id": "north-gate",
  "track_id": 17,
  "class": "drone",
  "confidence": 0.91,
  "bbox": { "x1": 120, "y1": 80, "x2": 260, "y2": 170 },
  "frame_index": 1234,
  "snapshot_path": "data/snapshots/2026-06-09/b2f4c8a0.jpg",
  "visual": { "airframe_type": "quadcopter", "airframe_confidence": 0.88, "model_family": "Mavic", "model_confidence": 0.61 },
  "identifier": { "kind": "none" }
}
```
`visual` is optional. `identifier` is optional; when absent it is treated as `{ "kind": "none" }`.

### 3.2 Beacon source → Server: `beacon`
```json
{
  "type": "beacon",
  "serial_number": "1581F5FJC231Q0012345",
  "zone_id": "north-gate",
  "timestamp": "2026-06-09T14:03:21.000Z",
  "source": "remote_id_sim"
}
```
Real Remote ID messages also carry position and altitude; add optional `lat`, `lon`, `altitude_m` later without breaking this contract.

### 3.3 Server → Detector: `ack`
```json
{
  "type": "ack",
  "event_id": "b2f4c8a0-6e0b-4c61-9a4e-3a9d7c1f0e11",
  "decision": "unauthorized",
  "reason": "no active authorization for zone north-gate",
  "identity": { "method": "beacon+visual", "result": "identified", "candidates": 1, "confidence": 0.9 },
  "drone": {
    "serial_number": "1581F5FJC231Q0012345",
    "manufacturer": "DJI",
    "model": "Mavic 3",
    "airframe_type": "quadcopter",
    "owner_name": "Amira Haddad"
  }
}
```
`drone` is `null` when no unique drone was identified.

### 3.4 Server → Detector: `error`
```json
{ "type": "error", "event_id": "…", "code": "invalid_event", "message": "confidence must be between 0 and 1" }
```

### 3.5 Server → Alert clients: `alert`
Same fields as `ack`, plus `detected_at`, `zone_id`, `confidence`, `snapshot_path`.

### 3.6 Keep-alive
Ping/pong on all sockets; the server closes connections idle for more than 60 s without a pong.

---

## 4. Identity Resolver (`server/internal/identity`)

Input: a detection. Output: `{ method, result, drone | null, candidates, confidence }`.

```
1. If identifier.kind != "none" and value != "":
       -> candidate set = { drone with that serial }          (method = explicit)
   Else:
       -> candidate set = beacons where zone_id == event.zone_id
                          and |beacon.timestamp - detected_at| <= BEACON_WINDOW_S
                          (deduplicated by serial_number)       (method = beacon)
2. If candidate set is empty                      -> result = none
3. If detection.visual is present and its confidence >= VISUAL_MIN_CONF:
       look up candidate drones in the DB and compare airframe_type (and model_family if confident).
       a. If more than one candidate: keep only compatible ones   (method = beacon+visual)
       b. If exactly one candidate and it is incompatible          -> result = mismatch
4. If exactly one candidate remains                -> result = identified
5. If more than one remains                        -> result = ambiguous
```

Rules:
- Never use `track_id` as identity.
- A beacon whose serial is not in the DB still counts as a candidate; the decision step then returns `unidentified: not registered`.
- Compare using event time only (`detected_at`, `beacon.timestamp`), never arrival time.
- Late beacons: wait up to `RESOLVE_GRACE_MS` (default 1500) before finalizing `none`, so beacons that arrive slightly after the detection are still considered.
- `airframe_type` comparison: exact match. `model_family`: case-insensitive match, only used when `model_confidence >= VISUAL_MIN_CONF`.

---

## 5. Decision logic

Evaluated in order after the resolver; the first match wins.

1. `result == none` → **`unidentified`** — "no identifier and no Remote ID broadcast".
2. `result == ambiguous` → **`unidentified`** — "multiple matching drones".
3. `result == mismatch` → **`unidentified`** — "claimed identity does not match visual attributes (possible spoofing)".
4. Serial not found in `drones` → **`unidentified`** — "identifier not registered".
5. Drone `status` is `stolen` or `revoked` → **`unauthorized`** — "drone status: <status>".
6. Zone `restriction_level == "no-fly"` → **`unauthorized`** — "no-fly zone".
7. Authorization exists for `(drone_id, zone_id)` with `status == active` and `valid_from <= detected_at <= valid_to` → **`authorized`**.
8. Otherwise → **`unauthorized`** — "no active authorization for zone <zone_id>".

Use `detected_at` (not server time) so replayed videos are deterministic.

---

## 6. Scenario file (`scenarios/*.json`)

Drives `remote_id_sim.py`, `fake_detector.py`, and the end-to-end tests. It describes what "really" happens.

```json
{
  "scenario_id": "demo1",
  "start_time": "2026-06-09T14:00:00Z",
  "zone_id": "north-gate",
  "source_id": "cam-01",
  "video": "videos/test1.mp4",
  "beacon_interval_s": 1.0,
  "appearances": [
    {
      "label": "authorized-survey",
      "serial_number": "SERIAL_FROM_DB_1",
      "from_s": 3.0, "to_s": 14.5,
      "broadcasts_remote_id": true,
      "visual": { "airframe_type": "quadcopter", "model_family": "Mavic" }
    },
    {
      "label": "rogue-no-broadcast",
      "serial_number": null,
      "from_s": 20.0, "to_s": 31.0,
      "broadcasts_remote_id": false,
      "visual": { "airframe_type": "quadcopter" }
    },
    {
      "label": "spoofer",
      "serial_number": "SERIAL_FROM_DB_2",
      "from_s": 40.0, "to_s": 50.0,
      "broadcasts_remote_id": true,
      "visual": { "airframe_type": "fixed_wing" }
    }
  ]
}
```

- `from_s`/`to_s` are seconds on the scenario timeline (video position for video files).
- The simulator emits a beacon every `beacon_interval_s` for each appearance with `broadcasts_remote_id = true`, with `timestamp = start_time + t`.
- `visual` is used only by `fake_detector.py`. With the real detector, `visual` comes from the model (or is omitted).
- An appearance may set an optional `zone_id` (e.g. to stage a drone in a no-fly zone); it defaults to the scenario-level `zone_id` and applies to both beacons and detections.
- Expected decisions (derived from the DB and rules in section 5) go in an optional `expected` block so tests can assert them.

Required test cases: authorized drone; drone authorized for another zone only; expired authorization; revoked/stolen drone;
rogue drone without beacon; spoofer (visual mismatch); two drones at once (disambiguation); drone in a no-fly zone;
unregistered serial.

---

## 7. Google Sheets export

**Approach:** one spreadsheet, one worksheet `detections`, append one row per detection.
Create the `detections` tab first (exact name): the API never creates tabs,
and appends fail with `400 Unable to parse range` until it exists.

- Auth: a **Google Cloud service account** with the Sheets API enabled; share the spreadsheet with the service account email (Editor). Two supported modes, chosen by configuration:
  - **Keyless (default recommendation):** `GOOGLE_CREDENTIALS_FILE` is empty; the server uses **Application Default Credentials** (`sheets.NewService(ctx, option.WithScopes(sheets.SpreadsheetsScope))`). For local development the developer runs `gcloud auth application-default login --impersonate-service-account=<SA_EMAIL>`. Works in organizations that enforce `iam.disableServiceAccountKeyCreation`.
  - **Key file:** `GOOGLE_CREDENTIALS_FILE` points to a service account JSON key (`option.WithAuthCredentialsFile(option.ServiceAccount, path)`; the older `option.WithCredentialsFile` is deprecated upstream). Only where key creation is allowed.
- `EXPORT_BACKEND=csv|sheets` selects the exporter. Default `csv`, so the whole system works before Google is configured. Startup fails with a clear message if `sheets` is selected but authentication or `GOOGLE_SHEET_ID` is missing.
- `GOOGLE_SHEET_ID` (and optionally `GOOGLE_CREDENTIALS_FILE`) from env. Never log credentials.
- `spreadsheets.values.append` with `valueInputOption=USER_ENTERED`, batching up to `EXPORT_BATCH_SIZE` rows or every `EXPORT_FLUSH_SECONDS`.
- On failure: write rows to `data/exports/detections-YYYY-MM-DD.csv`, set `export_status = failed`, retry with backoff, set `exported` on success.
- On startup: re-queue detections with `export_status` `pending` or `failed`.

**Columns (in order):**
`detected_at, event_id, zone_id, source_id, track_id, confidence, decision, reason, identity_method, serial_number, manufacturer, model, model_version, model_family, airframe_type_seen, airframe_type_registered, category, owner_name, year_sold, snapshot_path`

**Why not one CSV per detection on Drive?** It clutters Drive and is slow; appending to a single Drive CSV means download-edit-reupload (race conditions).
Sheets handles concurrent appends and filtering natively.

---

## 8. Configuration (`.env`)

The full, commented template is `.env.example` in the repo root; keep it in sync with this section.

```
# Server
SERVER_ADDR=:8080
GIN_MODE=debug
MONGO_URI=mongodb://localhost:27017
MONGO_DB=drone_detect_app
EXPORT_BACKEND=csv
GOOGLE_CREDENTIALS_FILE=
GOOGLE_SHEET_ID=
EXPORT_BATCH_SIZE=50
EXPORT_FLUSH_SECONDS=5
ALERT_ON_AUTHORIZED=false
ALERT_TOKEN=
ALERT_QUEUE_SIZE=64
BEACON_WINDOW_S=3
BEACON_RETENTION_S=60
RESOLVE_GRACE_MS=1500
VISUAL_MIN_CONF=0.5
DETECTOR_TOKEN=
SNAPSHOT_DIR=../data/snapshots

# Detector
WS_URL=ws://localhost:8080/ws/detector
YOLO_WEIGHTS=./detector/models/drone.pt
YOLO_TARGET_CLASSES=drone
YOLO_CONF=0.35
YOLO_IMGSZ=640
ZONE_ID=north-gate
SOURCE_ID=cam-01
TRACK_COOLDOWN_SECONDS=30
SNAPSHOT_DIR=./data/snapshots
VIDEOS_DIR=./videos
IMAGES_DIR=./images
DETECTOR_CLOCK=video
SCENARIO_START=2026-06-09T14:00:00Z

# Visual attributes, Stage C (M8, optional, off by default)
ATTR_FAMILY_ENABLED=false
ATTR_FAMILY_WEIGHTS=./detector/models/family.pt
ATTR_FAMILY_CONF=0.5

# Simulator
BEACON_WS_URL=ws://localhost:8080/ws/beacons
```

---

## 9. Non-functional requirements

- **Windows-first:** commands work in PowerShell; use `pathlib` / `filepath`, never hard-coded separators.
- **Reliability:** no event lost during a short server outage (bounded detector buffer); no accepted detection lost (stored before export).
- **Idempotency:** `event_id` unique; a resent event returns the same decision, no duplicate row.
- **Latency target:** event to ack under 200 ms on localhost (excluding the optional `RESOLVE_GRACE_MS` wait when no beacon is found).
- **Security:** secrets only in `.env` / `secrets/` (gitignored); WebSocket origin check; optional `X-Detector-Token` header.
- **Observability:** structured logs (`log/slog` in Go, `logging` in Python) with `event_id` on every line.
- **Tests:** table-driven Go tests for the resolver and decision engine (every branch, every required test case in section 6); pytest for tracking/dedupe and event validation; a fake exporter for Sheets tests.

---

## 10. Model notes

- Pretrained COCO YOLO has **no** drone class (it may confuse drones with birds, kites, airplanes). Fine-tune the latest Ultralytics model family (YOLO26) on a public drone dataset (e.g. Roboflow Universe, Kaggle), and include **hard negatives**: birds, planes, kites, helicopters.
- Drones are small in frame. Consider larger `imgsz` (960–1280) or tiling for high-resolution video.
- **Visual attributes** (see `PROJECT.md` section 5.4): start with none; then a multi-class detector by airframe type; then optionally a crop classifier for `model_family` (Ultralytics YOLO26-cls first; a Hugging Face backbone only if needed).
- Treat attribute predictions as soft evidence: apply `VISUAL_MIN_CONF`, and never let them override a clean beacon match on their own except for the explicit mismatch rule.
- Report precision, recall, and mAP50 on a held-out set; keep a short drone-free video in `videos/` to measure false positives per minute.

---

## 11. Open questions

1. Which real identification source comes later: Remote ID receiver, QR/ArUco tags, or both?
2. How many cameras / zones for the first demo?
3. Who should be notified, and how (console, web page, Telegram, email)?
4. Can frames contain people? If so, define a snapshot retention and privacy policy.

---

## 12. Input data folders (`videos/`, `images/`)

The project owner has already placed test material in two folders at the repository root:

| Folder | Content | Supported extensions |
|---|---|---|
| `videos/` | Test videos | `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm` |
| `images/` | Test images | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp` |

Requirements:

- **Used as sources.** `detector/sources.py` must accept these folders (or single files inside them) as `--source`, e.g.
  `uv run python -m detector.main --source videos\test1.mp4` or `--source images`. Paths come from `VIDEOS_DIR` / `IMAGES_DIR` (section 8); a bare folder name resolves relative to the repo root.
- **Discover, do not hard-code.** List the folder at runtime, filter by extension, sort by name. Skip unreadable or unsupported files with a warning; never crash because of one bad file.
- **Read-only.** Never modify, rename, move, or delete files in these folders. Outputs go to `data/` (snapshots, exports).
- **Scenarios.** The `video` field of a scenario file points into `videos/` (e.g. `videos/test1.mp4`). When creating `scenarios/demo1.json`, first list `videos/` and use real file names; for video files, read the duration/FPS to set sensible `from_s` / `to_s` values.
- **Source metadata.** `source.uri` in events is the path relative to the repo root (e.g. `videos/test1.mp4`); `source.kind` is `video` or `image`.
- **Git.** Both folders are gitignored except a `.gitkeep` file (`videos/*`, `images/*`, `!videos/.gitkeep`, `!images/.gitkeep`).
- **Missing folder.** If a folder is missing or empty, print a clear message telling the user where to put files; do not create fake data.

