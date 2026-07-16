#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the video-face-enhance sidecar into a single-file Windows executable.
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

& $python -m PyInstaller --name video-face-enhance --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/video-face-enhance.exe') (Join-Path $here 'video-face-enhance.exe') -Force
$size = (Get-Item (Join-Path $here 'video-face-enhance.exe')).Length / 1MB
Write-Host ("[done] video-face-enhance.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here '..\facerestore\facerestore.exe'))) {
    Write-Warning "[video-face-enhance] facerestore.exe was not found under ../facerestore/. Build tools/facerestore before shipping this preset."
}
