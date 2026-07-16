#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the VideoSubtitleRemover sidecar into a single-file Windows executable.

.DESCRIPTION
  Produces tools/videosubtitleremover/videosubtitleremover.exe — invoked by UCX
  as a subprocess via SidecarRunner. The host expects NDJSON on stdout per the
  contract in tools/README.md.

.NOTES
  Runs in a per-tool venv to keep PyInstaller bloat off the system Python.
  Output exe is gitignored (.exe rule in parent .gitignore).
  Heavy AI deps (torch, paddle, onnxruntime) are included via --collect-all.
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

if (-not (Test-Path .venv)) {
  Write-Host "[venv] Creating .venv" -ForegroundColor Cyan
  python -m venv .venv
}

$python = Join-Path $here '.venv/Scripts/python.exe'
& $python -m pip install --quiet --upgrade pip pyinstaller
& $python -m pip install --quiet -r requirements.txt

Write-Host "[freeze] Building videosubtitleremover.exe" -ForegroundColor Cyan
& $python -m PyInstaller `
  --name videosubtitleremover `
  --onefile `
  --console `
  --noconfirm `
  --clean `
  --log-level WARN `
  --paths . --paths ../_lib `
  --paths backend `
  --collect-all rapidocr `
  --collect-all rapidocr_onnxruntime `
  --collect-all easyocr `
  --collect-all simple_lama_inpainting `
  --hidden-import cv2 `
  --hidden-import numpy `
  --hidden-import PIL `
  sidecar.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$artifact = Join-Path $here 'dist/videosubtitleremover.exe'
if (-not (Test-Path $artifact)) { throw "Expected artifact missing: $artifact" }

Copy-Item $artifact (Join-Path $here 'videosubtitleremover.exe') -Force
$size = (Get-Item (Join-Path $here 'videosubtitleremover.exe')).Length / 1MB
Write-Host ("[done] videosubtitleremover.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
