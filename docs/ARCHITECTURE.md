# Architecture (M8)

Source of truth for contracts stays `DESCRIPTION.md`; milestone order and the
version snapshot stay `PROJECT.md` 2/8. This file reuses the pipeline diagrams
so the running code can be checked against them in one place.

## End-to-end flow

```mermaid
flowchart LR
    subgraph SRC["Inputs"]
        IMG["Images (images/ folder)"]
        VID["Video files (videos/ folder)"]
        CAM["Camera / RTSP"]
    end

    subgraph DET["detector/ (Python, uv)"]
        S1["1. Read frame"]
        S2["2. YOLO26 detect: drone"]
        S3["3. Track + dedupe (track_id, cooldown)"]
        S4["4. Visual attributes: airframe_type, model_family (optional)"]
        S5["5. Save snapshot + build detection event"]
        S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph SIM["tools/remote_id_sim.py (simulated Remote ID)"]
        B1["Scenario file: who is in the air, when, where"]
        B2["Emit beacons: serial_number, zone_id, timestamp"]
        B1 --> B2
    end

    subgraph SRV["server/ (Go + Gin)"]
        W1["/ws/detector"]
        W2["/ws/beacons"]
        P1["Beacon buffer (event-time, retention)"]
        R1["Identity Resolver"]
        A1["Authorization Engine"]
        ST["Persist detection"]
        H1["/ws/alerts hub"]
        X1["Export queue"]
        W2 --> P1
        W1 --> R1
        P1 --> R1
        R1 --> A1 --> ST
        ST --> H1
        ST --> X1
    end

    DB[("MongoDB: drones, owners, zones, authorizations, detections")]
    GS["Google Sheets (append rows)"]
    CSV["Local CSV fallback"]
    CL["Alert clients: console / web page"]

    IMG --> S1
    VID --> S1
    CAM --> S1
    S5 -- "detection event (WebSocket)" --> W1
    B2 -- "beacon (WebSocket)" --> W2
    W1 -. "ack: decision + drone info" .-> S5
    R1 <--> DB
    A1 <--> DB
    ST --> DB
    X1 --> GS
    X1 -. "on failure" .-> CSV
    H1 --> CL
```

## Sequence for one detection

```mermaid
sequenceDiagram
    autonumber
    participant Sim as Remote ID Simulator
    participant Det as Detector (YOLO26)
    participant Srv as Server (Gin)
    participant Res as Identity Resolver
    participant DB as MongoDB
    participant Out as Sheets / CSV
    participant Al as Alert clients

    Sim->>Srv: beacon {serial_number, zone_id, timestamp} (about 1 per second per drone)
    Srv->>Srv: store in beacon buffer (event-time)
    Det->>Det: frame -> YOLO -> track -> visual attributes
    Det->>Srv: detection {event_id, detected_at, zone_id, track_id, confidence, visual, snapshot_path}
    Srv->>Res: resolve(detection)
    Res->>Srv: beacon candidates in same zone within time window
    Res->>DB: load candidate drones (airframe_type, model_family)
    Res->>Srv: identity {method, drone | none | ambiguous | mismatch}
    Srv->>DB: authorization lookup (drone, zone, detected_at)
    Srv->>DB: insert detection with decision
    Srv-->>Det: ack {decision, reason, drone, identity}
    Srv-->>Al: alert (if unauthorized or unidentified)
    Srv->>Out: queue row, batch append to Google Sheet (CSV on failure)
```

## Decision flow

```mermaid
flowchart TD
    E["Detection event received"] --> V{"Valid schema?"}
    V -- "no" --> ERR["Reply: error. Stop."]
    V -- "yes" --> I{"Identity resolution"}
    I -- "no identifier and no beacon" --> U1["UNIDENTIFIED: no Remote ID / identifier"]
    I -- "more than one candidate left" --> U2["UNIDENTIFIED: ambiguous"]
    I -- "visual attributes contradict claimed identity" --> U3["UNIDENTIFIED: identity/visual mismatch (possible spoofing)"]
    I -- "exactly one drone" --> R{"Serial registered in DB?"}
    R -- "no" --> U4["UNIDENTIFIED: not registered"]
    R -- "yes" --> S{"Status stolen or revoked?"}
    S -- "yes" --> N1["UNAUTHORIZED: drone status"]
    S -- "no" --> Z{"Zone is no-fly?"}
    Z -- "yes" --> N2["UNAUTHORIZED: no-fly zone"]
    Z -- "no" --> AU{"Active authorization for zone at detected_at?"}
    AU -- "yes" --> OK["AUTHORIZED"]
    AU -- "no" --> N3["UNAUTHORIZED: no active authorization"]
```

## Repo map (what runs where)

```
drone-detect-app/
  detector/src/detector/  YOLO wrapper (detect.py), airframe map (Stage B),
                          family classifier (attributes.py, Stage C, flagged),
                          tracking/dedupe, sources, events, ws_client, main CLI
  detector/tools/         evaluate.py (FP/min probe on images/ + videos/)
  detector/models/        *.pt weights (gitignored): drone.pt, family.pt
  server/cmd/server       wiring (config, Mongo, hub, worker, notifier, routes)
  server/internal/ws      /ws/detector, /ws/beacons, /ws/alerts + hub
  server/internal/identity  beacon buffer + resolver (explicit/beacon/visual)
  server/internal/authorization  decision engine (order in DESCRIPTION.md 5)
  server/internal/export  Sheets append + CSV fallback + retry worker
  server/internal/notify  console notifier (best-effort, never blocks)
  server/internal/api     GET / dashboard, GET /health, /snapshots static
  tools/                  seed_db.py, fake_detector.py, remote_id_sim.py
  docs/                   TRAINING.md (this milestone), ARCHITECTURE.md
```

## Failure behavior (stage table, condensed)

| Stage | On failure |
|---|---|
| Read / Detect | Skip frame, log; stop at end of source |
| Track + dedupe | Never emit without a `track_id` |
| Visual attributes | Omit `visual` (resolver skips the cross-check) |
| Event / send | Bounded queue, reconnect with backoff |
| Beacons | Reconnect; beacons are not persisted |
| Resolve / Decide | `unidentified`, logged, never a crash |
| Persist + reply | Reply `error`, keep the connection |
| Notify | Slow `/ws/alerts` clients evicted, never block |
| Export | Retry with backoff, CSV fallback, `export_status` tracked |
