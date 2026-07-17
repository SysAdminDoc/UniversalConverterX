#requires -Version 7.0
<#
.SYNOPSIS
    Reproduce the optional GPL Comskip V0.83 Windows runtime from pinned inputs.

.DESCRIPTION
    This is a developer/release recipe, never an application-time downloader.
    It follows upstream's AppVeyor MSYS2/MinGW build, verifies every byte before
    extraction, and retains the exact source archive beside any runtime bundle.
#>

[CmdletBinding()]
param(
    [switch]$AcceptGpl,
    [switch]$PrepareOnly,
    [string]$WorkDirectory = (Join-Path $PSScriptRoot 'runtime-build')
)

$ErrorActionPreference = 'Stop'
if (-not $AcceptGpl) {
    throw 'Comskip is GPL-2.0-only and its FFmpeg build is GPL-3.0-or-later. Rerun with -AcceptGpl after reviewing runtime-manifest.json.'
}

$manifest = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'runtime-manifest.json') | ConvertFrom-Json
$work = [System.IO.Path]::GetFullPath($WorkDirectory)
$downloads = Join-Path $work 'downloads'
$sourceRoot = Join-Path $work 'source'
$bundle = Join-Path $work 'bundle'
New-Item -ItemType Directory -Path $downloads, $sourceRoot, $bundle -Force | Out-Null

$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromMinutes(10)
try {
    foreach ($input in $manifest.buildInputs) {
        $name = [System.IO.Path]::GetFileName(([Uri]$input.url).AbsolutePath)
        if ($input.name -eq 'Comskip source') { $name = 'comskip-source.tar.gz' }
        $destination = Join-Path $downloads $name
        $valid = $false
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            $file = Get-Item -LiteralPath $destination
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
            $valid = $file.Length -eq [long]$input.size -and $hash -eq $input.sha256
        }
        if (-not $valid) {
            $temporary = "$destination.download"
            $bytes = $client.GetByteArrayAsync([Uri]$input.url).GetAwaiter().GetResult()
            [System.IO.File]::WriteAllBytes($temporary, $bytes)
            $file = Get-Item -LiteralPath $temporary
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
            if ($file.Length -ne [long]$input.size -or $hash -ne $input.sha256) {
                Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
                throw "Integrity check failed for $($input.name)."
            }
            Move-Item -LiteralPath $temporary -Destination $destination -Force
        }
        Write-Host "[verified] $($input.name) $($input.sha256)"
    }
}
finally {
    $client.Dispose()
}

$sourceArchive = Join-Path $downloads 'comskip-source.tar.gz'
$ffmpegArchive = Join-Path $downloads 'ffmpeg-5.0.1-full_build-shared.7z'
$argtableArchive = Join-Path $downloads 'argtable2-13.tar.gz'
tar -xf $sourceArchive -C $sourceRoot
if ($LASTEXITCODE -ne 0) { throw 'Comskip source extraction failed.' }
$comskipSource = Get-ChildItem -LiteralPath $sourceRoot -Directory -Filter 'Comskip-*' | Select-Object -First 1
if ($null -eq $comskipSource) { throw 'Comskip source directory not found after extraction.' }
& 'C:\Program Files\7-Zip\7z.exe' x $ffmpegArchive "-o$($comskipSource.FullName)" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg extraction failed.' }
tar -xf $argtableArchive -C $comskipSource.FullName
if ($LASTEXITCODE -ne 0) { throw 'argtable2 extraction failed.' }

Copy-Item -LiteralPath $sourceArchive -Destination (Join-Path $bundle 'comskip-source.tar.gz') -Force
Copy-Item -LiteralPath (Join-Path $comskipSource.FullName 'LICENSE') -Destination (Join-Path $bundle 'COMSKIP-LICENSE') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime-manifest.json') -Destination $bundle -Force
if ($PrepareOnly) {
    Write-Host "Prepared and verified build inputs at $work"
    exit 0
}

$bash = 'C:\msys64\usr\bin\bash.exe'
if (-not (Test-Path -LiteralPath $bash)) { throw 'MSYS2 bash is required at C:\msys64\usr\bin\bash.exe.' }
$sourceFull = [System.IO.Path]::GetFullPath($comskipSource.FullName)
if ($sourceFull.Length -lt 3 -or $sourceFull[1] -ne ':') {
    throw "Expected an absolute Windows drive path for the MSYS2 build: $sourceFull"
}
$sourceUnix = '/' + $sourceFull[0].ToString().ToLowerInvariant() + $sourceFull.Substring(2).Replace('\', '/')
$toolchainCheck = & $bash -lc 'export PATH=/ucrt64/bin:/usr/bin:$PATH; command -v gcc && command -v make && command -v autoconf && command -v automake && command -v libtool'
if ($LASTEXITCODE -ne 0) {
    throw 'MSYS2 UCRT64 gcc, make, autoconf, automake, and libtool are required. Install them explicitly with pacman before building.'
}

$buildCommand = @"
set -euo pipefail
export PATH=/ucrt64/bin:/usr/bin:`$PATH
cd '$sourceUnix'
cd argtable2-13
./configure --build=x86_64-w64-mingw32
make -j2
cd ..
./autogen.sh
argtable2_CFLAGS='-Iargtable2-13/src' \
argtable2_LIBS='-Largtable2-13/src/.libs -largtable2' \
ffmpeg_CFLAGS='-Iffmpeg-5.0.1-full_build-shared/include' \
ffmpeg_LIBS='-Lffmpeg-5.0.1-full_build-shared/lib -lavutil -lavformat -lavcodec -lswscale' \
./configure
make -j2
"@
& $bash -lc $buildCommand
if ($LASTEXITCODE -ne 0) { throw 'Comskip build failed.' }

Copy-Item -LiteralPath (Join-Path $comskipSource.FullName 'comskip.exe') -Destination $bundle -Force
Get-ChildItem -LiteralPath (Join-Path $comskipSource.FullName 'ffmpeg-5.0.1-full_build-shared\bin') -Filter '*.dll' |
    Copy-Item -Destination $bundle -Force

$env:PATH = "$bundle;$env:PATH"
& (Join-Path $bundle 'comskip.exe') --help *> (Join-Path $bundle 'comskip-help.txt')
if ($LASTEXITCODE -notin 0, 1) { throw 'Built Comskip executable did not start.' }
Write-Host "Reproducible Comskip runtime ready at $bundle"
