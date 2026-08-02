[CmdletBinding()]
param(
    [string]$PortablePath,

    [string]$MsiPath,

    [Parameter(Mandatory = $true)]
    [string]$SourceToolsRoot
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($PortablePath) -and
    [string]::IsNullOrWhiteSpace($MsiPath)) {
    throw 'Provide PortablePath, MsiPath, or both.'
}

$sourceTools = (Resolve-Path -LiteralPath $SourceToolsRoot).Path
$repoRoot = Split-Path -Parent $sourceTools
$readinessScript = Join-Path $repoRoot 'tools\release\sidecar_readiness.py'
$temporaryRoot = Join-Path (
    [IO.Path]::GetTempPath()) ("ucx-release-smoke-" + [Guid]::NewGuid().ToString('N'))

function Resolve-ReleaseRoot {
    param([Parameter(Mandatory = $true)][string]$ExtractionRoot)

    $manifests = @(
        Get-ChildItem -LiteralPath $ExtractionRoot -Recurse -File `
            -Filter 'sidecar-readiness.json'
    )
    if ($manifests.Count -ne 1) {
        throw "Expected one sidecar-readiness.json under $ExtractionRoot; found $($manifests.Count)."
    }
    return $manifests[0].Directory.FullName
}

function Test-ExtractedRelease {
    param(
        [Parameter(Mandatory = $true)][string]$ReleaseRoot,
        [Parameter(Mandatory = $true)][string]$Kind
    )

    $readinessOutput = @(
        & python $readinessScript verify `
            --stage-root $ReleaseRoot `
            --source-tools $sourceTools `
            --architecture win-x64 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Kind sidecar readiness verification failed: $($readinessOutput -join ' ')"
    }

    $ucx = Join-Path $ReleaseRoot 'cli\ucx.exe'
    $ffmpeg = Join-Path $ReleaseRoot 'tools\bin\ffmpeg.exe'
    $ffprobe = Join-Path $ReleaseRoot 'tools\bin\ffprobe.exe'
    foreach ($required in @($ucx, $ffmpeg, $ffprobe)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "$Kind payload is incomplete: $required"
        }
    }

    $versionOutput = @(& $ucx --version 2>&1)
    if ($LASTEXITCODE -ne 0 -or $versionOutput.Count -eq 0) {
        throw "$Kind CLI version smoke failed."
    }

    $fixtureRoot = Join-Path $temporaryRoot ("fixture-" + $Kind.ToLowerInvariant())
    $outputRoot = Join-Path $fixtureRoot 'output'
    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    $fixture = Join-Path $fixtureRoot 'fixture.wav'
    & $ffmpeg -hide_banner -loglevel error -y `
        -f lavfi -i 'sine=frequency=880:duration=0.25' `
        -c:a pcm_s16le $fixture
    if ($LASTEXITCODE -ne 0 -or
        -not (Test-Path -LiteralPath $fixture -PathType Leaf)) {
        throw "$Kind fixture generation failed."
    }

    $conversionOutput = @(
        & $ucx convert $fixture `
            -o mp3 `
            -d $outputRoot `
            --tools-path (Join-Path $ReleaseRoot 'tools') `
            --converter ffmpeg `
            --no-progress 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Kind packaged conversion smoke failed: $($conversionOutput -join ' ')"
    }

    $converted = Join-Path $outputRoot 'fixture.mp3'
    if (-not (Test-Path -LiteralPath $converted -PathType Leaf) -or
        (Get-Item -LiteralPath $converted).Length -eq 0) {
        throw "$Kind packaged conversion did not create fixture.mp3."
    }
    $duration = @(
        & $ffprobe -v error -show_entries format=duration `
            -of 'default=noprint_wrappers=1:nokey=1' $converted 2>&1
    )
    $parsedDuration = 0.0
    if ($LASTEXITCODE -ne 0 -or
        -not [double]::TryParse(
            ($duration | Select-Object -First 1),
            [Globalization.NumberStyles]::Float,
            [Globalization.CultureInfo]::InvariantCulture,
            [ref]$parsedDuration) -or
        $parsedDuration -le 0) {
        throw "$Kind converted fixture could not be probed."
    }

    [pscustomobject]@{
        Kind = $Kind
        Root = $ReleaseRoot
        CliVersion = ($versionOutput -join ' ').Trim()
        Fixture = $converted
    }
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
    $results = [Collections.Generic.List[object]]::new()

    if (-not [string]::IsNullOrWhiteSpace($PortablePath)) {
        $portable = (Resolve-Path -LiteralPath $PortablePath).Path
        $portableExtract = Join-Path $temporaryRoot 'portable'
        Expand-Archive -LiteralPath $portable -DestinationPath $portableExtract
        $root = Resolve-ReleaseRoot -ExtractionRoot $portableExtract
        $results.Add((Test-ExtractedRelease -ReleaseRoot $root -Kind 'Portable'))
    }

    if (-not [string]::IsNullOrWhiteSpace($MsiPath)) {
        $msi = (Resolve-Path -LiteralPath $MsiPath).Path
        $msiExtract = Join-Path $temporaryRoot 'msi'
        New-Item -ItemType Directory -Path $msiExtract -Force | Out-Null
        $quotedMsi = '"' + $msi.Replace('"', '""') + '"'
        $quotedTarget = '"' + $msiExtract.Replace('"', '""') + '"'
        $process = Start-Process -FilePath 'msiexec.exe' `
            -ArgumentList "/a $quotedMsi /qn TARGETDIR=$quotedTarget" `
            -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -notin @(0, 3010)) {
            throw "MSI administrative extraction failed with exit code $($process.ExitCode)."
        }
        $root = Resolve-ReleaseRoot -ExtractionRoot $msiExtract
        $results.Add((Test-ExtractedRelease -ReleaseRoot $root -Kind 'MSI'))
    }

    $results
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
        $expectedPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $resolvedTemporary.StartsWith(
                $expectedPrefix,
                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean unexpected smoke path: $resolvedTemporary"
        }
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
