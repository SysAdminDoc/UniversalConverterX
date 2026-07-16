#requires -Version 5.1
# GifStudio sidecar — PyInstaller freeze script

[CmdletBinding()]
param(
    [switch] $Clean,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ToolDir  = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ToolDir '..\..')).Path
$Sidecar  = Join-Path $ToolDir 'sidecar.py'
$DistDir  = Join-Path $ToolDir 'dist'
$BuildDir = Join-Path $ToolDir 'build'
$SpecDir  = Join-Path $ToolDir 'spec'

if ($Clean) {
    foreach ($d in @($DistDir, $BuildDir, $SpecDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
    Write-Host '[gifstudio] Cleaned previous build artefacts.'
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host '[gifstudio] Installing PyInstaller...'
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

Write-Host '[gifstudio] Freezing sidecar.py...'

& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'gifstudio' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --paths ../_lib `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'gifstudio.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[gifstudio] Built: $exe" -ForegroundColor Green
