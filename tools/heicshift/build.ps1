#requires -Version 5.1
# HEICShift sidecar — PyInstaller freeze script

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
    Write-Host '[heicshift] Cleaned previous build artefacts.'
}

# Bundle Pillow + pillow_heif into the freeze so the frozen sidecar can run
# without runtime pip install (frozen-guard short-circuits at runtime).
Write-Host '[heicshift] Ensuring runtime deps...'
& $Python -m pip install --quiet 'Pillow>=10.0.0' 'pillow-heif>=0.16.0' pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Write-Host '[heicshift] Freezing sidecar.py...'

& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'heicshift' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --collect-all pillow_heif `
    --hidden-import PIL.ImageCms `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'heicshift.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[heicshift] Built: $exe" -ForegroundColor Green
