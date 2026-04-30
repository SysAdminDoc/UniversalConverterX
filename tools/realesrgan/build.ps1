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
    Write-Host '[realesrgan] Cleaned build artefacts (kept bin/ — pass -SkipDownload off to refetch).'
}

# ── 1. Fetch ncnn-vulkan + models ────────────────────────────────────────────
if (-not $SkipDownload) {
    $exe = Join-Path $BinDir 'realesrgan-ncnn-vulkan.exe'
    if (-not (Test-Path $exe)) {
        # Vetted upstream Windows release. Asset URL pinned to release tag, not 'latest',
        # so we don't drift unexpectedly. Update both URL + SHA-256 together.
        $assetUrl = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'
        $assetSha = 'EFC4E78E36D4F26F9486B8FB5B6BC0E3D7F5024F3F6E3E827DE8D03D6BA8DC1B'

        New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
        $zipPath = Join-Path $BinDir 'realesrgan-ncnn-vulkan.zip'
        Write-Host "[realesrgan] Downloading $assetUrl..."
        Invoke-WebRequest -Uri $assetUrl -OutFile $zipPath -UseBasicParsing

        $hash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($hash -ne $assetSha.ToUpperInvariant()) {
            Remove-Item -Force $zipPath
            Write-Warning "[realesrgan] SHA-256 mismatch for $assetUrl"
            Write-Warning "             expected $assetSha"
            Write-Warning "             actual   $hash"
            Write-Warning "             — bin/ left empty. The sidecar will refuse to run until a verified copy is dropped in."
        } else {
            Write-Host '[realesrgan] SHA-256 verified.'
            Expand-Archive -Path $zipPath -DestinationPath $BinDir -Force
            Remove-Item -Force $zipPath

            # The upstream zip extracts as realesrgan-ncnn-vulkan-<date>-windows/.
            # Flatten it into bin/ so the sidecar's REALESRGAN_EXE search hits it.
            $extracted = Get-ChildItem -Directory -Path $BinDir | Where-Object { $_.Name -like 'realesrgan-ncnn-vulkan-*-windows' } | Select-Object -First 1
            if ($extracted) {
                Get-ChildItem -Path $extracted.FullName | Move-Item -Destination $BinDir -Force
                Remove-Item -Recurse -Force $extracted.FullName
            }
            Write-Host "[realesrgan] Installed at: $exe"
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
    $Sidecar

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$frozen = Join-Path $DistDir 'realesrgan.exe'
if (-not (Test-Path $frozen)) { throw "Expected output not found: $frozen" }

Write-Host "[realesrgan] Built: $frozen" -ForegroundColor Green
