#requires -Version 5.1
<#
.SYNOPSIS
    Build orchestrator for every UCX sidecar.

.DESCRIPTION
    Fans out across tools/*/build.ps1, gathers exit codes, runs the NDJSON
    contract conformance check (tests/sidecar_contract/check_contract.py)
    before any build, verifies a revision- and hash-locked offline Python
    wheelhouse, and writes one machine-readable build-report.json.

    Default behaviour: contract check, then sequential build of every sidecar
    that has a build.ps1.

.PARAMETER Tools
    Comma-separated subset of sidecars to build (folder names under tools/).
    Default: every directory containing a build.ps1.

.PARAMETER Clean
    Forwarded to per-sidecar build.ps1 where supported (-Clean param).

.PARAMETER SkipContract
    Skip the NDJSON contract conformance check. Don't pass this in CI.

.PARAMETER Parallel
    Build sidecars in parallel via ThreadJob (PS 7+) / Start-Job (PS 5.1).
    Use carefully — each sidecar's PyInstaller pass is already CPU-bound.

.PARAMETER PrepareDependencies
    Connected preparation step: resolve the selected sidecars, download exact
    wheels, record their source URLs/sizes/SHA-256 values, then build offline.

.EXAMPLE
    pwsh tools/build-all.ps1
    # Contract check + sequential build of every sidecar.

.EXAMPLE
    pwsh tools/build-all.ps1 -Tools demucs,whisper-stt,lipsight
    # Build only the v2.3 wave.

.EXAMPLE
    pwsh tools/build-all.ps1 -Tools demucs -Clean
    # Force a clean rebuild of one sidecar.
#>
[CmdletBinding()]
param(
    [string[]] $Tools,
    [switch]   $Clean,
    [switch]   $SkipContract,
    [switch]   $Parallel,
    [switch]   $PrepareDependencies,
    [string]   $DependencyLock,
    [string]   $Wheelhouse,
    [ValidateSet('win-x64', 'win-arm64')]
    [string]   $Architecture = 'win-x64'
)

$ErrorActionPreference = 'Stop'

$ToolsDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ToolsDir '..')
$ReportDir = Join-Path $RepoRoot 'artifacts\build-reports'
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$JsonReport = Join-Path $ReportDir 'build-report.json'
$DependencyRoot = Join-Path $RepoRoot 'artifacts\python-dependencies'
if ([string]::IsNullOrWhiteSpace($DependencyLock)) {
    $DependencyLock = Join-Path $DependencyRoot 'sidecar-lock.json'
} elseif (-not [IO.Path]::IsPathRooted($DependencyLock)) {
    $DependencyLock = Join-Path $RepoRoot $DependencyLock
}
if ([string]::IsNullOrWhiteSpace($Wheelhouse)) {
    $Wheelhouse = Join-Path $DependencyRoot 'wheelhouse'
} elseif (-not [IO.Path]::IsPathRooted($Wheelhouse)) {
    $Wheelhouse = Join-Path $RepoRoot $Wheelhouse
}
$ConstraintsDir = Join-Path (Split-Path -Parent $DependencyLock) 'constraints'
$DependencyScript = Join-Path $ToolsDir 'dependencies\sidecar_dependencies.py'

# ── Discover sidecars with a build.ps1 ───────────────────────────────────────
$discovered = Get-ChildItem -Path $ToolsDir -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'build.ps1') } |
    ForEach-Object { $_.Name } |
    Sort-Object

if ($Tools) {
    $invalid = $Tools | Where-Object { $discovered -notcontains $_ }
    if ($invalid) {
        Write-Error "Unknown sidecar(s): $($invalid -join ', '). Known: $($discovered -join ', ')"
    }
    $targets = $Tools
} else {
    $targets = $discovered
}

Write-Host "[build-all] Target sidecars: $($targets -join ', ')" -ForegroundColor Cyan

# ── Resolve/verify exact offline Python distributions ─────────────────────────
& python $DependencyScript audit --repo-root $RepoRoot.Path
if ($LASTEXITCODE -ne 0) {
    Write-Error '[build-all] Python dependency-manifest audit failed.'
}

$dependencyArguments = @(
    '--repo-root', $RepoRoot.Path,
    '--wheelhouse', $Wheelhouse,
    '--lock', $DependencyLock
)
foreach ($target in $targets) {
    $dependencyArguments += @('--tool', $target)
}

if ($PrepareDependencies) {
    Write-Host "[build-all] Preparing authenticated Python wheelhouse..." -ForegroundColor Cyan
    & python $DependencyScript prepare @dependencyArguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error '[build-all] Dependency preparation failed.'
    }
}

Write-Host "[build-all] Verifying offline Python wheelhouse..." -ForegroundColor Cyan
& python $DependencyScript verify @dependencyArguments --constraints-dir $ConstraintsDir
if ($LASTEXITCODE -ne 0) {
    Write-Error (
        '[build-all] Dependency lock/wheelhouse verification failed. ' +
        'Run again with -PrepareDependencies on a connected machine.')
}
$DependencyLockSha256 = (
    Get-FileHash -LiteralPath $DependencyLock -Algorithm SHA256
).Hash.ToLowerInvariant()

# ── Pre-build contract check ─────────────────────────────────────────────────
if (-not $SkipContract) {
    $checker = Join-Path $RepoRoot 'tests\sidecar_contract\check_contract.py'
    if (-not (Test-Path $checker)) {
        Write-Warning "[build-all] Contract checker not found: $checker"
    } else {
        Write-Host "[build-all] Running NDJSON contract conformance check..." -ForegroundColor Cyan
        & python $checker
        if ($LASTEXITCODE -ne 0) {
            Write-Error "[build-all] Contract check failed — fix violations before building. Pass -SkipContract to override (CI: don't)."
        }
    }
}

# ── Per-sidecar isolated environments and builds ─────────────────────────────
function Initialize-LockedPythonEnvironment {
    param(
        [string] $Tool,
        [string] $ToolsDir,
        [bool]   $Clean,
        [string] $Wheelhouse,
        [string] $LockedRequirementsPath
    )

    $toolsRoot = [IO.Path]::GetFullPath($ToolsDir).TrimEnd('\', '/') +
        [IO.Path]::DirectorySeparatorChar
    $toolDirectory = [IO.Path]::GetFullPath((Join-Path $ToolsDir $Tool))
    if (-not $toolDirectory.StartsWith(
            $toolsRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Sidecar path escapes tools root: $toolDirectory"
    }
    if (-not (Test-Path -LiteralPath $LockedRequirementsPath -PathType Leaf)) {
        throw "Locked requirements are missing for ${Tool}: $LockedRequirementsPath"
    }

    $venv = Join-Path $toolDirectory '.venv'
    # The dependency environment is always recreated. This removes packages
    # left by an earlier connected or developer build before hashes are checked.
    if (Test-Path -LiteralPath $venv) {
        Remove-Item -LiteralPath $venv -Recurse -Force
    }
    if ($Clean) {
        foreach ($name in @('build', 'dist', 'spec')) {
            $candidate = Join-Path $toolDirectory $name
            if (Test-Path -LiteralPath $candidate) {
                Remove-Item -LiteralPath $candidate -Recurse -Force
            }
        }
        foreach ($specFile in @(Get-ChildItem `
                -LiteralPath $toolDirectory `
                -Filter '*.spec' `
                -File `
                -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $specFile.FullName -Force
        }
    }

    $venvOutput = & python -m venv $venv 2>&1
    $venvExitCode = $LASTEXITCODE
    $venvOutput | ForEach-Object { Write-Host $_ }
    if ($venvExitCode -ne 0) {
        throw "Could not create isolated Python environment for $Tool."
    }
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment did not create Python for $Tool."
    }

    $installOutput = & $venvPython -m pip --isolated install `
        --disable-pip-version-check `
        --no-index `
        --find-links $Wheelhouse `
        --only-binary ':all:' `
        --require-hashes `
        --no-deps `
        --requirement $LockedRequirementsPath 2>&1
    $installExitCode = $LASTEXITCODE
    $installOutput | ForEach-Object { Write-Host $_ }
    if ($installExitCode -ne 0) {
        throw "Hash-locked offline dependency install failed for $Tool."
    }
    $checkOutput = & $venvPython -m pip --isolated check 2>&1
    $checkExitCode = $LASTEXITCODE
    $checkOutput | ForEach-Object { Write-Host $_ }
    if ($checkExitCode -ne 0) {
        throw "Installed dependency graph is inconsistent for $Tool."
    }
    return $venvPython
}

function Get-SidecarExecutableName {
    param([Parameter(Mandatory=$true)][string] $Tool)

    switch ($Tool.ToLowerInvariant()) {
        'ab-av1'      { return 'ab-av1-sidecar.exe' }
        'av1an'       { return 'av1an-sidecar.exe' }
        'comskip'     { return 'comskip-sidecar.exe' }
        'demucs'      { return 'demucs-sidecar.exe' }
        'whisper-stt' { return 'ucx-whisper-stt.exe' }
        default       { return "$Tool.exe" }
    }
}

function Get-SidecarArtifact {
    param(
        [Parameter(Mandatory=$true)][string] $Tool,
        [Parameter(Mandatory=$true)][string] $ToolsDir,
        [Parameter(Mandatory=$true)][string] $RepoRoot,
        [Parameter(Mandatory=$true)][DateTime] $BuildStartedUtc
    )

    $dist = [IO.Path]::GetFullPath((Join-Path $ToolsDir "$Tool\dist"))
    if (-not (Test-Path -LiteralPath $dist -PathType Container)) {
        throw "Successful build did not create a dist directory for $Tool."
    }
    $expected = Get-SidecarExecutableName -Tool $Tool
    $candidates = @(
        Get-ChildItem -LiteralPath $dist -File -Recurse -Filter $expected |
            Sort-Object @{ Expression = { $_.FullName.Length } }, FullName
    )
    if ($candidates.Count -eq 0) {
        throw "Successful build did not produce the expected $expected for $Tool."
    }
    $entrypoint = $candidates[0]
    if ($entrypoint.LastWriteTimeUtc -lt $BuildStartedUtc.AddSeconds(-2)) {
        throw "The reported $Tool entrypoint predates this build."
    }

    $artifactRoot = $entrypoint.Directory.FullName
    $layout = if (
        $artifactRoot.TrimEnd('\', '/').Equals(
            $dist.TrimEnd('\', '/'),
            [StringComparison]::OrdinalIgnoreCase)
    ) { 'onefile' } else { 'onedir' }
    $files = @(
        Get-ChildItem -LiteralPath $artifactRoot -File -Recurse |
            Sort-Object FullName |
            ForEach-Object {
                [ordered]@{
                    path = [IO.Path]::GetRelativePath(
                        $artifactRoot, $_.FullName).Replace('\', '/')
                    sizeBytes = $_.Length
                    sha256 = (
                        Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
                    ).Hash.ToLowerInvariant()
                }
            }
    )
    if ($files.Count -eq 0) {
        throw "Successful build produced an empty artifact for $Tool."
    }

    return [ordered]@{
        layout = $layout
        rootPath = [IO.Path]::GetRelativePath(
            $RepoRoot, $artifactRoot).Replace('\', '/')
        entrypoint = [IO.Path]::GetRelativePath(
            $artifactRoot, $entrypoint.FullName).Replace('\', '/')
        files = $files
    }
}

function Invoke-OneBuild {
    param(
        [string] $Tool,
        [string] $ToolsDir,
        [string] $VenvPython,
        [string] $Wheelhouse,
        [string] $ConstraintPath,
        [string] $DependencyLock
    )

    $script = Join-Path $ToolsDir "$Tool\build.ps1"
    $started = Get-Date
    $environmentNames = @(
        'PATH',
        'PIP_CONFIG_FILE',
        'PIP_CONSTRAINT',
        'PIP_DISABLE_PIP_VERSION_CHECK',
        'PIP_FIND_LINKS',
        'PIP_NO_INDEX',
        'PIP_NO_INPUT',
        'PIP_ONLY_BINARY',
        'PYTHONNOUSERSITE',
        'UCX_PYTHON_DEPENDENCY_LOCK'
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
            $name, [EnvironmentVariableTarget]::Process)
    }

    try {
        $env:PIP_CONFIG_FILE = if ($env:OS -eq 'Windows_NT') { 'NUL' } else { '/dev/null' }
        $env:PIP_CONSTRAINT = $ConstraintPath
        $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
        $env:PIP_FIND_LINKS = $Wheelhouse
        $env:PIP_NO_INDEX = '1'
        $env:PIP_NO_INPUT = '1'
        $env:PIP_ONLY_BINARY = ':all:'
        $env:PYTHONNOUSERSITE = '1'
        $env:UCX_PYTHON_DEPENDENCY_LOCK = $DependencyLock
        $env:PATH = "$(Split-Path -Parent $VenvPython)$([IO.Path]::PathSeparator)$env:PATH"

        $log = & {
            $buildArguments = @()
            $commandInfo = Get-Command -Name $script
            if ($commandInfo.Parameters.ContainsKey('Python')) {
                $buildArguments += @('-Python', $VenvPython)
            } elseif ($commandInfo.Parameters.ContainsKey('PythonPath')) {
                $buildArguments += @('-PythonPath', $VenvPython)
            }
            try {
                & pwsh -NoProfile -File $script @buildArguments 2>&1
            } catch {
                "$($_.Exception.Message)"
            }
        } | Out-String
        $exitCode = $LASTEXITCODE
    } finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $previousEnvironment[$name],
                [EnvironmentVariableTarget]::Process)
        }
    }

    $artifact = $null
    if ($exitCode -eq 0) {
        try {
            $artifact = Get-SidecarArtifact `
                -Tool $Tool `
                -ToolsDir $ToolsDir `
                -RepoRoot $RepoRoot.Path `
                -BuildStartedUtc $started.ToUniversalTime()
        } catch {
            $log = ($log.TrimEnd() + [Environment]::NewLine +
                "[artifact] $($_.Exception.Message)").Trim()
            $exitCode = 1
        }
    }

    return [PSCustomObject]@{
        Tool       = $Tool
        ExitCode   = $exitCode
        DurationS  = [int]((Get-Date) - $started).TotalSeconds
        Log        = $log.TrimEnd()
        Artifact   = $artifact
    }
}

$pythonByTool = @{}
foreach ($target in $targets) {
    Write-Host "[build-all] Preparing isolated environment for $target..." -ForegroundColor Cyan
    $pythonByTool[$target] = Initialize-LockedPythonEnvironment `
        -Tool $target `
        -ToolsDir $ToolsDir `
        -Clean:$Clean `
        -Wheelhouse $Wheelhouse `
        -LockedRequirementsPath (
            Join-Path $ConstraintsDir "$target.requirements.txt")
}

$results = New-Object System.Collections.Generic.List[object]

if ($Parallel -and $targets.Count -gt 1) {
    Write-Host "[build-all] Parallel mode (CPU-bound — be sure you have headroom)" -ForegroundColor Yellow
    $jobs = foreach ($t in $targets) {
        Start-ThreadJob -Name "build-$t" -ScriptBlock {
            param(
                $Tool,
                $ToolsDir,
                $VenvPython,
                $Wheelhouse,
                $ConstraintPath,
                $DependencyLock
            )
            $script = Join-Path $ToolsDir "$Tool\build.ps1"
            $started = Get-Date
            $env:PATH = "$(Split-Path -Parent $VenvPython)$([IO.Path]::PathSeparator)$env:PATH"
            $env:PIP_CONFIG_FILE = if ($env:OS -eq 'Windows_NT') { 'NUL' } else { '/dev/null' }
            $env:PIP_CONSTRAINT = $ConstraintPath
            $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
            $env:PIP_FIND_LINKS = $Wheelhouse
            $env:PIP_NO_INDEX = '1'
            $env:PIP_NO_INPUT = '1'
            $env:PIP_ONLY_BINARY = ':all:'
            $env:PYTHONNOUSERSITE = '1'
            $env:UCX_PYTHON_DEPENDENCY_LOCK = $DependencyLock
            $buildArguments = @()
            $commandInfo = Get-Command -Name $script
            if ($commandInfo.Parameters.ContainsKey('Python')) {
                $buildArguments += @('-Python', $VenvPython)
            } elseif ($commandInfo.Parameters.ContainsKey('PythonPath')) {
                $buildArguments += @('-PythonPath', $VenvPython)
            }
            $log = (& pwsh -NoProfile -File $script @buildArguments 2>&1) |
                Out-String
            [PSCustomObject]@{
                Tool      = $Tool
                ExitCode  = $LASTEXITCODE
                DurationS = [int]((Get-Date) - $started).TotalSeconds
                Log       = $log.TrimEnd()
                StartedUtc = $started.ToUniversalTime()
            }
        } -ArgumentList @(
            $t,
            $ToolsDir,
            $pythonByTool[$t],
            $Wheelhouse,
            (Join-Path $ConstraintsDir "$t.txt"),
            $DependencyLock
        )
    }
    $jobs | Wait-Job | Out-Null
    foreach ($j in $jobs) {
        $result = $j | Receive-Job
        if ($result.ExitCode -eq 0) {
            try {
                $result | Add-Member -NotePropertyName Artifact -NotePropertyValue (
                    Get-SidecarArtifact `
                        -Tool $result.Tool `
                        -ToolsDir $ToolsDir `
                        -RepoRoot $RepoRoot.Path `
                        -BuildStartedUtc $result.StartedUtc)
            } catch {
                $result.ExitCode = 1
                $result.Log = ($result.Log.TrimEnd() + [Environment]::NewLine +
                    "[artifact] $($_.Exception.Message)").Trim()
            }
        }
        $results.Add($result) | Out-Null
    }
    $jobs | Remove-Job
} else {
    foreach ($t in $targets) {
        Write-Host "[build-all] $t ..." -ForegroundColor Cyan
        $r = Invoke-OneBuild `
            -Tool $t `
            -ToolsDir $ToolsDir `
            -VenvPython $pythonByTool[$t] `
            -Wheelhouse $Wheelhouse `
            -ConstraintPath (Join-Path $ConstraintsDir "$t.txt") `
            -DependencyLock $DependencyLock
        $results.Add($r) | Out-Null
        $tag = if ($r.ExitCode -eq 0) { 'OK ' } else { 'FAIL' }
        $color = if ($r.ExitCode -eq 0) { 'Green' } else { 'Red' }
        Write-Host "[build-all] $tag $t (exit $($r.ExitCode), $($r.DurationS)s)" -ForegroundColor $color
    }
}

# ── Reports ──────────────────────────────────────────────────────────────────
$sourceCommit = (& git -C $RepoRoot.Path rev-parse HEAD 2>$null |
    Select-Object -First 1).Trim()
$sourceDirty = @(& git -C $RepoRoot.Path status --porcelain 2>$null).Count -gt 0
$jsonPayload = [ordered]@{
    schemaVersion = 2
    timestamp = (Get-Date).ToString('o')
    repoRoot  = $RepoRoot.Path
    architecture = $Architecture
    sourceCommit = $sourceCommit
    sourceDirty = $sourceDirty
    clean = [bool]$Clean
    targets   = @($targets)
    dependencyLock = @{
        path   = $DependencyLock
        sha256 = $DependencyLockSha256
    }
    results   = @($results | ForEach-Object {
        @{
            tool      = $_.Tool
            exitCode  = $_.ExitCode
            durationS = $_.DurationS
            artifact  = $_.Artifact
        }
    })
}
$jsonPayload | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $JsonReport

# ── Summary ──────────────────────────────────────────────────────────────────
$failed = $results | Where-Object { $_.ExitCode -ne 0 }
$totalS = ($results | Measure-Object -Property DurationS -Sum).Sum

Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host "[build-all] FAIL — $($failed.Count) of $($results.Count) sidecar(s) failed (total ${totalS}s)" -ForegroundColor Red
    Write-Host "[build-all] Reports: $JsonReport"
    exit 1
} else {
    Write-Host "[build-all] OK — $($results.Count) sidecar(s) built in ${totalS}s" -ForegroundColor Green
    Write-Host "[build-all] Reports: $JsonReport"
    exit 0
}
