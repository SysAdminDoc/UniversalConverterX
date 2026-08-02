[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StageRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$resolvedStage = (Resolve-Path -LiteralPath $StageRoot).Path.TrimEnd('\', '/')
$stageInfo = Get-Item -LiteralPath $resolvedStage
if (-not $stageInfo.PSIsContainer -or
    ($stageInfo.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "StageRoot must be a regular directory: $resolvedStage"
}

$files = @(
    Get-ChildItem -LiteralPath $resolvedStage -Recurse -File |
        Sort-Object FullName
)
if ($files.Count -eq 0) {
    throw "Cannot generate an MSI payload from an empty stage: $resolvedStage"
}

$reparsePoint = Get-ChildItem -LiteralPath $resolvedStage -Recurse -Force |
    Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
    Select-Object -First 1
if ($null -ne $reparsePoint) {
    throw "MSI payload cannot contain a reparse point: $($reparsePoint.FullName)"
}

function Get-StableWixId {
    param(
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value.ToLowerInvariant())
        $digest = $sha256.ComputeHash($bytes)
    } finally {
        $sha256.Dispose()
    }
    $hex = [Convert]::ToHexString($digest).Substring(0, 24)
    return "${Prefix}_$hex"
}

function Escape-Xml {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}

$fileRecords = @(
    foreach ($file in $files) {
        $relative = [IO.Path]::GetRelativePath(
            $resolvedStage,
            $file.FullName).Replace('\', '/')
        if ($relative.StartsWith('../') -or [IO.Path]::IsPathRooted($relative)) {
            throw "Staged file escapes StageRoot: $($file.FullName)"
        }
        [pscustomobject]@{
            File = $file
            Relative = $relative
            Directory = [IO.Path]::GetDirectoryName($relative).Replace('\', '/')
        }
    }
)

$directorySet = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase)
foreach ($record in $fileRecords) {
    $directory = $record.Directory
    while (-not [string]::IsNullOrWhiteSpace($directory)) {
        $directorySet.Add($directory) | Out-Null
        $directory = [IO.Path]::GetDirectoryName($directory).Replace('\', '/')
    }
}
$directories = @(
    $directorySet |
        Sort-Object @{ Expression = { ($_ -split '/').Count } }, @{ Expression = { $_ } }
)

$lines = [Collections.Generic.List[string]]::new()
$lines.Add('<?xml version="1.0" encoding="UTF-8"?>')
$lines.Add('<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">')

foreach ($directory in $directories) {
    $parent = [IO.Path]::GetDirectoryName($directory).Replace('\', '/')
    $parentId = if ([string]::IsNullOrWhiteSpace($parent)) {
        'INSTALLFOLDER'
    } else {
        Get-StableWixId -Prefix 'Dir' -Value $parent
    }
    $directoryId = Get-StableWixId -Prefix 'Dir' -Value $directory
    $name = [IO.Path]::GetFileName($directory)
    $lines.Add('  <Fragment>')
    $lines.Add("    <DirectoryRef Id=`"$(Escape-Xml $parentId)`">")
    $lines.Add("      <Directory Id=`"$(Escape-Xml $directoryId)`" Name=`"$(Escape-Xml $name)`" />")
    $lines.Add('    </DirectoryRef>')
    $lines.Add('  </Fragment>')
}

$lines.Add('  <Fragment>')
$lines.Add('    <ComponentGroup Id="ReleasePayload">')
foreach ($record in $fileRecords) {
    $directoryId = if ([string]::IsNullOrWhiteSpace($record.Directory)) {
        'INSTALLFOLDER'
    } else {
        Get-StableWixId -Prefix 'Dir' -Value $record.Directory
    }
    $componentId = Get-StableWixId -Prefix 'Cmp' -Value $record.Relative
    $fileId = Get-StableWixId -Prefix 'File' -Value $record.Relative
    $source = '$(var.PublishDir)' + $record.Relative.Replace('/', '\')
    $lines.Add("      <Component Id=`"$(Escape-Xml $componentId)`" Directory=`"$(Escape-Xml $directoryId)`" Guid=`"*`">")
    $lines.Add("        <File Id=`"$(Escape-Xml $fileId)`" Source=`"$(Escape-Xml $source)`" KeyPath=`"yes`" />")
    $lines.Add('      </Component>')
}
$lines.Add('    </ComponentGroup>')
$lines.Add('  </Fragment>')
$lines.Add('</Wix>')

$outputDirectory = Split-Path -Parent $OutputPath
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
$temporary = "$OutputPath.tmp"
Set-Content -LiteralPath $temporary -Value $lines -Encoding utf8
Move-Item -LiteralPath $temporary -Destination $OutputPath -Force

[pscustomobject]@{
    StageRoot = $resolvedStage
    OutputPath = [IO.Path]::GetFullPath($OutputPath)
    FileCount = $fileRecords.Count
    DirectoryCount = $directories.Count
}
