[CmdletBinding()]
param(
    [switch]$AcceptApacheLicense,
    [string]$Destination = (Join-Path $PSScriptRoot '..\_bin'),
    [string]$WorkDirectory,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $AcceptApacheLicense) {
    throw 'tsMuxeR 2.7.0 is Apache-2.0 licensed. Re-run with -AcceptApacheLicense after reviewing tsmuxer-runtime.json.'
}

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tsmuxer-runtime.json') -Raw |
    ConvertFrom-Json
$ownedWorkDirectory = [string]::IsNullOrWhiteSpace($WorkDirectory)
if ($ownedWorkDirectory) {
    $WorkDirectory = Join-Path ([IO.Path]::GetTempPath()) ("ucx-tsmuxer-{0}" -f [guid]::NewGuid().ToString('N'))
}
$work = [IO.Path]::GetFullPath($WorkDirectory)
$destinationRoot = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $work | Out-Null
New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null

function Get-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][object]$Entry,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $client = [Net.Http.HttpClient]::new()
    try {
        $bytes = $client.GetByteArrayAsync([string]$Entry.url).GetAwaiter().GetResult()
        [IO.File]::WriteAllBytes($Path, $bytes)
    } finally {
        $client.Dispose()
    }
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -ne [long]$Entry.size) {
        throw "Size mismatch for $Path. Expected $($Entry.size), got $($file.Length)."
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$Entry.sha256).ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. Expected $($Entry.sha256), got $actual."
    }
}

try {
    $archive = Join-Path $work 'tsMuxer-2.7.0-win64.zip'
    $license = Join-Path $work 'LICENSE-tsMuxeR.txt'
    $extract = Join-Path $work 'extract'
    Get-VerifiedFile -Entry $manifest.archive -Path $archive
    Get-VerifiedFile -Entry $manifest.licenseFile -Path $license
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $binary = Join-Path $extract 'tsMuxeR.exe'
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        throw 'Verified archive did not contain tsMuxeR.exe at its expected path.'
    }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $binary
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $banner = $process.StandardOutput.ReadToEnd() + $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($banner -notmatch 'tsMuxeR version 2\.7\.0') {
        throw 'Verified executable did not report tsMuxeR version 2.7.0.'
    }

    $targetBinary = Join-Path $destinationRoot 'tsMuxeR.exe'
    $targetLicense = Join-Path $destinationRoot 'LICENSE-tsMuxeR.txt'
    if (-not $Force -and ((Test-Path -LiteralPath $targetBinary) -or (Test-Path -LiteralPath $targetLicense))) {
        throw "Destination already contains a tsMuxeR runtime. Re-run with -Force to replace it: $destinationRoot"
    }
    $temporaryBinary = Join-Path $destinationRoot (".tsMuxeR.{0}.exe" -f $PID)
    $temporaryLicense = Join-Path $destinationRoot (".LICENSE-tsMuxeR.{0}.txt" -f $PID)
    Copy-Item -LiteralPath $binary -Destination $temporaryBinary
    Copy-Item -LiteralPath $license -Destination $temporaryLicense
    Move-Item -LiteralPath $temporaryBinary -Destination $targetBinary -Force
    Move-Item -LiteralPath $temporaryLicense -Destination $targetLicense -Force
    [ordered]@{
        runtime = [string]$manifest.runtime
        executable = $targetBinary
        license = $targetLicense
        sha256 = (Get-FileHash -LiteralPath $targetBinary -Algorithm SHA256).Hash.ToLowerInvariant()
    } | ConvertTo-Json
} finally {
    if ($ownedWorkDirectory -and (Test-Path -LiteralPath $work)) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
