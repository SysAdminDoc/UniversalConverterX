#requires -Version 5.1
<#
Real-ESRGAN sidecar — bootstrap + freeze script.

Two distinct things ship here:
  1. realesrgan-ncnn-vulkan.exe + bundled models — downloaded from the upstream
     xinntao/Real-ESRGAN GitHub release. SHA-256 verified.
  2. The Python sidecar (sidecar.py) — frozen with PyInstaller into a single
     exe that wraps ncnn-vulkan with the NDJSON contract.

The frozen sidecar locates the ncnn-vulkan exe via:
  REALESRGAN_EXE env → tools/realesrgan/bin/realesrgan-ncnn-vulkan.exe → PATH
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
    Write-Host '[realesrgan] Cleaned build artefacts (kept bin/ — pass -SkipDownload off to refetch).'
}

# ── 1. Fetch ncnn-vulkan + models ────────────────────────────────────────────
if (-not $SkipDownload) {
    $exe = Join-Path $BinDir 'realesrgan-ncnn-vulkan.exe'
    if (-not (Test-Path $exe)) {
        # Pinned BSD-3-Clause upstream release. Update URL, size, and SHA together.
        $assetUrl = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'
        $assetSize = 45474481
        $assetSha = 'ABC02804E17982A3BE33675E4D471E91EA374E65B70167ABC09E31ACB412802D'

        if (-not $AcceptLicense) {
            Write-Warning '[realesrgan] Not downloading the BSD-3-Clause runtime without -AcceptLicense.'
        } else {
            New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
            $stagingPath = Join-Path $BinDir '.realesrgan-ncnn-vulkan.zip.part'
            try {
                Write-Host "[realesrgan] Downloading pinned BSD-3-Clause asset $assetUrl..."
                Invoke-WebRequest -Uri $assetUrl -OutFile $stagingPath -UseBasicParsing -ErrorAction Stop
                $actualSize = (Get-Item -LiteralPath $stagingPath).Length
                $actualSha = (Get-FileHash -LiteralPath $stagingPath -Algorithm SHA256).Hash.ToUpperInvariant()
                if ($actualSize -ne $assetSize -or $actualSha -ne $assetSha) {
                    throw "Integrity mismatch (expected $assetSize bytes / $assetSha, got $actualSize bytes / $actualSha)."
                }
                Write-Host '[realesrgan] Size and SHA-256 verified.'
                Expand-Archive -LiteralPath $stagingPath -DestinationPath $BinDir -Force

                # The upstream zip extracts as realesrgan-ncnn-vulkan-<date>-windows/.
                # Flatten it into bin/ so the sidecar's REALESRGAN_EXE search hits it.
                $extracted = Get-ChildItem -Directory -Path $BinDir | Where-Object { $_.Name -like 'realesrgan-ncnn-vulkan-*-windows' } | Select-Object -First 1
                if ($extracted) {
                    Get-ChildItem -Path $extracted.FullName | Move-Item -Destination $BinDir -Force
                    Remove-Item -Recurse -Force $extracted.FullName
                }
                Write-Host "[realesrgan] Installed at: $exe"
            } finally {
                Remove-Item -LiteralPath $stagingPath -Force -ErrorAction SilentlyContinue
            }
        }
    } else {
        Write-Host "[realesrgan] ncnn-vulkan exe already present at $exe — skipping download. Pass -Clean -SkipDownload:`$false to refetch."
    }
} else {
    Write-Host '[realesrgan] -SkipDownload set; not fetching upstream binary.'
}

# ── 2. Freeze the sidecar ────────────────────────────────────────────────────
if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host '[realesrgan] Installing PyInstaller...'
    & $Python -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed.' }
}

Write-Host '[realesrgan] Freezing sidecar.py...'
& $Python -m PyInstaller `
    --noconfirm `
    --onefile `
    --console `
    --name 'realesrgan' `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir `
    --paths $LibDir `
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$frozen = Join-Path $DistDir 'realesrgan.exe'
if (-not (Test-Path $frozen)) { throw "Expected output not found: $frozen" }
Copy-Item -LiteralPath $frozen -Destination (Join-Path $ToolDir 'realesrgan.exe') -Force

Write-Host "[realesrgan] Built: $frozen" -ForegroundColor Green
