#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Clean,
    [ValidateSet('cu126', 'cu130')]
    [string]$CudaChannel = 'cu130'
)

$ErrorActionPreference = 'Stop'
$ToolDir = $PSScriptRoot
$Venv = Join-Path $ToolDir '.venv'
$Dist = Join-Path $ToolDir 'dist'
$Build = Join-Path $ToolDir 'build'

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Venv, $Dist, $Build
}
if (-not (Test-Path $Venv)) { python -m venv $Venv }
$Python = Join-Path $Venv 'Scripts/python.exe'

& $Python -m pip install --quiet --upgrade pip pyinstaller
& $Python -m pip install --quiet `
    'torch==2.12.1' 'torchvision==0.27.1' `
    --index-url "https://download.pytorch.org/whl/$CudaChannel"
if ($LASTEXITCODE -ne 0) { throw 'Pinned PyTorch CUDA runtime install failed.' }
& $Python -m pip install --quiet -r (Join-Path $ToolDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'SeedVR2 runtime dependency install failed.' }

Push-Location $ToolDir
try {
    & $Python -m PyInstaller `
        --noconfirm --onefile --console --clean `
        --name 'seedvr2' `
        --distpath $Dist `
        --workpath $Build `
        --specpath $Build `
        --paths . --paths ../_lib `
        --collect-all torch `
        --collect-all torchvision `
        --collect-all diffusers `
        --collect-all peft `
        --collect-all safetensors `
        --collect-all omegaconf `
        --collect-all rotary_embedding_torch `
        --collect-all gguf `
        --hidden-import cv2 `
        sidecar.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$Exe = Join-Path $Dist 'seedvr2.exe'
if (-not (Test-Path $Exe)) { throw "Expected output not found: $Exe" }
Write-Host "[seedvr2] Built: $Exe" -ForegroundColor Green
Write-Host '[seedvr2] Weights and upstream runtime are excluded; the in-app download requires explicit Apache-2.0 consent.'
