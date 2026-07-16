#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the vvc-encoder sidecar into a single-file Windows executable.
  The sidecar shells out to vvencapp; download from
  github.com/fraunhoferhhi/vvenc/releases and drop vvencapp.exe next
  to this script or under ../_bin/ before shipping.
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

& $python -m PyInstaller --name vvc-encoder --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/vvc-encoder.exe') (Join-Path $here 'vvc-encoder.exe') -Force
$size = (Get-Item (Join-Path $here 'vvc-encoder.exe')).Length / 1MB
Write-Host ("[done] vvc-encoder.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here 'vvencapp.exe')) -and `
    -not (Test-Path (Join-Path $here '..\_bin\vvencapp.exe'))) {
    Write-Warning "[vvc-encoder] No vvencapp.exe found next to the sidecar or under ../_bin/. Download from github.com/fraunhoferhhi/vvenc/releases before shipping."
}
