#requires -Version 5.1
<# Reproduce the static libavif 1.4.2 gain-map utility published for UCX. #>
[CmdletBinding()]
param(
  [string]$WorkDirectory = (Join-Path $env:TEMP 'ucx-gainmap-runtime'),
  [string]$OutputArchive = (Join-Path $PWD 'UniversalConverterX-gainmap-runtime-v1.4.2-win-x64.zip')
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $WorkDirectory 'libavif'
$build = Join-Path $source 'build-ucx'
$stage = Join-Path $WorkDirectory ("stage-" + [guid]::NewGuid().ToString('N'))

if (-not (Test-Path $source)) {
  git clone --filter=blob:none https://github.com/AOMediaCodec/libavif.git $source
}
git -C $source fetch --tags origin
git -C $source checkout --detach c5240fc79fe5c2407e10afd35f5505ef6333ea49

cmake -S $source -B $build -G 'Visual Studio 17 2022' -A x64 `
  -DBUILD_SHARED_LIBS=OFF -DAOM_TARGET_CPU=generic `
  -DAVIF_CODEC_AOM=LOCAL -DAVIF_LIBYUV=LOCAL -DAVIF_LIBSHARPYUV=LOCAL `
  -DAVIF_JPEG=LOCAL -DAVIF_ZLIBPNG=LOCAL -DAVIF_LIBXML2=LOCAL `
  -DAVIF_BUILD_APPS=ON -DAVIF_BUILD_TESTS=OFF
if ($LASTEXITCODE -ne 0) { throw 'libavif configure failed' }
cmake --build $build --config Release --parallel 8
if ($LASTEXITCODE -ne 0) { throw 'libavif build failed' }

New-Item -ItemType Directory -Force (Join-Path $stage 'licenses') | Out-Null
Copy-Item (Join-Path $build 'Release/avifgainmaputil.exe') $stage -Force
$licenses = @{
  'libavif-LICENSE.txt' = (Join-Path $source 'LICENSE')
  'libaom-LICENSE.txt' = (Join-Path $build '_deps/libaom-src/LICENSE')
  'libargparse-LICENSE.md' = (Join-Path $build '_deps/libargparse-src/LICENSE.md')
  'libpng-LICENSE.txt' = (Join-Path $build '_deps/libpng-src/LICENSE')
  'libwebp-COPYING.txt' = (Join-Path $build '_deps/libwebp-src/COPYING')
  'libxml2-Copyright.txt' = (Join-Path $build '_deps/libxml2-src/Copyright')
  'libyuv-LICENSE.txt' = (Join-Path $build '_deps/libyuv-src/LICENSE')
  'zlib-LICENSE.txt' = (Join-Path $build '_deps/zlib-src/LICENSE')
  'libjpeg-turbo-LICENSE.md' = (Join-Path $build 'libjpeg/src/libjpeg/LICENSE.md')
}
foreach ($entry in $licenses.GetEnumerator()) {
  Copy-Item $entry.Value (Join-Path $stage "licenses/$($entry.Key)") -Force
}

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $OutputArchive -CompressionLevel Optimal -Force
$archive = Get-Item $OutputArchive
$hash = Get-FileHash $OutputArchive -Algorithm SHA256
Write-Host "Archive: $($archive.FullName)"
Write-Host "Bytes: $($archive.Length)"
Write-Host "SHA256: $($hash.Hash)"
