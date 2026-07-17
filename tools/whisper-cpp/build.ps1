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
    [switch] $AcceptLicense,
    [string] $Python = 'python'
)

$ErrorActionPreference = 'Stop'
$ToolDir   = $PSScriptRoot
$Sidecar   = Join-Path $ToolDir 'sidecar.py'
$DistDir   = Join-Path $ToolDir 'dist'
$BuildDir  = Join-Path $ToolDir 'build'
$SpecDir   = Join-Path $ToolDir 'spec'
$BinDir    = Join-Path $ToolDir 'bin'
$LibDir    = Join-Path $ToolDir '../_lib'

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
        # Pinned MIT-licensed upstream release. Update URL, size, and SHA together.
        $assetUrl = 'https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.4/whisper-bin-x64.zip'
        $assetSize = 4078768
        $assetSha = '74F973345CB52EF5BA3EC9E7E7AF8E48CC8C71722D1528603B80588A11F82E3E'

        if (-not $AcceptLicense) {
            Write-Warning '[whisper-cpp] Not downloading the MIT-licensed whisper.cpp runtime without -AcceptLicense.'
        } else {
            New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
            $stagingPath = Join-Path $BinDir '.whisper-bin-x64.zip.part'
            try {
                Write-Host "[whisper-cpp] Downloading pinned MIT asset $assetUrl..."
                Invoke-WebRequest -Uri $assetUrl -OutFile $stagingPath -UseBasicParsing -ErrorAction Stop
                $actualSize = (Get-Item -LiteralPath $stagingPath).Length
                $actualSha = (Get-FileHash -LiteralPath $stagingPath -Algorithm SHA256).Hash.ToUpperInvariant()
                if ($actualSize -ne $assetSize -or $actualSha -ne $assetSha) {
                    throw "Integrity mismatch (expected $assetSize bytes / $assetSha, got $actualSize bytes / $actualSha)."
                }
                Write-Host '[whisper-cpp] Size and SHA-256 verified.'
                Expand-Archive -LiteralPath $stagingPath -DestinationPath $BinDir -Force
            } finally {
                Remove-Item -LiteralPath $stagingPath -Force -ErrorAction SilentlyContinue
            }
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
    --paths $LibDir `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$frozen = Join-Path $DistDir 'whisper-cpp.exe'
if (-not (Test-Path $frozen)) { throw "Expected output not found: $frozen" }
Copy-Item -LiteralPath $frozen -Destination (Join-Path $ToolDir 'whisper-cpp.exe') -Force

Write-Host "[whisper-cpp] Built: $frozen" -ForegroundColor Green
Write-Host '[whisper-cpp] Drop ggml-*.bin GGUF models into tools/whisper-cpp/models/' -ForegroundColor Yellow
Write-Host '              huggingface.co/ggerganov/whisper.cpp is the canonical source.' -ForegroundColor Yellow
