[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,

    [Parameter(Mandatory = $true)]
    [string]$DestinationPath,

    [string]$ArchivePath
)

$ErrorActionPreference = 'Stop'

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne 1 -or $manifest.tool -ne 'ffmpeg') {
    throw "Unsupported FFmpeg bundle manifest: $ManifestPath"
}

$platform = $manifest.platforms.'windows-x64'
if ($null -eq $platform -or $platform.archiveType -ne 'zip') {
    throw 'The FFmpeg bundle manifest must define a windows-x64 ZIP archive.'
}
if ($platform.url -notmatch '^https://') {
    throw 'The pinned FFmpeg download URL must use HTTPS.'
}
if ($platform.sha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'The pinned FFmpeg archive must have a valid SHA-256 checksum.'
}

$tempDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ucx-ffmpeg-stage-" + [Guid]::NewGuid().ToString('N'))
$downloadedArchive = $false
try {
    New-Item -ItemType Directory -Path $tempDirectory -Force | Out-Null
    if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
        $ArchivePath = Join-Path $tempDirectory 'ffmpeg.zip'
        Invoke-WebRequest -Uri $platform.url -OutFile $ArchivePath -UseBasicParsing
        $downloadedArchive = $true
    }

    $resolvedArchive = (Resolve-Path -LiteralPath $ArchivePath).Path
    $actualChecksum = (Get-FileHash -LiteralPath $resolvedArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualChecksum -ne $platform.sha256.ToLowerInvariant()) {
        throw "FFmpeg archive checksum mismatch. Expected $($platform.sha256), got $actualChecksum."
    }

    $extractDirectory = Join-Path $tempDirectory 'extract'
    Expand-Archive -LiteralPath $resolvedArchive -DestinationPath $extractDirectory -Force
    New-Item -ItemType Directory -Path $DestinationPath -Force | Out-Null

    foreach ($baseName in $manifest.files) {
        $fileName = "$baseName.exe"
        $matches = @(Get-ChildItem -LiteralPath $extractDirectory -Recurse -File -Filter $fileName)
        if ($matches.Count -ne 1) {
            throw "Pinned FFmpeg archive must contain exactly one $fileName; found $($matches.Count)."
        }
        Copy-Item -LiteralPath $matches[0].FullName -Destination (Join-Path $DestinationPath $fileName) -Force
    }

    $metadataDirectory = Join-Path (Split-Path -Parent $DestinationPath) 'ffmpeg'
    New-Item -ItemType Directory -Path $metadataDirectory -Force | Out-Null
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $metadataDirectory 'bundle.json') -Force
    Set-Content -LiteralPath (Join-Path $metadataDirectory 'ffmpeg.version') -Value $manifest.version -Encoding ascii -NoNewline

    [pscustomobject]@{
        Tool = $manifest.tool
        Version = $manifest.version
        Build = $manifest.build
        Destination = (Resolve-Path -LiteralPath $DestinationPath).Path
        Downloaded = $downloadedArchive
    }
}
finally {
    if (Test-Path -LiteralPath $tempDirectory) {
        Remove-Item -LiteralPath $tempDirectory -Recurse -Force
    }
}
