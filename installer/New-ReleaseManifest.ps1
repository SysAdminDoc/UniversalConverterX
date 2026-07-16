#requires -Version 5.1
<#
.SYNOPSIS
    Writes the machine-readable metadata published with a UCX release.

.DESCRIPTION
    Hashes the exact installer artifacts after signing and inventories bundled
    executables/scripts without launching them. The manifest is written
    atomically so release automation cannot publish a partial JSON document.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string[]]$ArtifactPath,

    [Parameter(Mandatory = $true)]
    [string]$BundleRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$RuntimeIdentifier = 'win-x64'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Sha256Lower {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BundleRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $rootPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Bundled tool path escapes bundle root: $fullPath"
    }
    return $fullPath.Substring($rootPrefix.Length).Replace('\', '/')
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    throw 'Version must not be empty.'
}
if (-not (Test-Path -LiteralPath $BundleRoot -PathType Container)) {
    throw "Bundle root does not exist: $BundleRoot"
}

$artifactEntries = @(
    foreach ($candidate in ($ArtifactPath | Sort-Object -Unique)) {
        $item = Get-Item -LiteralPath $candidate -ErrorAction Stop
        if (-not $item.PSIsContainer -and $item.Length -gt 0) {
            [PSCustomObject][ordered]@{
                fileName  = $item.Name
                type      = $item.Extension.TrimStart('.').ToLowerInvariant()
                sizeBytes = $item.Length
                sha256    = Get-Sha256Lower -Path $item.FullName
            }
        } else {
            throw "Release artifact must be a non-empty regular file: $candidate"
        }
    }
)
if ($artifactEntries.Count -eq 0) {
    throw 'At least one release artifact is required.'
}

$toolExtensions = @('.exe', '.com', '.cmd', '.bat', '.ps1', '.py', '.jar')
$seenToolPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$toolEntries = New-Object System.Collections.Generic.List[object]
foreach ($relativeRoot in @('tools', 'Sidecars')) {
    $toolRoot = Join-Path $BundleRoot $relativeRoot
    if (-not (Test-Path -LiteralPath $toolRoot -PathType Container)) {
        continue
    }

    Get-ChildItem -LiteralPath $toolRoot -File -Recurse |
        Where-Object {
            $toolExtensions -contains $_.Extension.ToLowerInvariant() -and
            -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        } |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = Get-BundleRelativePath -Root $BundleRoot -Path $_.FullName
            if (-not $seenToolPaths.Add($relativePath)) {
                return
            }

            $versionValue = $null
            if ($_.Extension.Equals('.exe', [StringComparison]::OrdinalIgnoreCase)) {
                try {
                    $versionInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName)
                    if (-not [string]::IsNullOrWhiteSpace($versionInfo.ProductVersion)) {
                        $versionValue = $versionInfo.ProductVersion
                    } elseif (-not [string]::IsNullOrWhiteSpace($versionInfo.FileVersion)) {
                        $versionValue = $versionInfo.FileVersion
                    }
                } catch {
                    # Version metadata is optional. Hashing the payload is not.
                }
            }

            $kind = if ($relativePath.StartsWith('Sidecars/', [StringComparison]::OrdinalIgnoreCase)) {
                'sidecar'
            } else {
                'tool'
            }
            $toolEntries.Add([PSCustomObject][ordered]@{
                name      = $_.BaseName
                kind      = $kind
                path      = $relativePath
                version   = $versionValue
                sizeBytes = $_.Length
                sha256    = Get-Sha256Lower -Path $_.FullName
            }) | Out-Null
        }
}

$manifest = [ordered]@{
    schemaVersion     = 1
    product           = 'UniversalConverterX'
    version           = $Version
    runtimeIdentifier = $RuntimeIdentifier
    generatedAtUtc    = [DateTimeOffset]::UtcNow.ToString('o')
    artifacts         = $artifactEntries
    bundledTools      = $toolEntries.ToArray()
}

$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $outputFullPath
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$tempPath = "$outputFullPath.tmp-$PID"
$utf8NoBom = New-Object Text.UTF8Encoding($false)
try {
    $json = $manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($tempPath, $json + [Environment]::NewLine, $utf8NoBom)
    Move-Item -LiteralPath $tempPath -Destination $outputFullPath -Force
} finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force
    }
}

Write-Output $outputFullPath
