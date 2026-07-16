#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the GIS converter sidecar (GDAL ogr2ogr / gdal_translate wrapper).
  Pure-Python -- no third-party deps. Requires GDAL on the host (OSGeo4W, QGIS,
  or set $env:GDAL_BIN_DIR to a directory containing ogr2ogr.exe + gdal_translate.exe).
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
    --name gisconvert `
    --onefile --console --noconfirm --clean --log-level WARN `
    --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/gisconvert.exe') (Join-Path $here 'gisconvert.exe') -Force
$size = (Get-Item (Join-Path $here 'gisconvert.exe')).Length / 1MB
Write-Host ("[done] gisconvert.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
Write-Host "Note: requires GDAL (OSGeo4W / QGIS) at runtime." -ForegroundColor Yellow
