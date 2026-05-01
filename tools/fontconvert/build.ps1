#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the font converter sidecar (fonttools + brotli) into a single-file Windows exe.
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
& $python -m pip install --quiet 'fonttools>=4.50,<5' brotli zopfli

& $python -m PyInstaller `
    --name fontconvert `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all fontTools `
    --hidden-import brotli `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/fontconvert.exe') (Join-Path $here 'fontconvert.exe') -Force
$size = (Get-Item (Join-Path $here 'fontconvert.exe')).Length / 1MB
Write-Host ("[done] fontconvert.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
