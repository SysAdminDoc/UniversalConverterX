#requires -Version 5.1
param([switch]$Clean)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    if ($Clean) {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv, *.spec
    }
    if (-not (Test-Path .venv)) { python -m venv .venv }
    $python = Join-Path $here '.venv\Scripts\python.exe'
    & $python -m pip install --quiet --upgrade pip pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }

    & $python -m PyInstaller --name comskip-sidecar --onefile --console --noconfirm --clean `
        --log-level WARN --paths . --paths ..\_lib `
        --add-data 'comskip.ini;.' --add-data 'runtime-manifest.json;.' sidecar.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    Copy-Item (Join-Path $here 'dist\comskip-sidecar.exe') `
        (Join-Path $here 'comskip-sidecar.exe') -Force
    Write-Host '[done] comskip-sidecar.exe'
}
finally {
    Pop-Location
}
