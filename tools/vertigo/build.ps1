#requires -Version 5.1
# Vertigo Auto-Reframe sidecar — PyInstaller freeze script.
#
# Static-mode operation requires only FFmpeg on PATH at runtime.
# Smart-mode operation additionally needs OpenCV (cv2) + MediaPipe; if those
# aren't bundled, the sidecar falls back to static at runtime with a warning.

[CmdletBinding()]
param(
    [switch] $Clean,
    [switch] $NoSmart,   # skip cv2 + mediapipe in the freeze (smaller exe)
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
    Write-Host '[vertigo] Cleaned previous build artefacts.'
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host '[vertigo] Installing PyInstaller...'
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

$pyiArgs = @(
    '--noconfirm', '--onefile', '--console',
    '--name', 'vertigo',
    '--distpath', $DistDir,
    '--workpath', $BuildDir,
    '--specpath', $SpecDir,
    '--paths', '../_lib'
)

if (-not $NoSmart) {
    Write-Host '[vertigo] Installing smart-mode runtime deps (opencv-python + mediapipe)...'
    & $Python -m pip install --quiet 'opencv-python>=4.8.0' 'mediapipe>=0.10.0'
    if ($LASTEXITCODE -ne 0) {
        Write-Warning '[vertigo] cv2/mediapipe install failed — building static-only sidecar.'
    } else {
        $pyiArgs += @('--collect-all', 'mediapipe', '--hidden-import', 'cv2')
    }
}

$pyiArgs += $Sidecar

Write-Host '[vertigo] Freezing sidecar.py...'
& $Python -m PyInstaller @pyiArgs

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'vertigo.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[vertigo] Built: $exe" -ForegroundColor Green
