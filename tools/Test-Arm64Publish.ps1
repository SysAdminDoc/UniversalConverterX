<#
.SYNOPSIS
    Verifies UCX ARM64 publish apphosts and records sidecar architecture policy.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$PublishRoot,

    [Parameter(Mandatory = $true)]
    [string]$SourceToolsRoot,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Get-PeMachine {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    try {
        $reader = [System.IO.BinaryReader]::new($stream)
        if ($reader.ReadUInt16() -ne 0x5A4D) { return 'not-pe' }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or $peOffset -gt ($stream.Length - 6)) { return 'invalid-pe' }
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) { return 'invalid-pe' }
        $machine = $reader.ReadUInt16()
        if ($machine -eq 0xAA64) { return 'arm64' }
        if ($machine -eq 0x8664) { return 'x64' }
        if ($machine -eq 0x014C) { return 'x86-or-anycpu' }
        return ('0x{0:X4}' -f $machine)
    }
    finally {
        $stream.Dispose()
    }
}

$publishRootFull = [System.IO.Path]::GetFullPath($PublishRoot)
$toolsRootFull = [System.IO.Path]::GetFullPath($SourceToolsRoot)
$outputFull = [System.IO.Path]::GetFullPath($OutputPath)

$required = @(
    'cli\ucx.exe',
    'ui\UniversalConverterX.exe',
    'shell\UniversalConverterX.ShellExtension.comhost.dll',
    'tools\ffmpeg-proxy\ffmpeg.exe'
)

$artifacts = foreach ($relative in $required) {
    $path = Join-Path $publishRootFull $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        [pscustomobject]@{ path = $relative; machine = 'missing'; valid = $false }
        continue
    }
    $machine = Get-PeMachine -Path $path
    [pscustomobject]@{ path = $relative; machine = $machine; valid = $machine -eq 'arm64' }
}

$sidecars = foreach ($engineDirectory in Get-ChildItem -LiteralPath $toolsRootFull -Directory) {
    foreach ($executable in Get-ChildItem -LiteralPath $engineDirectory.FullName -Filter '*.exe' -File) {
        [pscustomobject]@{
            engine = $engineDirectory.Name
            file = $executable.Name
            machine = Get-PeMachine -Path $executable.FullName
            arm64Policy = 'native'
        }
    }
}
foreach ($sidecar in $sidecars) {
    if ($sidecar.machine -ne 'arm64') {
        $sidecar.arm64Policy = 'requires-windows-x64-emulation-or-arm64-rebuild'
    }
}

$report = [ordered]@{
    schemaVersion = 1
    runtimeIdentifier = 'win-arm64'
    generatedAtUtc = [DateTime]::UtcNow.ToString('O')
    artifacts = @($artifacts)
    artifactsValid = -not (@($artifacts | Where-Object { -not $_.valid }).Count)
    sidecarExecutables = @($sidecars | Sort-Object engine, file)
    sidecarSummary = [ordered]@{
        total = @($sidecars).Count
        nativeArm64 = @($sidecars | Where-Object machine -eq 'arm64').Count
        emulationOrRebuild = @($sidecars | Where-Object machine -ne 'arm64').Count
    }
    policy = 'Managed UCX apphosts are ARM64-native. Non-ARM64 sidecars remain disabled unless Windows x64 emulation can launch them; QNN workloads additionally require an ARM64 Python runtime and QNNExecutionProvider. No architecture is inferred from a filename.'
}

$outputDirectory = Split-Path -Parent $outputFull
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outputFull -Encoding utf8

if (-not $report.artifactsValid) {
    $bad = $artifacts | Where-Object { -not $_.valid } | ForEach-Object { "$($_.path)=$($_.machine)" }
    Write-Error ("ARM64 publish artifact audit failed: " + ($bad -join ', '))
    exit 1
}

Write-Host ("ARM64 publish audit passed: {0} primary apphosts; {1} sidecar executable(s) require emulation or rebuild." -f $artifacts.Count, $report.sidecarSummary.emulationOrRebuild)
