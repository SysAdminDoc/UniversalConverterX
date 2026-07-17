param([string] $Python = "python")
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    & $Python -m PyInstaller --name chatterboxtts --onedir --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib --recursive-copy-metadata transformers --recursive-copy-metadata diffusers --collect-data perth sidecar.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
