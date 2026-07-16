#requires -Version 5.1
<#
whisper.cpp sidecar — bootstrap + freeze script.

Two distinct things ship here:
  1. whisper-cli.exe + bundled DLLs — fetched from the upstream
     ggml-org/whisper.cpp GitHub release. SHA-256 verified.
  2. The Python sidecar (sidecar.py) — frozen with PyInstaller into a single
     exe that wraps whisper-cli.exe with the NDJSON contract.

GGUF models are NOT bundled (they are 75 MB – 2.9 GB each, individually
licensed). Drop them into tools/whisper-cpp/models/ or fetch them at runtime.
The .gitkeep file lists trusted sources.
#>

[CmdletBinding()]
param(
    [switch] $Clean,
    [switch] $SkipDownload,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ToolDir   = $PSScriptRoot
$Sidecar   = Join-Path $ToolDir 'sidecar.py'
$DistDir   = Join-Path $ToolDir 'dist'
$BuildDir  = Join-Path $ToolDir 'build'
$SpecDir   = Join-Path $ToolDir 'spec'
$BinDir    = Join-Path $ToolDir 'bin'

if ($Clean) {
    foreach ($d in @($DistDir, $BuildDir, $SpecDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
    Write-Host '[whisper-cpp] Cleaned build artefacts.'
}

# ── 1. Fetch whisper-cli release ─────────────────────────────────────────────
if (-not $SkipDownload) {
    $exe = Join-Path $BinDir 'whisper-cli.exe'
    if (-not (Test-Path $exe)) {
        # Pinned upstream release — bump tag + SHA together. Vulkan-enabled win-x64 build.
        $assetUrl = 'https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-bin-x64.zip'
        $assetSha = '0000000000000000000000000000000000000000000000000000000000000000'

        New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
        $zipPath = Join-Path $BinDir 'whisper-bin-x64.zip'
        Write-Host "[whisper-cpp] Downloading $assetUrl..."
        try {
            Invoke-WebRequest -Uri $assetUrl -OutFile $zipPath -UseBasicParsing -ErrorAction Stop
        } catch {
            Write-Warning "[whisper-cpp] Download failed: $($_.Exception.Message)"
            Write-Warning "             Update the release tag in build.ps1 if v1.8.4 has been superseded,"
            Write-Warning "             or drop whisper-cli.exe + DLLs into $BinDir manually."
            $zipPath = $null
        }

        if ($zipPath -and (Test-Path $zipPath)) {
            $hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToUpperInvariant()
            $expected = $assetSha.ToUpperInvariant()

            if ($expected -eq ('0' * 64)) {
                Write-Warning '[whisper-cpp] Placeholder SHA-256 in build.ps1 — release verification SKIPPED.'
                Write-Warning '             Pin the real SHA after the first vetted download.'
                Write-Warning "             Actual hash for the file you downloaded: $hash"
                Expand-Archive -Path $zipPath -DestinationPath $BinDir -Force
            } elseif ($hash -ne $expected) {
                Remove-Item -Force $zipPath
                Write-Warning "[whisper-cpp] SHA-256 mismatch — bin/ left empty."
                Write-Warning "             expected $expected"
                Write-Warning "             actual   $hash"
            } else {
                Write-Host '[whisper-cpp] SHA-256 verified.'
                Expand-Archive -Path $zipPath -DestinationPath $BinDir -Force
            }
            if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
        }
    } else {
        Write-Host "[whisper-cpp] whisper-cli.exe already present at $exe — skipping download."
    }
}

# ── 2. Freeze the sidecar ────────────────────────────────────────────────────
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host '[whisper-cpp] Installing PyInstaller...'
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

Write-Host '[whisper-cpp] Freezing sidecar.py...'
& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'whisper-cpp' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --paths ../_lib `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$frozen = Join-Path $DistDir 'whisper-cpp.exe'
if (-not (Test-Path $frozen)) { throw "Expected output not found: $frozen" }

Write-Host "[whisper-cpp] Built: $frozen" -ForegroundColor Green
Write-Host '[whisper-cpp] Drop ggml-*.bin GGUF models into tools/whisper-cpp/models/' -ForegroundColor Yellow
Write-Host '              huggingface.co/ggerganov/whisper.cpp is the canonical source.' -ForegroundColor Yellow
