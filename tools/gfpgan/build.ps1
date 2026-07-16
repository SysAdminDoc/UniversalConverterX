#requires -Version 5.1
# GFPGAN sidecar — PyInstaller freeze script.

[CmdletBinding()]
param(
    [switch] $Clean,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ToolDir  = $PSScriptRoot
$Sidecar  = Join-Path $ToolDir 'sidecar.py'
$DistDir  = Join-Path $ToolDir 'dist'
$BuildDir = Join-Path $ToolDir 'build'
$SpecDir  = Join-Path $ToolDir 'spec'

if ($Clean) {
    foreach ($d in @($DistDir, $BuildDir, $SpecDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
    Write-Host '[gfpgan] Cleaned previous build artefacts.'
}

Write-Host '[gfpgan] Installing runtime deps (gfpgan + torch + opencv-python)...'
& $Python -m pip install --quiet `
    'gfpgan>=1.3.8' 'basicsr>=1.4.2' 'facexlib>=0.3.0' `
    'torch>=2.0.0' 'torchvision>=0.15.0' `
    'opencv-python>=4.8.0' `
    pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Write-Host '[gfpgan] Freezing sidecar.py...'
& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'gfpgan' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --paths ../_lib `
    --collect-all gfpgan `
    --collect-all basicsr `
    --collect-all facexlib `
    --hidden-import cv2 `
    --hidden-import torch `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'gfpgan.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[gfpgan] Built: $exe" -ForegroundColor Green
Write-Host '[gfpgan] Drop GFPGANv1.4.pth into tools/gfpgan/models/ on first run.' -ForegroundColor Yellow
Write-Host '         Source: github.com/TencentARC/GFPGAN/releases (Apache 2.0)' -ForegroundColor Yellow
