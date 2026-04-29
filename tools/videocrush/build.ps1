#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the VideoCrush sidecar into a single-file Windows executable.

.DESCRIPTION
  Produces tools/videocrush/videocrush.exe — invoked by UCX as a subprocess
  via SidecarRunner. The host expects NDJSON on stdout per the contract in
  tools/README.md.

.NOTES
  Runs in a per-tool venv to keep PyInstaller bloat off the system Python.
  Output exe is gitignored (.exe rule in parent .gitignore).
#>
[CmdletBinding()]
param(
  [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if ($Clean) {
  Write-Host "[clean] Removing build artifacts" -ForegroundColor Yellow
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv, *.spec
}

# Per-tool venv to isolate PyInstaller / its deps from system Python.
if (-not (Test-Path .venv)) {
  Write-Host "[venv] Creating .venv" -ForegroundColor Cyan
  python -m venv .venv
}

$python = Join-Path $here '.venv/Scripts/python.exe'
& $python -m pip install --quiet --upgrade pip pyinstaller

Write-Host "[freeze] Building videocrush.exe" -ForegroundColor Cyan
& $python -m PyInstaller `
  --name videocrush `
  --onefile `
  --console `
  --noconfirm `
  --clean `
  --log-level WARN `
  --paths . `
  sidecar.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$artifact = Join-Path $here 'dist/videocrush.exe'
if (-not (Test-Path $artifact)) { throw "Expected artifact missing: $artifact" }

Copy-Item $artifact (Join-Path $here 'videocrush.exe') -Force
$size = (Get-Item (Join-Path $here 'videocrush.exe')).Length / 1MB
Write-Host ("[done] videocrush.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
