#requires -Version 5.1
<#
.SYNOPSIS
  Freeze the 3D mesh converter sidecar (trimesh-based) into a single-file Windows exe.
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
# trimesh + optional fast-load deps. lxml for COLLADA, networkx for some
# graph ops, pyglet for GLTF scene assembly.
& $python -m pip install --quiet 'trimesh>=4.0,<5' lxml networkx pillow pyglet shapely

& $python -m PyInstaller `
    --name meshconvert `
    --onefile --console --noconfirm --clean --log-level WARN `
    --collect-all trimesh `
    --hidden-import lxml `
    --hidden-import networkx `
    --paths . --paths ../_lib sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/meshconvert.exe') (Join-Path $here 'meshconvert.exe') -Force
$size = (Get-Item (Join-Path $here 'meshconvert.exe')).Length / 1MB
Write-Host ("[done] meshconvert.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
