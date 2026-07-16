#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the StreamKeep sidecar (yt-dlp-backed) into a single-file Windows executable.
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
& $python -m pip install --quiet --upgrade pip pyinstaller "yt-dlp[default]>=2026.07.04"

& $python -m PyInstaller --name streamkeep --onefile --console --noconfirm --clean --log-level WARN `
  --hidden-import yt_dlp `
  --collect-data yt_dlp `
  --collect-data yt_dlp_ejs `
  --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/streamkeep.exe') (Join-Path $here 'streamkeep.exe') -Force
$size = (Get-Item (Join-Path $here 'streamkeep.exe')).Length / 1MB
Write-Host ("[done] streamkeep.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
