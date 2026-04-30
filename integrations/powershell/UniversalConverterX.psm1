#requires -Version 5.1
<#
.SYNOPSIS
    UniversalConverterX PowerShell module -- typed cmdlets that wrap the `ucx`
    CLI plus the sidecar binaries for sysadmin batch workflows.

.DESCRIPTION
    Each public cmdlet shells out to a UCX-shipped exe (ucx.exe / a sidecar
    under tools/<name>/) and translates parameters into the underlying CLI
    flags. Output is structured PSObjects where it makes sense; raw JSON
    NDJSON is parsed and surfaced as objects.

    Resolution order for the UCX install root:
      1. $env:UCX_HOME -- explicit override
      2. The directory containing the running PowerShell module
      3. C:\Program Files\UniversalConverterX
      4. %LocalAppData%\UniversalConverterX

    Run `Get-UcxRoot` to inspect the resolved root, or `Test-Ucx` to verify
    the install before scripting.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'


# ── UCX install discovery ───────────────────────────────────────────────────

function Get-UcxRoot {
    <#
    .SYNOPSIS
        Resolve the UCX install root.
    .OUTPUTS
        [string] Absolute path to the UCX install directory, or $null if not found.
    #>
    if ($env:UCX_HOME -and (Test-Path $env:UCX_HOME)) { return (Resolve-Path $env:UCX_HOME).Path }

    $modDir = $PSScriptRoot
    if ($modDir) {
        # Module sits under <repo>/integrations/powershell -- walk up two levels.
        $candidate = Resolve-Path (Join-Path $modDir '..\..') -ErrorAction SilentlyContinue
        if ($candidate -and (Test-Path (Join-Path $candidate 'src'))) { return $candidate.Path }
    }

    foreach ($p in @(
        'C:\Program Files\UniversalConverterX',
        (Join-Path $env:LOCALAPPDATA 'UniversalConverterX')
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}


function Get-UcxExe {
    <#
    .SYNOPSIS
        Return the absolute path to the bundled `ucx.exe` CLI.
    #>
    $root = Get-UcxRoot
    if (-not $root) { throw "UCX install root not found. Set `$env:UCX_HOME or install UCX." }

    foreach ($p in @(
        (Join-Path $root 'ucx.exe'),
        (Join-Path $root 'src\UniversalConverterX.Console\bin\x64\Release\net10.0\ucx.exe'),
        (Join-Path $root 'src\UniversalConverterX.Console\bin\x64\Debug\net10.0\ucx.exe')
    )) {
        if (Test-Path $p) { return $p }
    }
    throw "ucx.exe not found under $root. Build the Console project or install a release bundle."
}


function Get-UcxSidecar {
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string] $Name)
    $root = Get-UcxRoot
    if (-not $root) { throw 'UCX install root not found.' }
    foreach ($p in @(
        (Join-Path $root "tools\$Name\dist\$Name.exe"),
        (Join-Path $root "tools\$Name\$Name.exe"),
        (Join-Path $root "tools\$Name\bin\$Name.exe")
    )) {
        if (Test-Path $p) { return $p }
    }
    throw "Sidecar '$Name' not built. Run `pwsh tools/$Name/build.ps1` from the repo."
}


function Test-Ucx {
    <#
    .SYNOPSIS
        Verify UCX install root + cmdlets reach the bundled binaries.
    #>
    [CmdletBinding()] param()
    $root = Get-UcxRoot
    if (-not $root) {
        Write-Warning 'UCX install root not found.'
        return $false
    }
    Write-Host "UCX root: $root"
    try   { $cli = Get-UcxExe; Write-Host "  ucx.exe: $cli" } catch { Write-Warning $_ }
    foreach ($s in @('videocrush','clipforge','heicshift','gifstudio','recordcast')) {
        try   { Write-Host "  $($s): $(Get-UcxSidecar -Name $s)" } catch { Write-Warning "  $($s): not built" }
    }
    return $true
}


# ── Helpers ──────────────────────────────────────────────────────────────────

function Invoke-UcxNdjson {
    <#
    .SYNOPSIS
        Run a sidecar exe with given args, parse NDJSON events, surface as
        PSObjects via the pipeline. Translates `progress` events to
        Write-Progress and `log`/`error` to console streams.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Exe,
        [Parameter()] [string[]] $ArgsList = @(),
        [Parameter()] [string]   $Activity = 'UCX'
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $Exe
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true
    foreach ($a in $ArgsList) { $psi.ArgumentList.Add($a) | Out-Null }

    $proc = [System.Diagnostics.Process]::Start($psi)
    while (-not $proc.StandardOutput.EndOfStream) {
        $line = $proc.StandardOutput.ReadLine()
        if (-not $line) { continue }
        try {
            $ev = $line | ConvertFrom-Json -ErrorAction Stop
        } catch {
            Write-Verbose "non-JSON: $line"
            continue
        }
        switch ($ev.event) {
            'progress' {
                $stage = if ($ev.PSObject.Properties['stage']) { $ev.stage } else { '' }
                Write-Progress -Activity $Activity -Status $stage -PercentComplete ([int]$ev.percent)
            }
            'log'      {
                if ($ev.level -eq 'error')      { Write-Warning $ev.message }
                elseif ($ev.level -eq 'warn')   { Write-Warning $ev.message }
                else                            { Write-Verbose $ev.message }
            }
            'error'    {
                Write-Error "UCX error [$($ev.code)]: $($ev.message)"
            }
            default    { $ev }   # surface other events to the pipeline
        }
    }
    $proc.WaitForExit()
    Write-Progress -Activity $Activity -Completed
    if ($proc.ExitCode -ne 0) {
        $stderr = $proc.StandardError.ReadToEnd()
        if ($stderr) { Write-Warning $stderr }
        throw "$([System.IO.Path]::GetFileName($Exe)) exited with code $($proc.ExitCode)."
    }
}


# ── Convert-MediaFile ────────────────────────────────────────────────────────

function Convert-MediaFile {
    <#
    .SYNOPSIS
        Convert one or more media files to a target format using the UCX CLI.

    .EXAMPLE
        Convert-MediaFile -Path .\source.mov -OutputFormat mp4

    .EXAMPLE
        Get-ChildItem *.mov | Convert-MediaFile -OutputFormat mp4 -OutputDirectory .\converted
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('FullName')]
        [string[]] $Path,

        [Parameter(Mandatory)] [string] $OutputFormat,
        [Parameter()]          [string] $OutputDirectory,
        [Parameter()]          [int]    $Quality = 85,
        [Parameter()]          [switch] $Overwrite
    )
    begin {
        $cli = Get-UcxExe
    }
    process {
        foreach ($p in $Path) {
            if (-not (Test-Path $p)) { Write-Warning "Skip $p -- not found"; continue }
            if (-not $PSCmdlet.ShouldProcess($p, "Convert to $OutputFormat")) { continue }

            $argList = @('convert', '-i', (Resolve-Path $p).Path, '-f', $OutputFormat, '-q', $Quality)
            if ($OutputDirectory) { $argList += @('-o', $OutputDirectory) }
            if ($Overwrite)       { $argList += '--overwrite' }

            & $cli @argList
            if ($LASTEXITCODE -ne 0) { Write-Error "Convert failed for $p (exit $LASTEXITCODE)" }
        }
    }
}


# ── Compress-MediaFile ───────────────────────────────────────────────────────

function Compress-MediaFile {
    <#
    .SYNOPSIS
        Shrink a video using the videocrush sidecar (CRF or size-targeted).

    .EXAMPLE
        Compress-MediaFile -Path .\big.mp4 -Preset web-1080p

    .EXAMPLE
        Compress-MediaFile -Path .\big.mp4 -TargetMb 9.5 -Codec libx264

    .EXAMPLE
        Compress-MediaFile -Path .\edit.mov -Preset prores-422-hq -Output .\edit.prores.mov
    #>
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('FullName')]
        [string] $Path,

        [Parameter()] [string] $Output,
        [Parameter()] [string] $Preset,
        [Parameter()] [int]    $Crf,
        [Parameter()] [double] $TargetMb,
        [Parameter()] [string] $Codec,
        [Parameter()] [string] $Resolution,
        [Parameter()]
        [ValidateSet('none','nvenc','amf','qsv','d3d12')]
        [string] $HwAccel = 'none'
    )
    begin {
        $exe = Get-UcxSidecar -Name 'videocrush'
    }
    process {
        if (-not (Test-Path $Path)) { Write-Warning "Skip $Path -- not found"; return }
        if (-not $Output) {
            $stem = [IO.Path]::GetFileNameWithoutExtension($Path)
            $Output = Join-Path (Split-Path $Path -Parent) "$($stem)_compressed$([IO.Path]::GetExtension($Path))"
        }

        if (-not $PSCmdlet.ShouldProcess($Path, "Compress -> $Output")) { return }

        $argList = @('--input', (Resolve-Path $Path).Path, '--output', $Output)
        if ($Preset)     { $argList += @('--preset',  $Preset) }
        if ($Crf)        { $argList += @('--crf',     $Crf) }
        if ($TargetMb)   { $argList += @('--target-mb', $TargetMb) }
        if ($Codec)      { $argList += @('--codec',   $Codec) }
        if ($Resolution) { $argList += @('--resolution', $Resolution) }
        if ($HwAccel)    { $argList += @('--hwaccel', $HwAccel) }

        Invoke-UcxNdjson -Exe $exe -ArgsList $argList -Activity "Compress $Path"
        Write-Output (Get-Item $Output)
    }
}


# ── Get-MediaInfo ────────────────────────────────────────────────────────────

function Get-MediaInfo {
    <#
    .SYNOPSIS
        Probe a media file via ffprobe (bundled or PATH-resolved).

    .EXAMPLE
        Get-MediaInfo .\source.mp4 | Select-Object Duration, Width, Height
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
        [Alias('FullName')]
        [string] $Path
    )
    process {
        if (-not (Test-Path $Path)) { Write-Warning "Skip $Path -- not found"; return }
        $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
        if (-not $ffprobe) {
            $root = Get-UcxRoot
            $ffprobe = Join-Path $root 'tools\_bin\ffprobe.exe'
            if (-not (Test-Path $ffprobe)) { throw 'ffprobe not on PATH and not bundled at tools/_bin/ffprobe.exe.' }
        }
        $resolvedExe = if ($ffprobe -is [string]) { $ffprobe } else { $ffprobe.Source }
        $json = & $resolvedExe -v quiet -show_format -show_streams -print_format json (Resolve-Path $Path).Path
        if ($LASTEXITCODE -ne 0) { Write-Error "ffprobe failed (exit $LASTEXITCODE)"; return }
        $obj = $json | ConvertFrom-Json
        $videoStream = $obj.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1

        [PSCustomObject]@{
            Path       = (Resolve-Path $Path).Path
            FormatName = $obj.format.format_name
            Duration   = [double]$obj.format.duration
            SizeBytes  = [long]$obj.format.size
            VideoCodec = $videoStream.codec_name
            Width      = [int]$videoStream.width
            Height     = [int]$videoStream.height
            FrameRate  = $videoStream.avg_frame_rate
            Streams    = $obj.streams
            FormatTags = $obj.format.tags
        }
    }
}


# ── Watch-MediaFolder ────────────────────────────────────────────────────────

function Watch-MediaFolder {
    <#
    .SYNOPSIS
        Watch a folder for new media files and convert each one as it arrives.

    .DESCRIPTION
        Backed by [System.IO.FileSystemWatcher]. Each new file is passed
        through Convert-MediaFile or Compress-MediaFile based on the chosen
        action. Press Ctrl+C to stop the watcher.

    .EXAMPLE
        Watch-MediaFolder -Path D:\incoming -Action Convert -OutputFormat mp4

    .EXAMPLE
        Watch-MediaFolder -Path D:\incoming -Action Compress -Preset web-1080p
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter()] [string[]] $Filter = @('*.mp4','*.mkv','*.mov','*.avi','*.webm','*.m4v'),
        [Parameter(Mandatory)]
        [ValidateSet('Convert','Compress')]
        [string] $Action,
        [Parameter()] [string] $OutputFormat,
        [Parameter()] [string] $Preset = 'web-1080p',
        [Parameter()] [int]    $StableSeconds = 5
    )

    if (-not (Test-Path $Path -PathType Container)) { throw "Path '$Path' is not a directory." }
    Write-Host "Watching $Path (action=$Action, filters=[$($Filter -join ', ')])..."
    Write-Host 'Press Ctrl+C to stop.'

    $watcher = New-Object System.IO.FileSystemWatcher
    $watcher.Path = (Resolve-Path $Path).Path
    $watcher.IncludeSubdirectories = $false
    $watcher.EnableRaisingEvents = $true

    Register-ObjectEvent $watcher 'Created' -Action {
        $arrival = $Event.SourceEventArgs.FullPath
        Start-Sleep -Seconds $using:StableSeconds   # let copies settle

        if (-not (Test-Path $arrival)) { return }
        $matched = $false
        foreach ($f in $using:Filter) {
            if ([IO.Path]::GetFileName($arrival) -like $f) { $matched = $true; break }
        }
        if (-not $matched) { return }

        Write-Host "[$(Get-Date -Format HH:mm:ss)] Picked up: $arrival"
        try {
            if ($using:Action -eq 'Convert') {
                Convert-MediaFile -Path $arrival -OutputFormat $using:OutputFormat -ErrorAction Stop
            } else {
                Compress-MediaFile -Path $arrival -Preset $using:Preset -ErrorAction Stop
            }
        } catch {
            Write-Warning "Failed for $($arrival): $_"
        }
    } | Out-Null

    try { while ($true) { Start-Sleep 1 } }
    finally {
        Get-EventSubscriber | Unregister-Event
        $watcher.EnableRaisingEvents = $false
        $watcher.Dispose()
        Write-Host 'Watcher stopped.'
    }
}


Export-ModuleMember -Function `
    Get-UcxRoot, Get-UcxExe, Get-UcxSidecar, Test-Ucx, `
    Convert-MediaFile, Compress-MediaFile, Get-MediaInfo, Watch-MediaFolder
