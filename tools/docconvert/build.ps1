#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the document-converter sidecar (LibreOffice headless wrapper) into a
  single-file Windows exe. Pure-Python -- no third-party deps.
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
    --name docconvert `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/docconvert.exe') (Join-Path $here 'docconvert.exe') -Force
$size = (Get-Item (Join-Path $here 'docconvert.exe')).Length / 1MB
Write-Host ("[done] docconvert.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
Write-Host "Note: requires LibreOffice on PATH or installed at C:\Program Files\LibreOffice\." -ForegroundColor Yellow
