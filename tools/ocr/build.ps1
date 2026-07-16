#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the OCR sidecar (Tesseract wrapper) into a single-file Windows exe.
  Pure-Python -- no third-party deps. Requires Tesseract installed at runtime.
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
    --name ocr `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/ocr.exe') (Join-Path $here 'ocr.exe') -Force
$size = (Get-Item (Join-Path $here 'ocr.exe')).Length / 1MB
Write-Host ("[done] ocr.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
Write-Host "Note: requires Tesseract on PATH or installed at C:\Program Files\Tesseract-OCR\." -ForegroundColor Yellow
