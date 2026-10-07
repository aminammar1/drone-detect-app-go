<#
.SYNOPSIS
  Run the real YOLO detector against the running server. Leave it running.
.EXAMPLE
  .\scripts\run-yolo.ps1
  .\scripts\run-yolo.ps1 -Source ..\videos\test1.mp4
  .\scripts\run-yolo.ps1 -Video "my clip.mp4"
  .\scripts\run-yolo.ps1 -Image "shot.png" -Port 8000
  .\scripts\run-yolo.ps1 -Pick
  .\scripts\run-yolo.ps1 -Pick -Image shot.png
  .\scripts\run-yolo.ps1 -ListSources
#>
param(
  [string]$Source = "",
  [string]$Video = "",
  [string]$Image = "",
  [switch]$Pick,
  [switch]$ListSources,
  [float]$Conf = -1,
  [int]$Imgsz = -1,
  [int]$Stride = -1,
  [int]$MinFrames = -1,
  [float]$MaxFps = 10,
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$env:WS_URL = "ws://localhost:$Port/ws/detector"

# No fine-tuned drone.pt yet (needs a labeled dataset, see docs/TRAINING.md):
# fall back to the pretrained stand-in so the live YOLO demo still runs.
if (-not (Test-Path "$Root\detector\models\drone.pt")) {
  Write-Output "no drone.pt - using pretrained stand-in (airplane class)"
  $env:YOLO_WEIGHTS = "yolo26n.pt"
  $env:YOLO_TARGET_CLASSES = "airplane"
  $env:YOLO_CONF = "0.1"
}

# Precedence: -Source > -Video > -Image > default.
# Bare file names are searched inside videos/ and images/ by the detector.
# -Pick with no explicit source lists BOTH folders (media) so images appear.
$Target = "..\videos"
$ImagesOnly = $false
if ($Source -ne "") { $Target = $Source }
elseif ($Video -ne "") { $Target = $Video }
elseif ($Image -ne "") { $Target = $Image; $ImagesOnly = $true }
elseif ($Pick -or $ListSources) { $Target = "media" }

$Extra = @()
if ($Pick) { $Extra += "--pick" }
if ($ListSources) { $Extra += "--list-sources" }
if ($Conf -ge 0) { $Extra += "--conf"; $Extra += "$Conf" }
if ($Imgsz -gt 0) { $Extra += "--imgsz"; $Extra += "$Imgsz" }
if ($Stride -gt 0) { $Extra += "--stride"; $Extra += "$Stride" }
if ($MinFrames -gt 0) { $Extra += "--min-frames"; $Extra += "$MinFrames" }

Set-Location "$Root\detector"
if ($ImagesOnly) {
  & "$Root\detector\.venv\Scripts\python.exe" -m detector.main --source $Target --clock video @Extra
} else {
  & "$Root\detector\.venv\Scripts\python.exe" -m detector.main --source $Target --clock video --display --max-fps $MaxFps @Extra
}
