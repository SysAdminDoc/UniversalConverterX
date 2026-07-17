param([string] $Python = "python")
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    & $Python -m PyInstaller --name dia2tts --onedir --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib --paths vendor sidecar.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
