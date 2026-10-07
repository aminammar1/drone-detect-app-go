<#
.SYNOPSIS
  One-command demo shortcuts for the product-owner test (Windows PowerShell).

.DESCRIPTION
  Every task runs the repo's documented commands with one port used
  consistently by server, detector and simulator. Default port is 8000
  because a local Apache/XAMPP already answers on 8080 (the browser
  dashboard would hit Apache instead of our server). Pass -Port 8080 only
  if that Apache is stopped.

  Run from the repo root. Each task in its own terminal, in this order:

    .\scripts\demo.ps1 check            # mongo, port, ADC, sheet reminder
    .\scripts\demo.ps1 seed             # wipe + re-create mock data
    .\scripts\demo.ps1 server           # Go server (leave running)
    .\scripts\demo.ps1 sim              # preload Remote ID beacons
    .\scripts\demo.ps1 fake             # scripted detections, checks acks
    .\scripts\demo.ps1 dashboard        # open live page in browser
    .\scripts\demo.ps1 detect-video     # real YOLO on videos\ (leave running)
    .\scripts\demo.ps1 evaluate         # FP/min probe on videos\

  Before the Sheets step, open the spreadsheet and add a tab named exactly:
    detections
  (appends fail with 400 "Unable to parse range" until the tab exists).
#>

param(
  [Parameter(Position = 0)]
  [ValidateSet("check", "seed", "server", "sim", "fake", "dashboard",
    "detect-images", "detect-video", "evaluate", "test")]
  [string]$Task = "check",
  [int]$Port = 8000,
  [string]$Scenario = "scenarios\demo1.json"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Use-PortEnv {
  $env:SERVER_ADDR = ":$Port"
  $env:WS_URL = "ws://localhost:$Port/ws/detector"
  $env:BEACON_WS_URL = "ws://localhost:$Port/ws/beacons"
}

function Use-WeightsFallback {
  # No fine-tuned drone.pt yet (M8 needs a labeled dataset): fall back to the
  # pretrained stand-in so the live YOLO demo still runs. Remove this once
  # detector/models/drone.pt is trained (docs/TRAINING.md).
  if (-not (Test-Path "$Root\detector\models\drone.pt")) {
    Write-Output "no drone.pt - using pretrained stand-in (airplane class)"
    $env:YOLO_WEIGHTS = "yolo26n.pt"
    $env:YOLO_TARGET_CLASSES = "airplane"
    $env:YOLO_CONF = "0.1"
  }
}

switch ($Task) {
  "check" {
    Write-Output "== MongoDB =="
    mongosh --quiet --eval "db.runCommand({ping:1})"
    Write-Output "== Port $Port =="
    $busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($busy) { Write-Output "BUSY (PID $($busy.OwningProcess -join ',')) - pick another -Port" }
    else { Write-Output "free" }
    Write-Output "== Google ADC =="
    $adc = "$env:APPDATA\gcloud\application_default_credentials.json"
    if (Test-Path $adc) { Write-Output "present: $adc" } else { Write-Output "MISSING - Sheets will fail" }
    Write-Output "== Sheet tab =="
    Write-Output "open the spreadsheet and confirm a tab named exactly: detections"
  }
  "seed" {
    Set-Location $Root
    & "$Root\detector\.venv\Scripts\python.exe" tools\seed_db.py
  }
  "server" {
    Use-PortEnv
    Set-Location "$Root\server"
    go run .\cmd\server
  }
  "sim" {
    Use-PortEnv
    Set-Location $Root
    & "$Root\detector\.venv\Scripts\python.exe" tools\remote_id_sim.py --scenario $Scenario --mode preload
  }
  "fake" {
    Use-PortEnv
    Set-Location $Root
    & "$Root\detector\.venv\Scripts\python.exe" tools\fake_detector.py --scenario $Scenario
  }
  "dashboard" {
    Start-Process "http://localhost:$Port/"
  }
  "detect-images" {
    Use-PortEnv
    Use-WeightsFallback
    Set-Location "$Root\detector"
    & "$Root\detector\.venv\Scripts\python.exe" -m detector.main --source ..\images --clock video
  }
  "detect-video" {
    Use-PortEnv
    Use-WeightsFallback
    Set-Location "$Root\detector"
    & "$Root\detector\.venv\Scripts\python.exe" -m detector.main --source ..\videos --clock video --display --max-fps 10
  }
  "evaluate" {
    Set-Location "$Root\detector"
    & "$Root\detector\.venv\Scripts\python.exe" tools\evaluate.py --source ..\videos --weights yolo26n.pt --target-classes drone
  }
  "test" {
    Set-Location "$Root\server"
    go test ./...
    Set-Location "$Root\detector"
    & "$Root\detector\.venv\Scripts\python.exe" -m pytest -q
  }
}
