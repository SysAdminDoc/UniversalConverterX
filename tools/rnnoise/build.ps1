#requires -Version 5.1
# RNNoise sidecar — PyInstaller freeze script.
#
# Pure-FFmpeg sidecar (no Python ML deps), so no runtime pip install. Bundles
# the discovered tools/rnnoise/models/ subtree into the freeze so the frozen
# exe ships any user-supplied model files alongside.

[CmdletBinding()]
param(
    [switch] $Clean,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ToolDir   = $PSScriptRoot
$Sidecar   = Join-Path $ToolDir 'sidecar.py'
$DistDir   = Join-Path $ToolDir 'dist'
$BuildDir  = Join-Path $ToolDir 'build'
$SpecDir   = Join-Path $ToolDir 'spec'
$ModelsDir = Join-Path $ToolDir 'models'

if ($Clean) {
    foreach ($d in @($DistDir, $BuildDir, $SpecDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
    Write-Host '[rnnoise] Cleaned previous build artefacts.'
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host '[rnnoise] Installing PyInstaller...'
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

Write-Host '[rnnoise] Freezing sidecar.py...'

$pyiArgs = @(
    '--noconfirm', '--onefile', '--console',
    '--name', 'rnnoise',
    '--distpath', $DistDir,
    '--workpath', $BuildDir,
    '--specpath', $SpecDir,
    '--paths', '../_lib'
)

# Ship any models the user has placed under tools/rnnoise/models/ alongside
# the frozen exe so the sidecar discovers them at runtime via _models_dir_local().
if (Test-Path $ModelsDir) {
    $pyiArgs += @('--add-data', "$ModelsDir;models")
}

$pyiArgs += $Sidecar

& $Python -m PyInstaller @pyiArgs

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$exe = Join-Path $DistDir 'rnnoise.exe'
if (-not (Test-Path $exe)) { throw "Expected output not found: $exe" }

Write-Host "[rnnoise] Built: $exe" -ForegroundColor Green
Write-Host '[rnnoise] Note: drop a .rnnn model under tools/rnnoise/models/ before first run.' -ForegroundColor Yellow
Write-Host '          cb.rnnn from github.com/GregorR/rnnoise-models is a good general default.' -ForegroundColor Yellow
