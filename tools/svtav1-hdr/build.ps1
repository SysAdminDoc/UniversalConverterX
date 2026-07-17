#requires -Version 5.1
[CmdletBinding()]
param([switch]$Clean)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
if ($Clean) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .venv, *.spec }
if (-not (Test-Path .venv)) { python -m venv .venv }
$python = Join-Path $here '.venv/Scripts/python.exe'
& $python -m pip install --quiet --upgrade pip pyinstaller
& $python -m PyInstaller --name svtav1-hdr --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
Copy-Item (Join-Path $here 'dist/svtav1-hdr.exe') (Join-Path $here 'svtav1-hdr.exe') -Force
$size = (Get-Item (Join-Path $here 'svtav1-hdr.exe')).Length / 1MB
Write-Host ("[done] svtav1-hdr.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
