#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the PDF tools sidecar (pikepdf-based) into a single-file Windows exe.
  Bundles pikepdf which embeds qpdf -- no external runtime dependency.
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
& $python -m pip install --quiet 'pikepdf>=9.0,<10'

& $python -m PyInstaller `
    --name pdftools `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all pikepdf `
    --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/pdftools.exe') (Join-Path $here 'pdftools.exe') -Force
$size = (Get-Item (Join-Path $here 'pdftools.exe')).Length / 1MB
Write-Host ("[done] pdftools.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
