#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('drives', 'image', 'burn')]
    [string]$Operation,

    [string]$SourcePath,
    [string]$OutputPath,
    [string]$VolumeLabel = 'UNIVERSAL_X',

    [ValidateSet('cd', 'dvd', 'bluray')]
    [string]$Media = 'dvd',

    [ValidateSet('data', 'dvd-video', 'bdmv')]
    [string]$Layout = 'data',

    [string]$RecorderId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-JsonResult {
    param([Parameter(Mandatory = $true)][object]$Value)
    $Value | ConvertTo-Json -Compress -Depth 5
}

function Assert-SafeSourceTree {
    param([Parameter(Mandatory = $true)][string]$Path)

    $root = Get-Item -LiteralPath $Path -ErrorAction Stop
    if (-not $root.PSIsContainer) {
        throw "Disc source must be a directory: $Path"
    }
    if ($root.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Disc source must not be a reparse point: $Path"
    }
    $link = Get-ChildItem -LiteralPath $root.FullName -Force -Recurse -ErrorAction Stop |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
        Select-Object -First 1
    if ($null -ne $link) {
        throw "Disc source contains a reparse point: $($link.FullName)"
    }
    return $root.FullName
}

function New-ImageResult {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$MediaKind,
        [Parameter(Mandatory = $true)][string]$LayoutKind
    )

    $source = Assert-SafeSourceTree -Path $Path
    $image = New-Object -ComObject IMAPI2FS.MsftFileSystemImage

    # IMAPI_MEDIA_TYPE: CD-R = 2, DVD-R = 9, BD-R = 13. Choosing media defaults before
    # adding the tree gives the image the correct capacity constraints.
    $mediaType = if ($MediaKind -eq 'cd') { 2 } elseif ($MediaKind -eq 'bluray') { 13 } else { 9 }
    $image.ChooseImageDefaultsForMediaType($mediaType)

    if ($LayoutKind -eq 'dvd-video') {
        # DVD-Video requires UDF 1.02. The authored source root contains the
        # VIDEO_TS directory produced by dvdauthor.
        $image.FileSystemsToCreate = 4
        $image.UDFRevision = 258
    } elseif ($LayoutKind -eq 'bdmv') {
        # Blu-ray BDMV uses a UDF 2.50 filesystem. The source root contains
        # the inspectable BDMV tree produced and validated by tsMuxeR.
        $image.FileSystemsToCreate = 4
        $image.UDFRevision = 592
    } elseif ($MediaKind -eq 'cd') {
        $image.FileSystemsToCreate = 3 # ISO9660 + Joliet
    } else {
        $image.FileSystemsToCreate = 7 # ISO9660 + Joliet + UDF
    }

    $image.VolumeName = $Label
    $image.Root.AddTree($source, $false)
    return $image.CreateResultImage()
}

if ($Operation -eq 'drives') {
    $master = New-Object -ComObject IMAPI2.MsftDiscMaster2
    $drives = @()
    for ($index = 0; $index -lt $master.Count; $index++) {
        $id = [string]$master.Item($index)
        $recorder = New-Object -ComObject IMAPI2.MsftDiscRecorder2
        $recorder.InitializeDiscRecorder($id)
        $drives += [ordered]@{
            id          = $id
            vendor      = [string]$recorder.VendorId
            product     = [string]$recorder.ProductId
            revision    = [string]$recorder.ProductRevision
            volumePaths = @($recorder.VolumePathNames)
            canLoad     = [bool]$recorder.CanLoadMedia
        }
    }
    Write-JsonResult ([ordered]@{
        supported = [bool]$master.IsSupportedEnvironment
        drives    = $drives
    })
    exit 0
}

if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    throw 'SourcePath is required for image and burn operations.'
}
if ($VolumeLabel -notmatch '^[A-Z0-9_]{1,32}$') {
    throw 'VolumeLabel must contain 1-32 uppercase letters, numbers, or underscores.'
}

$result = New-ImageResult -Path $SourcePath -Label $VolumeLabel -MediaKind $Media -LayoutKind $Layout

if ($Operation -eq 'image') {
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        throw 'OutputPath is required for image operations.'
    }

    if ($null -eq ('UniversalConverterX.ComStreamCopy' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace UniversalConverterX
{
    public static class ComStreamCopy
    {
        public static long ToFile(object value, string path)
        {
            var input = (IStream)value;
            var buffer = new byte[65536];
            var readPointer = Marshal.AllocCoTaskMem(sizeof(int));
            long total = 0;
            try
            {
                using (var output = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    while (true)
                    {
                        Marshal.WriteInt32(readPointer, 0);
                        input.Read(buffer, buffer.Length, readPointer);
                        var read = Marshal.ReadInt32(readPointer);
                        if (read <= 0) break;
                        output.Write(buffer, 0, read);
                        total += read;
                    }
                }
            }
            finally
            {
                Marshal.FreeCoTaskMem(readPointer);
            }
            return total;
        }
    }
}
'@
    }

    $fullOutput = [IO.Path]::GetFullPath($OutputPath)
    $outputDirectory = Split-Path -Parent $fullOutput
    if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    }
    $temporaryOutput = "$fullOutput.partial-$PID"
    try {
        $bytes = [UniversalConverterX.ComStreamCopy]::ToFile($result.ImageStream, $temporaryOutput)
        Move-Item -LiteralPath $temporaryOutput -Destination $fullOutput -Force
    } finally {
        if (Test-Path -LiteralPath $temporaryOutput) {
            Remove-Item -LiteralPath $temporaryOutput -Force
        }
    }
    Write-JsonResult ([ordered]@{ output = $fullOutput; sizeBytes = $bytes })
    exit 0
}

$master = New-Object -ComObject IMAPI2.MsftDiscMaster2
if (-not $master.IsSupportedEnvironment -or $master.Count -eq 0) {
    throw 'No IMAPI2-compatible optical recorder is available.'
}
$selectedId = if ([string]::IsNullOrWhiteSpace($RecorderId)) {
    [string]$master.Item(0)
} else {
    $RecorderId
}
$recorder = New-Object -ComObject IMAPI2.MsftDiscRecorder2
$recorder.InitializeDiscRecorder($selectedId)
$format = New-Object -ComObject IMAPI2.MsftDiscFormat2Data
$format.Recorder = $recorder
if (-not $format.IsRecorderSupported($recorder)) {
    throw 'The selected recorder does not support IMAPI2 data writes.'
}
if (-not $format.IsCurrentMediaSupported($recorder)) {
    throw 'The media in the selected recorder is not writable by IMAPI2.'
}
$format.ClientName = 'UniversalConverterX'
$format.ForceMediaToBeClosed = $true
$format.Write($result.ImageStream)
Write-JsonResult ([ordered]@{ recorderId = $selectedId; completed = $true })
