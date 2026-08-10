# Whisper STT Sidecar — PyInstaller freeze script

$ErrorActionPreference = "Stop"
$ToolDir  = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ToolDir "..\..") | Select-Object -ExpandProperty Path
$Sidecar  = Join-Path $ToolDir "sidecar.py"
$OutDir   = Join-Path $RepoRoot "src\UniversalConverterX.UI\Sidecars\whisper-stt"

Write-Host "Building whisper-stt sidecar..."

if (Test-Path (Join-Path $ToolDir "requirements.txt")) {
    Write-Host "Provisioning declared whisper-stt dependencies..."
    & python -m pip install --quiet -r (Join-Path $ToolDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "whisper-stt dependency installation failed (exit $LASTEXITCODE)" }
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing PyInstaller..."
    & python -m pip install pyinstaller --quiet
}

Push-Location $ToolDir
try {
    pyinstaller `
        --noconfirm `
        --onefile `
        --console `
        --name "ucx-whisper-stt" `
        --distpath $OutDir `
        --workpath (Join-Path $ToolDir "build") `
        --specpath (Join-Path $ToolDir "spec") `
        --paths (Join-Path $ToolDir "../_lib") `
        --collect-submodules "pyannote.audio" `
        --collect-data "pyannote.audio" `
        $Sidecar

    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
    Write-Host "Build complete: $OutDir\ucx-whisper-stt.exe"
} finally {
    Pop-Location
}
