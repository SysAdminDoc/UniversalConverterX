#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the ClipForge sidecar into a single-file Windows executable.
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
& $python -m pip install --quiet -r requirements.txt

& $python -m PyInstaller --name clipforge --onefile --console --noconfirm --clean --log-level WARN --paths . --hidden-import cv2 --collect-data cv2 sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/clipforge.exe') (Join-Path $here 'clipforge.exe') -Force
$size = (Get-Item (Join-Path $here 'clipforge.exe')).Length / 1MB
Write-Host ("[done] clipforge.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
