#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the exiftool-meta sidecar into a single-file Windows executable.
  Sidecar shells out to exiftool.exe — download the Windows portable build
  from exiftool.org and drop exiftool.exe next to this script or under
  ../_bin/ before shipping.
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

& $python -m PyInstaller --name exiftool-meta --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/exiftool-meta.exe') (Join-Path $here 'exiftool-meta.exe') -Force
$size = (Get-Item (Join-Path $here 'exiftool-meta.exe')).Length / 1MB
Write-Host ("[done] exiftool-meta.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here 'exiftool.exe')) -and `
    -not (Test-Path (Join-Path $here '..\_bin\exiftool.exe'))) {
    Write-Warning "[exiftool-meta] No exiftool.exe binary found next to the sidecar or under ../_bin/. Download the Windows portable build from exiftool.org before shipping."
}
