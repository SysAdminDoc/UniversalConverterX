#requires -Version 5.1
[CmdletBinding()]
param([switch] $Clean)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$venv = Join-Path $here '.venv'
if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $venv, (Join-Path $here 'dist'), (Join-Path $here 'build'), (Join-Path $here 'spec')
}
if (-not (Test-Path $venv)) { py -3.12 -m venv $venv }
$python = Join-Path $venv 'Scripts/python.exe'
& $python -m pip install --quiet --upgrade pip pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller setup failed.' }
& $python -m pip install --quiet -r (Join-Path $here 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'VideoTag runtime dependency install failed.' }
& $python -m PyInstaller --name videotag --onefile --console --noconfirm --clean --log-level WARN `
    --distpath (Join-Path $here 'dist') --workpath (Join-Path $here 'build') --specpath (Join-Path $here 'spec') `
    --paths (Join-Path $here '../_lib') --collect-all ai_edge_litert --collect-all cv2 `
    (Join-Path $here 'sidecar.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
Copy-Item -LiteralPath (Join-Path $here 'dist/videotag.exe') -Destination (Join-Path $here 'videotag.exe') -Force
Write-Host '[done] videotag.exe' -ForegroundColor Green
