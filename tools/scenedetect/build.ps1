#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the SceneDetect sidecar (PySceneDetect 0.6.x) into a single-file Windows exe.
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
& $python -m pip install --quiet 'scenedetect[opencv]>=0.6.7,<0.7' opencv-python-headless

& $python -m PyInstaller `
    --name scenedetect `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all scenedetect `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/scenedetect.exe') (Join-Path $here 'scenedetect.exe') -Force
$size = (Get-Item (Join-Path $here 'scenedetect.exe')).Length / 1MB
Write-Host ("[done] scenedetect.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
