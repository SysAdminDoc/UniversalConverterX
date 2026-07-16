#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the hdrplus-rpu sidecar into a single-file Windows executable.
  The sidecar shells out to the hdr10plus_tool Rust binary; download it
  from github.com/quietvoid/hdr10plus_tool/releases and drop
  hdr10plus_tool.exe next to this script or under ../_bin/ before
  shipping the frozen sidecar.
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

& $python -m PyInstaller --name hdrplus-rpu --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/hdrplus-rpu.exe') (Join-Path $here 'hdrplus-rpu.exe') -Force
$size = (Get-Item (Join-Path $here 'hdrplus-rpu.exe')).Length / 1MB
Write-Host ("[done] hdrplus-rpu.exe ({0:N1} MB)" -f $size) -ForegroundColor Green

if (-not (Test-Path (Join-Path $here 'hdr10plus_tool.exe')) -and `
    -not (Test-Path (Join-Path $here '..\_bin\hdr10plus_tool.exe'))) {
    Write-Warning "[hdrplus-rpu] No hdr10plus_tool.exe binary found next to the sidecar or under ../_bin/. Download it from github.com/quietvoid/hdr10plus_tool/releases before shipping."
}
