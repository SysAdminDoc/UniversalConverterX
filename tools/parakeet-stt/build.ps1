#requires -Version 5.1
[CmdletBinding()]
param([switch]$Clean)

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
& $Python -m pip install --quiet -r (Join-Path $ToolDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Parakeet runtime dependency install failed.' }

Push-Location $ToolDir
try {
    & $Python -m PyInstaller `
        --noconfirm --onefile --console --clean `
        --name 'parakeet-stt' `
        --distpath $Dist `
        --workpath $Build `
        --specpath $Build `
        --paths . --paths ../_lib `
        --collect-all transformers `
        --collect-all torch `
        --collect-all safetensors `
        --hidden-import huggingface_hub `
        sidecar.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$Exe = Join-Path $Dist 'parakeet-stt.exe'
if (-not (Test-Path $Exe)) { throw "Expected output not found: $Exe" }
Write-Host "[parakeet-stt] Built: $Exe" -ForegroundColor Green
Write-Host '[parakeet-stt] Model weights are intentionally excluded; download requires explicit in-app consent.'
