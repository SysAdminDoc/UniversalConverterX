#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the AlphaCut sidecar into a single-file Windows executable.

.DESCRIPTION
  Produces tools/alphacut/alphacut.exe — invoked by UCX as a subprocess
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
& $python -m pip install --quiet -r (Join-Path $here 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed (exit $LASTEXITCODE)" }

Write-Host "[freeze] Building alphacut.exe" -ForegroundColor Cyan
& $python -m PyInstaller `
  --name alphacut `
  --onefile `
  --console `
  --noconfirm `
  --clean `
  --log-level WARN `
  --paths . --paths ../_lib `
  --hidden-import AlphaCut `
  sidecar.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$artifact = Join-Path $here 'dist/alphacut.exe'
if (-not (Test-Path $artifact)) { throw "Expected artifact missing: $artifact" }

Copy-Item $artifact (Join-Path $here 'alphacut.exe') -Force
$size = (Get-Item (Join-Path $here 'alphacut.exe')).Length / 1MB
Write-Host ("[done] alphacut.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
