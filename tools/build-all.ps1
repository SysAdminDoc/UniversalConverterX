#requires -Version 5.1
<#
.SYNOPSIS
    Build orchestrator for every UCX sidecar.

.DESCRIPTION
    Fans out across tools/*/build.ps1, gathers exit codes, runs the NDJSON
    contract conformance check (tests/sidecar_contract/check_contract.py)
    before any build, and writes a single build-report.json + build-report.md
    summary so CI has one artifact instead of N.

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
    [switch]   $Parallel
)

$ErrorActionPreference = 'Stop'

$ToolsDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $ToolsDir '..')
$ReportDir = Join-Path $RepoRoot 'artifacts\build-reports'
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$JsonReport = Join-Path $ReportDir 'build-report.json'
$MdReport   = Join-Path $ReportDir 'build-report.md'

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

# ── Per-sidecar build ────────────────────────────────────────────────────────
function Invoke-OneBuild {
    param(
        [string] $Tool,
        [string] $ToolsDir,
        [bool]   $Clean
    )

    $script = Join-Path $ToolsDir "$Tool\build.ps1"
    $started = Get-Date

    $log = & {
        $args = @()
        if ($Clean) { $args += '-Clean' }
        # Some build.ps1 reject unknown args; tolerate that case.
        try {
            & pwsh -NoProfile -File $script @args 2>&1
        } catch {
            "$($_.Exception.Message)"
        }
    } | Out-String

    return [PSCustomObject]@{
        Tool       = $Tool
        ExitCode   = $LASTEXITCODE
        DurationS  = [int]((Get-Date) - $started).TotalSeconds
        Log        = $log.TrimEnd()
    }
}

$results = New-Object System.Collections.Generic.List[object]

if ($Parallel -and $targets.Count -gt 1) {
    Write-Host "[build-all] Parallel mode (CPU-bound — be sure you have headroom)" -ForegroundColor Yellow
    $jobs = foreach ($t in $targets) {
        Start-ThreadJob -Name "build-$t" -ScriptBlock {
            param($Tool, $ToolsDir, $Clean)
            $script = Join-Path $ToolsDir "$Tool\build.ps1"
            $started = Get-Date
            $log = (& pwsh -NoProfile -File $script @(if ($Clean) { '-Clean' }) 2>&1) | Out-String
            [PSCustomObject]@{
                Tool      = $Tool
                ExitCode  = $LASTEXITCODE
                DurationS = [int]((Get-Date) - $started).TotalSeconds
                Log       = $log.TrimEnd()
            }
        } -ArgumentList $t, $ToolsDir, $Clean.IsPresent
    }
    $jobs | Wait-Job | Out-Null
    foreach ($j in $jobs) { $results.Add(($j | Receive-Job)) | Out-Null }
    $jobs | Remove-Job
} else {
    foreach ($t in $targets) {
        Write-Host "[build-all] $t ..." -ForegroundColor Cyan
        $r = Invoke-OneBuild -Tool $t -ToolsDir $ToolsDir -Clean:$Clean
        $results.Add($r) | Out-Null
        $tag = if ($r.ExitCode -eq 0) { 'OK ' } else { 'FAIL' }
        $color = if ($r.ExitCode -eq 0) { 'Green' } else { 'Red' }
        Write-Host "[build-all] $tag $t (exit $($r.ExitCode), $($r.DurationS)s)" -ForegroundColor $color
    }
}

# ── Reports ──────────────────────────────────────────────────────────────────
$jsonPayload = @{
    timestamp = (Get-Date).ToString('o')
    repoRoot  = $RepoRoot.Path
    targets   = $targets
    results   = $results | ForEach-Object {
        @{
            tool      = $_.Tool
            exitCode  = $_.ExitCode
            durationS = $_.DurationS
        }
    }
}
$jsonPayload | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $JsonReport

$mdLines = New-Object System.Collections.Generic.List[string]
$mdLines.Add("# UCX Sidecar Build Report") | Out-Null
$mdLines.Add('') | Out-Null
$mdLines.Add("Generated: $((Get-Date).ToString('u'))") | Out-Null
$mdLines.Add('') | Out-Null
$mdLines.Add('| Tool | Result | Duration |') | Out-Null
$mdLines.Add('|------|--------|----------|') | Out-Null
foreach ($r in $results) {
    $mark = if ($r.ExitCode -eq 0) { 'OK' } else { "FAIL (exit $($r.ExitCode))" }
    $mdLines.Add("| $($r.Tool) | $mark | $($r.DurationS) s |") | Out-Null
}
$mdLines.Add('') | Out-Null
foreach ($r in $results | Where-Object { $_.ExitCode -ne 0 }) {
    $mdLines.Add("## $($r.Tool) — failure log") | Out-Null
    $mdLines.Add('```') | Out-Null
    $mdLines.Add($r.Log) | Out-Null
    $mdLines.Add('```') | Out-Null
    $mdLines.Add('') | Out-Null
}
($mdLines -join "`n") | Set-Content -Encoding utf8 $MdReport

# ── Summary ──────────────────────────────────────────────────────────────────
$failed = $results | Where-Object { $_.ExitCode -ne 0 }
$totalS = ($results | Measure-Object -Property DurationS -Sum).Sum

Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host "[build-all] FAIL — $($failed.Count) of $($results.Count) sidecar(s) failed (total ${totalS}s)" -ForegroundColor Red
    Write-Host "[build-all] Reports: $JsonReport"
    Write-Host "[build-all] Reports: $MdReport"
    exit 1
} else {
    Write-Host "[build-all] OK — $($results.Count) sidecar(s) built in ${totalS}s" -ForegroundColor Green
    Write-Host "[build-all] Reports: $JsonReport"
    Write-Host "[build-all] Reports: $MdReport"
    exit 0
}
