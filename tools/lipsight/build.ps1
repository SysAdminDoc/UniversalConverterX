# LipSight UCX sidecar — PyInstaller freeze
#Requires -Version 5.1

param(
    [string]$Python = "python"
)

Set-Location $PSScriptRoot

Write-Host "LipSight sidecar build" -ForegroundColor Cyan

# Install runtime deps
& $Python -m pip install pyinstaller opencv-python requests numpy mediapipe -q

& $Python -m PyInstaller `
    --onefile `
    --name lipsight_sidecar `
    --distpath dist `
    --workpath build_tmp `
    --specpath build_tmp `
    --collect-all mediapipe `
    --hidden-import cv2 `
    --hidden-import requests `
    --hidden-import numpy `
    --noconfirm `
    sidecar.py

Remove-Item -Recurse -Force build_tmp -ErrorAction SilentlyContinue

if (Test-Path "dist\lipsight_sidecar.exe") {
    Write-Host "Built: dist\lipsight_sidecar.exe" -ForegroundColor Green
} else {
    Write-Error "Build failed — dist\lipsight_sidecar.exe not found"
    exit 1
}
