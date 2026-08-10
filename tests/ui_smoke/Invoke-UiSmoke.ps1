<#
.SYNOPSIS
    Runtime UI smoke gate: drives the real shell through every registered route.

.DESCRIPTION
    Launches the built x64 WinUI app with --ui-smoke, waits for it to sweep
    every route in NavigationRoutes across the light, dark, and narrow-reflow
    passes, then fails on any page that threw, laid out empty, exposed no
    reachable focus target, or produced an unhandled exception.

    Failure screenshots and the machine-readable report land in -ReportPath.

.PARAMETER ExePath
    UniversalConverterX.exe to drive. Defaults to the Release x64 build output.

.PARAMETER Launcher
    Optional script that launches the app somewhere isolated instead of on the
    operator's desktop. It is invoked as
    "<launcher> launch -FilePath <exe> -ArgumentList <args>" and must emit a
    JSON object carrying a processId.
#>
[CmdletBinding()]
param(
    [string]$ExePath,

    [string]$ReportPath,

    [string]$Launcher,

    [ValidateRange(60, 3600)]
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

if ([string]::IsNullOrWhiteSpace($ExePath)) {
    $ExePath = Join-Path $repoRoot (
        'src\UniversalConverterX.UI\bin\x64\Release\' +
        'net10.0-windows10.0.22621.0\UniversalConverterX.exe')
}
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "UI build output not found: $ExePath. Build the x64 Release UI first."
}
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportPath = Join-Path $repoRoot 'artifacts\ui-smoke'
}
if (Test-Path -LiteralPath $ReportPath) {
    $resolvedReport = [IO.Path]::GetFullPath($ReportPath)
    $resolvedRoot = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\', '/')
    $inRepo = $resolvedReport.StartsWith(
        $resolvedRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)
    $inTemp = $resolvedReport.StartsWith(
        [IO.Path]::GetFullPath([IO.Path]::GetTempPath()),
        [StringComparison]::OrdinalIgnoreCase)
    if (-not ($inRepo -or $inTemp)) {
        throw "Refusing to clear a report path outside the repo or temp: $resolvedReport"
    }
    Remove-Item -LiteralPath $ReportPath -Recurse -Force
}
New-Item -ItemType Directory -Path $ReportPath -Force | Out-Null

$arguments = @('--ui-smoke', $ReportPath)

if ([string]::IsNullOrWhiteSpace($Launcher)) {
    $process = Start-Process -FilePath $ExePath -ArgumentList $arguments -PassThru
    $processId = $process.Id
} else {
    $launchOutput = & $Launcher launch -FilePath $ExePath -ArgumentList $arguments
    $json = $launchOutput | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
    if ($null -eq $json) {
        throw "Launcher did not report a process: $($launchOutput -join ' ')"
    }
    $processId = ([string]$json | ConvertFrom-Json).processId
}

Write-Host "UI smoke running (pid $processId); report: $ReportPath" -ForegroundColor Cyan

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds 5
}
if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    throw "UI smoke did not finish within $TimeoutSeconds seconds."
}

$reportFile = Join-Path $ReportPath 'ui-smoke.json'
if (-not (Test-Path -LiteralPath $reportFile -PathType Leaf)) {
    throw "UI smoke exited without writing $reportFile (the app likely failed to start)."
}

$report = Get-Content -LiteralPath $reportFile -Raw | ConvertFrom-Json
$failures = @($report.results | Where-Object { -not $_.Passed })
foreach ($failure in $failures) {
    Write-Host (
        "FAIL {0} [{1}]: {2}" -f $failure.RouteKey, $failure.Theme, $failure.Failure
    ) -ForegroundColor Red
}
foreach ($unhandled in @($report.unhandledExceptions)) {
    Write-Host "UNHANDLED: $unhandled" -ForegroundColor Red
}

Write-Host (
    "Routes {0}; passes {1}; failures {2}" -f
        $report.routeCount, $report.passes, $report.failures
) -ForegroundColor Green

if ($failures.Count -gt 0 -or @($report.unhandledExceptions).Count -gt 0) {
    throw "Runtime UI smoke failed. See $ReportPath for screenshots."
}

$report
