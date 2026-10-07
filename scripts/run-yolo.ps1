<#
.SYNOPSIS
  Run the real YOLO detector against the running server. Leave it running.
.EXAMPLE
  .\scripts\run-yolo.ps1
  .\scripts\run-yolo.ps1 -Source ..\videos\test1.mp4
  .\scripts\run-yolo.ps1 -Source ..\images -Port 8080
#>
param(
  [string]$Source = "..\videos",
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$env:WS_URL = "ws://localhost:$Port/ws/detector"

# No fine-tuned drone.pt yet (M8 needs a labeled dataset): fall back to the
# pretrained stand-in so the live YOLO demo still runs.
if (-not (Test-Path "$Root\detector\models\drone.pt")) {
  Write-Output "no drone.pt - using pretrained stand-in (airplane class)"
  $env:YOLO_WEIGHTS = "yolo26n.pt"
  $env:YOLO_TARGET_CLASSES = "airplane"
  $env:YOLO_CONF = "0.1"
}

Set-Location "$Root\detector"
& "$Root\detector\.venv\Scripts\python.exe" -m detector.main --source $Source --clock video --display --max-fps 10
