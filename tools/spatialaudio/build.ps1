#requires -Version 5.1
[CmdletBinding()]
param([string] $Python = 'python')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
& $Python -m PyInstaller --name spatialaudio --onefile --console --noconfirm --clean --log-level WARN --distpath (Join-Path $here 'dist') --workpath (Join-Path $here 'build') --specpath (Join-Path $here 'spec') --paths (Join-Path $here '../_lib') (Join-Path $here 'sidecar.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
Copy-Item -LiteralPath (Join-Path $here 'dist/spatialaudio.exe') -Destination (Join-Path $here 'spatialaudio.exe') -Force
Write-Host '[done] spatialaudio.exe' -ForegroundColor Green
