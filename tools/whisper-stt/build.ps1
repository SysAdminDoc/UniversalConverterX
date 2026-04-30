# Whisper STT Sidecar — PyInstaller freeze script

$ErrorActionPreference = "Stop"
$ToolDir  = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ToolDir "..\..") | Select-Object -ExpandProperty Path
$Sidecar  = Join-Path $ToolDir "sidecar.py"
$OutDir   = Join-Path $RepoRoot "src\UniversalConverterX.UI\Sidecars\whisper-stt"

Write-Host "Building whisper-stt sidecar..."

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
        $Sidecar

    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
    Write-Host "Build complete: $OutDir\ucx-whisper-stt.exe"
} finally {
    Pop-Location
}
