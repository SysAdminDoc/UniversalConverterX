#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the anime-upscale sidecar into a single-file Windows executable.
  Sidecar shells out to realesrgan-ncnn-vulkan.exe — download the release zip
  from github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases and unzip it next
  to this script (or under ../_bin/) so models/*.param and the binary are on
  disk before shipping.
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

& $python -m PyInstaller --name anime-upscale --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/anime-upscale.exe') (Join-Path $here 'anime-upscale.exe') -Force
$size = (Get-Item (Join-Path $here 'anime-upscale.exe')).Length / 1MB
Write-Host ("[done] anime-upscale.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here 'realesrgan-ncnn-vulkan.exe')) -and `
    -not (Test-Path (Join-Path $here '..\_bin\realesrgan-ncnn-vulkan.exe'))) {
    Write-Warning "[anime-upscale] No realesrgan-ncnn-vulkan.exe found next to the sidecar or under ../_bin/. Download from github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases before shipping (the zip includes the models/ folder)."
}
