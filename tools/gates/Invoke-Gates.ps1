<#
.SYNOPSIS
    Runs every local release gate in one fail-fast command.

.DESCRIPTION
    The canonical Test target used to cover only the Core suite and the
    VideoScaler smoke, which left Python, sidecar, localization, accessibility,
    packaging, and dependency failures outside the release contract. This
    script is the single aggregate: it runs each gate in ascending cost order,
    stops at the first failure unless -ContinueOnFailure is set, and writes a
    machine-readable summary to artifacts/gates/gate-summary.json.

    Gates that need artifacts this repository does not currently hold (a staged
    publish tree, an ARM64 publish) are reported as "skipped" with the reason
    rather than silently omitted.

.PARAMETER Configuration
    Debug or Release. Release is the release contract.

.PARAMETER Only
    Run just these gate ids. Useful while iterating; not a release run.

.PARAMETER Skip
    Skip these gate ids. Every skip is recorded in the summary.

.PARAMETER UiSmokeLauncher
    Optional launcher script for the runtime UI gate so the swept window opens
    off the operator's desktop.

.PARAMETER ContinueOnFailure
    Run every gate and report all failures instead of stopping at the first.
#>
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',

    [string[]]$Only = @(),

    [string[]]$Skip = @(),

    [string]$UiSmokeLauncher,

    [switch]$ContinueOnFailure,

    [string]$SummaryPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$solution = Join-Path $repoRoot 'src\UniversalConverterX.sln'
$publishRoot = Join-Path $repoRoot 'publish'
$python = 'python'
if (Get-Command 'py' -ErrorAction SilentlyContinue) { $python = 'py' }

if ([string]::IsNullOrWhiteSpace($SummaryPath)) {
    $SummaryPath = Join-Path $repoRoot 'artifacts\gates\gate-summary.json'
}

function New-Gate {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [scriptblock]$SkipWhen
    )
    [pscustomobject]@{
        Id = $Id
        Description = $Description
        Action = $Action
        SkipWhen = $SkipWhen
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $output = & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $text = ($output | Out-String).Trim()
        throw "$FilePath $($Arguments -join ' ') failed ($LASTEXITCODE):`n$text"
    }
    return $output
}

function Invoke-Pytest {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $pythonArguments = @()
    if ($python -eq 'py') { $pythonArguments += '-3.12' }
    Invoke-Native -FilePath $python -Arguments ($pythonArguments + @('-m', 'pytest', '-q') + $Arguments)
}

function Invoke-PythonScript {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $pythonArguments = @()
    if ($python -eq 'py') { $pythonArguments += '-3.12' }
    Invoke-Native -FilePath $python -Arguments ($pythonArguments + $Arguments)
}

$sidecarContractDir = Join-Path $repoRoot 'tests\sidecar_contract'
$syntaxTest = Join-Path $sidecarContractDir 'test_python_source_syntax.py'
$localizationTest = Join-Path $sidecarContractDir 'test_localization_resources.py'
$allowlist = Join-Path $repoRoot 'tools\gates\allowlist.json'

$gates = @(
    New-Gate -Id 'nuget-lock' -Description 'Restore resolves exactly the committed packages.lock.json graph' -Action {
        Invoke-Native -FilePath 'dotnet' -Arguments @(
            'restore', $solution, '--locked-mode', '-p:Platform=x64', '--nologo')
        Invoke-Native -FilePath 'dotnet' -Arguments @(
            'restore',
            (Join-Path $repoRoot 'tests\UniversalConverterX.VideoScalerSmoke\UniversalConverterX.VideoScalerSmoke.csproj'),
            '--locked-mode', '--nologo')
    }

    New-Gate -Id 'build' -Description 'x64 solution builds' -Action {
        Invoke-Native -FilePath 'dotnet' -Arguments @(
            'build', $solution, '-c', $Configuration, '--nologo',
            '--verbosity', 'minimal', '-p:Platform=x64', '--no-restore')
    }

    New-Gate -Id 'core-tests' -Description 'Core xUnit suite' -Action {
        Invoke-Native -FilePath 'dotnet' -Arguments @(
            'test',
            (Join-Path $repoRoot 'tests\UniversalConverterX.Core.Tests\UniversalConverterX.Core.Tests.csproj'),
            '-c', $Configuration, '--nologo', '--no-build', '--no-restore',
            '--verbosity', 'minimal', '-p:Platform=x64')
    }

    New-Gate -Id 'videoscaler-smoke' -Description 'Windows AI VideoScaler capability probe' -Action {
        Invoke-Native -FilePath 'dotnet' -Arguments @(
            'run', '--project',
            (Join-Path $repoRoot 'tests\UniversalConverterX.VideoScalerSmoke\UniversalConverterX.VideoScalerSmoke.csproj'),
            '-c', $Configuration, '--nologo', '--verbosity', 'quiet')
    } -SkipWhen {
        if (-not ($IsWindows -or $env:OS -eq 'Windows_NT')) { 'requires a Windows host' }
    }

    New-Gate -Id 'python-syntax' -Description 'Every tracked *.py parses' -Action {
        Invoke-Pytest -Arguments @($syntaxTest)
    }

    New-Gate -Id 'sidecar-contract' -Description '212-sidecar NDJSON contract, security floors, ORT matrix' -Action {
        Invoke-PythonScript -Arguments @((Join-Path $sidecarContractDir 'check_contract.py'))
    }

    New-Gate -Id 'sidecar-unit' -Description 'Sidecar behaviour and hardening unit tests' -Action {
        Invoke-Pytest -Arguments @(
            $sidecarContractDir,
            "--ignore=$syntaxTest",
            "--ignore=$localizationTest")
    }

    New-Gate -Id 'shared-lib-unit' -Description 'Shared ucx_sidecar helper tests' -Action {
        Invoke-Pytest -Arguments @((Join-Path $repoRoot 'tools\_lib\tests'))
    }

    New-Gate -Id 'localization' -Description 'x:Uid / RESW key and placeholder parity across 6 locales' -Action {
        Invoke-Pytest -Arguments @($localizationTest)
    }

    New-Gate -Id 'uia-contract' -Description 'Static AutomationId coverage against the ratcheted baseline' -Action {
        Invoke-PythonScript -Arguments @((Join-Path $repoRoot 'tests\uia_contract\check_uia.py'))
    }

    New-Gate -Id 'virtualization-contract' -Description 'Virtualized catalog surfaces and bounded UI performance budgets' -Action {
        Invoke-PythonScript -Arguments @((Join-Path $repoRoot 'tests\uia_contract\check_virtualization.py'))
    }

    New-Gate -Id 'release-manifest' -Description 'Release manifest, WiX payload, and readiness staging tests' -Action {
        Invoke-Pytest -Arguments @((Join-Path $repoRoot 'tests\release_manifest'))
    }

    New-Gate -Id 'dependency-manifest' -Description 'Every sidecar build.ps1 resolves its declared requirements' -Action {
        Invoke-PythonScript -Arguments @(
            (Join-Path $repoRoot 'tools\dependencies\sidecar_dependencies.py'),
            'audit', '--repo-root', $repoRoot)
    }

    New-Gate -Id 'nuget-audit' -Description 'No unallowlisted vulnerable or deprecated NuGet package' -Action {
        Invoke-PythonScript -Arguments @(
            (Join-Path $repoRoot 'tools\gates\dependency_gate.py'),
            'nuget', '--solution', $solution, '--allowlist', $allowlist)
    }

    New-Gate -Id 'allowlist-expiry' -Description 'No expired or over-long dependency suppression' -Action {
        Invoke-PythonScript -Arguments @(
            (Join-Path $repoRoot 'tools\gates\dependency_gate.py'),
            'allowlist', '--allowlist', $allowlist)
    }

    New-Gate -Id 'runtime-ui' -Description 'Every route opens in light, dark, and narrow reflow' -Action {
        $smokeArguments = @{
            ExePath = Join-Path $repoRoot (
                'src\UniversalConverterX.UI\bin\x64\' + $Configuration +
                '\net10.0-windows10.0.19041.0\UniversalConverterX.exe')
        }
        if (-not [string]::IsNullOrWhiteSpace($UiSmokeLauncher)) {
            $smokeArguments.Launcher = $UiSmokeLauncher
        }
        & (Join-Path $repoRoot 'tests\ui_smoke\Invoke-UiSmoke.ps1') @smokeArguments | Out-Null
    } -SkipWhen {
        if (-not ($IsWindows -or $env:OS -eq 'Windows_NT')) { 'requires a Windows host' }
    }

    New-Gate -Id 'staged-artifact' -Description 'Staged publish tree matches its readiness manifest byte for byte' -Action {
        Invoke-PythonScript -Arguments @(
            (Join-Path $repoRoot 'tools\release\sidecar_readiness.py'),
            'verify',
            '--stage-root', $publishRoot,
            '--source-tools', (Join-Path $repoRoot 'tools'),
            '--architecture', 'win-x64')
    } -SkipWhen {
        if (-not (Test-Path -LiteralPath (Join-Path $publishRoot 'sidecar-readiness.json') -PathType Leaf)) {
            'no staged publish tree; run build.ps1 -Target Publish first'
        }
    }

    New-Gate -Id 'sbom-reconcile' -Description 'CycloneDX SBOM reconciles against the staged tree' -Action {
        $sbomArguments = @(
            (Join-Path $repoRoot 'tools\dependencies\sidecar_dependencies.py'),
            'sbom',
            '--repo-root', $repoRoot,
            '--stage-root', $publishRoot,
            '--output', (Join-Path $repoRoot 'artifacts\gates\UniversalConverterX.cdx.json'),
            '--product-version', '0.0.0-gate')
        $lock = Join-Path $repoRoot 'artifacts\python-dependencies\sidecar-lock.json'
        if (Test-Path -LiteralPath $lock -PathType Leaf) {
            $sbomArguments += @('--lock', $lock)
        }
        Invoke-PythonScript -Arguments $sbomArguments
    } -SkipWhen {
        if (-not (Test-Path -LiteralPath (Join-Path $publishRoot 'sidecar-readiness.json') -PathType Leaf)) {
            'no staged publish tree; run build.ps1 -Target Publish first'
        }
    }
)

$summaryDirectory = Split-Path -Parent $SummaryPath
if (-not [string]::IsNullOrWhiteSpace($summaryDirectory)) {
    New-Item -ItemType Directory -Path $summaryDirectory -Force | Out-Null
}

$results = [Collections.Generic.List[object]]::new()
$failed = $false
$startedAll = Get-Date

foreach ($gate in $gates) {
    if ($Only.Count -gt 0 -and $gate.Id -notin $Only) { continue }

    $status = 'passed'
    $reason = $null
    $started = Get-Date

    if ($gate.Id -in $Skip) {
        $status = 'skipped'
        $reason = 'explicitly skipped on the command line'
    } elseif ($failed -and -not $ContinueOnFailure) {
        $status = 'skipped'
        $reason = 'an earlier gate failed'
    } elseif ($null -ne $gate.SkipWhen -and ($skipReason = & $gate.SkipWhen)) {
        $status = 'skipped'
        $reason = [string]$skipReason
    } else {
        Write-Host "== gate: $($gate.Id) -- $($gate.Description)" -ForegroundColor Cyan
        try {
            & $gate.Action | Out-Null
        } catch {
            $status = 'failed'
            $reason = ($_ | Out-String).Trim()
            $failed = $true
        }
    }

    $results.Add([pscustomobject]@{
        id = $gate.Id
        description = $gate.Description
        status = $status
        reason = $reason
        durationSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    })

    switch ($status) {
        'passed'  { Write-Host "   PASS $($gate.Id)" -ForegroundColor Green }
        'skipped' { Write-Host "   SKIP $($gate.Id): $reason" -ForegroundColor Yellow }
        'failed'  { Write-Host "   FAIL $($gate.Id): $reason" -ForegroundColor Red }
    }
}

$summary = [pscustomobject]@{
    schemaVersion = 1
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    configuration = $Configuration
    architecture = 'x64'
    durationSeconds = [math]::Round(((Get-Date) - $startedAll).TotalSeconds, 2)
    passed = @($results | Where-Object { $_.status -eq 'passed' }).Count
    failed = @($results | Where-Object { $_.status -eq 'failed' }).Count
    skipped = @($results | Where-Object { $_.status -eq 'skipped' }).Count
    gates = @($results)
}
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $SummaryPath -Encoding utf8

$summaryColor = 'Green'
if ($summary.failed -gt 0) { $summaryColor = 'Red' }
Write-Host ""
Write-Host (
    "Gates: {0} passed, {1} failed, {2} skipped ({3}s). Summary: {4}" -f
        $summary.passed, $summary.failed, $summary.skipped,
        $summary.durationSeconds, $SummaryPath
) -ForegroundColor $summaryColor

if ($summary.failed -gt 0) {
    throw "$($summary.failed) gate(s) failed. See $SummaryPath."
}
$summary
