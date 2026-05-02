#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the ab-av1 sidecar into a single-file Windows executable.
  The sidecar shells out to the ab-av1 Rust binary; download it from
  github.com/alexheretic/ab-av1/releases and drop ab-av1.exe next to
  this script or under ../_bin/ before shipping the frozen sidecar.
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

& $python -m PyInstaller --name ab-av1 --onefile --console --noconfirm --clean --log-level WARN --paths . sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

# Sidecar shim is named ab-av1-sidecar so it doesn't collide with the upstream
# ab-av1 binary that lives next to it.
Copy-Item (Join-Path $here 'dist/ab-av1.exe') (Join-Path $here 'ab-av1-sidecar.exe') -Force
$size = (Get-Item (Join-Path $here 'ab-av1-sidecar.exe')).Length / 1MB
Write-Host ("[done] ab-av1-sidecar.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here 'ab-av1.exe')) -and `
    -not (Test-Path (Join-Path $here '..\_bin\ab-av1.exe'))) {
    Write-Warning "[ab-av1] No ab-av1.exe binary found next to the sidecar or under ../_bin/. Download it from github.com/alexheretic/ab-av1/releases before shipping."
}
