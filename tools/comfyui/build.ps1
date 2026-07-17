#requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$arguments = @('-3.12', '-m', 'PyInstaller', '--name', 'comfyui', '--onefile', '--console', '--noconfirm', '--clean', '--log-level', 'WARN', '--distpath', (Join-Path $here 'dist'), '--workpath', (Join-Path $here 'build'), '--specpath', (Join-Path $here 'spec'), '--paths', (Join-Path $here '../_lib'), (Join-Path $here 'sidecar.py'))
& py @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
Copy-Item -LiteralPath (Join-Path $here 'dist/comfyui.exe') -Destination (Join-Path $here 'comfyui.exe') -Force
Write-Host '[done] comfyui.exe' -ForegroundColor Green
