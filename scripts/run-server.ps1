<#
.SYNOPSIS
  Run the Go server (Gin). Leave this terminal running.
.EXAMPLE
  .\scripts\run-server.ps1
  .\scripts\run-server.ps1 -Port 8080
#>
param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Default port is 8000 because a local Apache/XAMPP already answers on 8080.
$env:SERVER_ADDR = ":$Port"

Set-Location "$Root\server"
go run .\cmd\server
