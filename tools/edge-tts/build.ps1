#requires -Version 5.1
# edge-tts sidecar — PyInstaller freeze script

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
    Write-Host '[edge-tts] Cleaned previous build artefacts.'
}

Write-Host '[edge-tts] Ensuring runtime deps...'
& $Python -m pip install --quiet 'edge-tts>=7.2.0' pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Write-Host '[edge-tts] Freezing sidecar.py...'

& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'edge-tts' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --collect-all edge_tts `
    --hidden-import certifi `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'edge-tts.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[edge-tts] Built: $exe" -ForegroundColor Green
