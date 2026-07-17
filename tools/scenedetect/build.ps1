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
& $python -m pip install --quiet 'scenedetect[opencv]==0.6.7.1' opencv-python-headless
# PyAV powers the NVDEC hardware-decode path in tools/_lib/hw_decode.py (Item 98).
# Optional at runtime — motion measurement degrades to OpenCV software decode when
# PyAV or a CUDA device is absent — but bundling it lets a rebuilt sidecar offload
# decode to the GPU on long-form HD/4K.
& $python -m pip install --quiet 'av>=17.0.0'

& $python -m PyInstaller `
    --name scenedetect `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all scenedetect `
    --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/scenedetect.exe') (Join-Path $here 'scenedetect.exe') -Force
$size = (Get-Item (Join-Path $here 'scenedetect.exe')).Length / 1MB
Write-Host ("[done] scenedetect.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
