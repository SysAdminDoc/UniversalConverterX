#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the subtitle-sync sidecar into a single-file Windows executable.
  The sidecar shells out to subsync or ffsubsync; install via pip.
#>
[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if ($Clean) {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv, *.spec
}
if (-not (Test-Path .venv)) { python -m venv .venv }
$python = Join-Path $here '.venv/Scripts/python.exe'
& $python -m pip install --quiet --upgrade pip pyinstaller

& $python -m PyInstaller --name subtitle-sync --onefile --console --noconfirm --clean --log-level WARN --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/subtitle-sync.exe') (Join-Path $here 'subtitle-sync.exe') -Force
$size = (Get-Item (Join-Path $here 'subtitle-sync.exe')).Length / 1MB
Write-Host ("[done] subtitle-sync.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
