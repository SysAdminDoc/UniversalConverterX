#requires -Version 5.1
# ChapterMark sidecar — PyInstaller freeze script.
# No third-party Python deps; just shells out to ffmpeg/ffprobe.

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
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

& $Python -m PyInstaller `
    --noconfirm --onefile --console `
    --name 'chaptermark' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
$exe = Join-Path $DistDir 'chaptermark.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }
Write-Host "[chaptermark] Built: $exe" -ForegroundColor Green
