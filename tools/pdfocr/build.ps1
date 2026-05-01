#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the PDF OCR sidecar (ocrmypdf wrapper) into a single-file Windows exe.
  Requires Tesseract and Ghostscript installed at runtime; the sidecar
  auto-discovers their standard install dirs.
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
& $python -m pip install --quiet 'ocrmypdf>=16.0,<17' 'pikepdf>=9' Pillow

& $python -m PyInstaller `
    --name pdfocr `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all ocrmypdf `
    --collect-all pikepdf `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/pdfocr.exe') (Join-Path $here 'pdfocr.exe') -Force
$size = (Get-Item (Join-Path $here 'pdfocr.exe')).Length / 1MB
Write-Host ("[done] pdfocr.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
Write-Host "Note: requires Tesseract + Ghostscript installed (auto-discovered)." -ForegroundColor Yellow
