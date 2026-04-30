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
# pillow-jxl-plugin is opt-in: succeed even if it fails to install (some
# environments lack libjxl prebuilt wheels). The sidecar degrades gracefully.
& $Python -m pip install --quiet 'Pillow>=10.0.0' 'pillow-heif>=0.16.0' pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

& $Python -m pip install --quiet 'pillow-jxl-plugin>=1.3.0' 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning '[heicshift] pillow-jxl-plugin install failed — frozen sidecar will refuse JXL with a helpful error.'
}

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
    --collect-all pillow_jxl `
    --hidden-import PIL.ImageCms `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'heicshift.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[heicshift] Built: $exe" -ForegroundColor Green
