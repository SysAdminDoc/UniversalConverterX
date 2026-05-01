#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the Pandoc wrapper sidecar into a single-file Windows exe.
  Pure-Python -- no third-party deps. Requires Pandoc installed at runtime.
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

& $python -m PyInstaller `
    --name pandoc-cli `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/pandoc-cli.exe') (Join-Path $here 'pandoc-cli.exe') -Force
$size = (Get-Item (Join-Path $here 'pandoc-cli.exe')).Length / 1MB
Write-Host ("[done] pandoc-cli.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
Write-Host "Note: requires Pandoc on PATH or installed at C:\Program Files\Pandoc\." -ForegroundColor Yellow
