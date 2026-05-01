#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the iccprofile sidecar into a single-file Windows exe.
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
& $python -m pip install --quiet Pillow

& $python -m PyInstaller `
    --name iccprofile `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/iccprofile.exe') (Join-Path $here 'iccprofile.exe') -Force
$size = (Get-Item (Join-Path $here 'iccprofile.exe')).Length / 1MB
Write-Host ("[done] iccprofile.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
