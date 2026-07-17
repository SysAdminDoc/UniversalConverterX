#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Fast', 'All')]
    [string]$Mode = 'All',
    [string[]]$Engine = @(),
    [switch]$Freeze,
    [ValidateRange(1, 300)]
    [int]$TimeoutSeconds = 15,
    [ValidateRange(30, 7200)]
    [int]$FreezeTimeoutSeconds = 900,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$verifier = Join-Path $PSScriptRoot 'verify_sidecars.py'
$arguments = @('-3.12', $verifier, '--mode', $Mode.ToLowerInvariant(), '--timeout', $TimeoutSeconds)
foreach ($name in $Engine) { $arguments += @('--engine', $name) }
if ($Freeze) { $arguments += @('--freeze', '--freeze-timeout', $FreezeTimeoutSeconds) }
if ($Json) { $arguments += '--json' }

Push-Location $repo
try {
    & py @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
