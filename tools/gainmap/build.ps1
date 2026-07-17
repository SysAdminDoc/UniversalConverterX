#requires -Version 5.1
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
& $python -m PyInstaller --name gainmap --onefile --console --noconfirm --clean --log-level WARN --paths . --paths ../_lib --add-data 'runtime.bundle.json;.' sidecar.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Copy-Item (Join-Path $here 'dist/gainmap.exe') (Join-Path $here 'gainmap.exe') -Force
$size = (Get-Item (Join-Path $here 'gainmap.exe')).Length / 1MB
Write-Host ("[done] gainmap.exe ({0:N1} MB)" -f $size) -ForegroundColor Green
