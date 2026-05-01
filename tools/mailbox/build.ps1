#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the mailbox sidecar into a single-file Windows exe.
#>
[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv, *.spec
}
if (-not (Test-Path .venv)) { python -m venv .venv }
$python = Join-Path $here '.venv/Scripts/python.exe'

& $python -m pip install --quiet --upgrade pip pyinstaller
# (no third-party deps)

& $python -m PyInstaller `
    --name mailbox `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/mailbox.exe') (Join-Path $here 'mailbox.exe') -Force
$size = (Get-Item (Join-Path $here 'mailbox.exe')).Length / 1MB
Write-Host ("[done] mailbox.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
