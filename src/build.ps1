<#
.SYNOPSIS
    Build script for UniversalConverter X

.DESCRIPTION
    Builds, tests, and packages UniversalConverter X

.PARAMETER Configuration
    Build configuration (Debug or Release)

.PARAMETER Target
    Build target: Build, Test, Publish, Clean, All

.EXAMPLE
    .\build.ps1 -Target Build -Configuration Release
#>

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    
    [ValidateSet("Build", "Test", "Publish", "Clean", "All")]
    [string]$Target = "Build"
)

$ErrorActionPreference = "Stop"

$SolutionPath = Join-Path $PSScriptRoot "UniversalConverterX.sln"
$PublishPath = Join-Path $PSScriptRoot "publish"

function Write-Step {
    param([string]$Message)
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}

function Invoke-Clean {
    Write-Step "Cleaning"
    
    dotnet clean $SolutionPath -c $Configuration --nologo -v q
    
    if (Test-Path $PublishPath) {
        Remove-Item $PublishPath -Recurse -Force
    }
    
    Get-ChildItem -Path $PSScriptRoot -Include bin,obj -Recurse -Directory | 
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Host "Clean complete" -ForegroundColor Green
}

function Invoke-Build {
    Write-Step "Building ($Configuration)"
    
    dotnet restore $SolutionPath --nologo -v q
    dotnet build $SolutionPath -c $Configuration --nologo --no-restore
    
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed"
    }
    
    Write-Host "Build complete" -ForegroundColor Green
}

function Invoke-Test {
    Write-Step "Running Tests"
    
    dotnet test $SolutionPath -c $Configuration --nologo --no-build --verbosity normal
    
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed"
    }
    
    Write-Host "Tests complete" -ForegroundColor Green
}

function Invoke-Publish {
    Write-Step "Publishing"
    
    # Create publish directory
    New-Item -ItemType Directory -Path $PublishPath -Force | Out-Null
    
    # Publish CLI
    Write-Host "Publishing CLI..." -ForegroundColor Yellow
    $cliPath = Join-Path $PublishPath "cli"
    dotnet publish "src/UniversalConverterX.Console" -c $Configuration -o $cliPath --nologo
    
    # Publish UI (Windows only)
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        Write-Host "Publishing UI..." -ForegroundColor Yellow
        $uiPath = Join-Path $PublishPath "ui"
        dotnet publish "src/UniversalConverterX.UI" -c $Configuration -r win-x64 --self-contained -o $uiPath --nologo
    }
    
    # Copy README and LICENSE
    Copy-Item "README.md" $PublishPath -ErrorAction SilentlyContinue
    
    # Create tools directory
    $toolsPath = Join-Path $PublishPath "tools/bin"
    New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null
    
    Write-Host "Publish complete: $PublishPath" -ForegroundColor Green
}

# Main execution
try {
    Push-Location $PSScriptRoot
    
    switch ($Target) {
        "Clean" { Invoke-Clean }
        "Build" { Invoke-Build }
        "Test" { Invoke-Build; Invoke-Test }
        "Publish" { Invoke-Build; Invoke-Publish }
        "All" { Invoke-Clean; Invoke-Build; Invoke-Test; Invoke-Publish }
    }
    
    Write-Host "`nSuccess!" -ForegroundColor Green
}
catch {
    Write-Host "`nError: $_" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
