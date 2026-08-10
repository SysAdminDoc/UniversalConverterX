# UCX Demucs Sidecar Build Script
# Freezes sidecar.py into a portable .exe using PyInstaller.
#
# Prerequisites: Python 3.10+, PyInstaller (auto-installed below)
#
# Usage:
#   .\build.ps1                        # Build to dist\demucs\
#   .\build.ps1 -Clean                 # Remove build artifacts first
#   .\build.ps1 -PythonPath "C:\Python312\python.exe"

param(
    [switch]$Clean,
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$DistDir   = Join-Path $ScriptDir "dist\demucs"
$SpecFile  = Join-Path $ScriptDir "sidecar.spec"

if ($Clean -and (Test-Path $ScriptDir\build)) {
    Remove-Item -Recurse -Force "$ScriptDir\build"
    Remove-Item -Recurse -Force "$ScriptDir\dist"
    Remove-Item -Force $SpecFile -ErrorAction SilentlyContinue
    Write-Host "[clean] Removed build artifacts."
}

# Ensure PyInstaller
& $PythonPath -m pip install pyinstaller --quiet
if ($LASTEXITCODE -ne 0) { throw "PyInstaller install failed." }

Write-Host "[build] Freezing sidecar.py..."

& $PythonPath -m PyInstaller `
    --onefile `
    --paths (Join-Path $ScriptDir "../_lib") `
    --name "demucs-sidecar" `
    --distpath $DistDir `
    --workpath "$ScriptDir\build" `
    --specpath $ScriptDir `
    --noconfirm `
    "$ScriptDir\sidecar.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$ExePath = Join-Path $DistDir "demucs-sidecar.exe"
if (-not (Test-Path $ExePath)) {
    throw "Expected output not found: $ExePath"
}

$SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
Write-Host "[build] Done. $ExePath ($SizeMB MB)"
