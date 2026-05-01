#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the RAW photo developer sidecar (rawpy + Pillow) into a single-file Windows exe.
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
& $python -m pip install --quiet 'rawpy>=0.21,<1' 'Pillow>=10' numpy

& $python -m PyInstaller `
    --name rawphoto `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-binaries rawpy `
    --hidden-import PIL `
    --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/rawphoto.exe') (Join-Path $here 'rawphoto.exe') -Force
$size = (Get-Item (Join-Path $here 'rawphoto.exe')).Length / 1MB
Write-Host ("[done] rawphoto.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
