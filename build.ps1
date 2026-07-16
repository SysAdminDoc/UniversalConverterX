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

$SolutionPath = [System.IO.Path]::Combine($PSScriptRoot, "src", "UniversalConverterX.sln")
$PublishPath = Join-Path $PSScriptRoot "publish"
$SrcPath = [System.IO.Path]::Combine($PSScriptRoot, "src")
$CoreTestsPath = [System.IO.Path]::Combine($PSScriptRoot, "tests", "UniversalConverterX.Core.Tests", "UniversalConverterX.Core.Tests.csproj")

function Write-Step {
    param([string]$Message)
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}

function Test-IsWindows {
    return ($IsWindows -or $env:OS -eq "Windows_NT")
}

function Invoke-Clean {
    Write-Step "Cleaning"

    dotnet clean $SolutionPath -c $Configuration --nologo -v q -p:Platform=x64
    if ($LASTEXITCODE -ne 0) {
        throw "Clean failed"
    }
    
    if (Test-Path $PublishPath) {
        Remove-Item $PublishPath -Recurse -Force
    }
    
    Get-ChildItem -Path $PSScriptRoot -Include bin,obj -Recurse -Directory | 
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    
    Write-Host "Clean complete" -ForegroundColor Green
}

function Invoke-Build {
    Write-Step "Building ($Configuration)"

    # All projects are SDK-style. The .NET 10 SDK now carries the WinUI/XAML
    # targets required for a headless x64 build, so invoking an older Visual
    # Studio MSBuild would incorrectly fail to resolve Microsoft.NET.Sdk.
    dotnet build $SolutionPath -c $Configuration --nologo --verbosity minimal -p:Platform=x64
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed"
    }
    
    Write-Host "Build complete" -ForegroundColor Green
}

function Invoke-Test {
    Write-Step "Running Tests"
    
    dotnet test $CoreTestsPath -c $Configuration --nologo --no-build --no-restore --verbosity minimal -p:Platform=x64
    
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
    dotnet publish "$SrcPath/UniversalConverterX.Console" -c $Configuration -o $cliPath --nologo
    if ($LASTEXITCODE -ne 0) {
        throw "CLI publish failed"
    }
    
    # Publish UI (Windows only)
    if (Test-IsWindows) {
        Write-Host "Publishing UI..." -ForegroundColor Yellow
        $uiPath = Join-Path $PublishPath "ui"
        dotnet publish "$SrcPath/UniversalConverterX.UI/UniversalConverterX.UI.csproj" `
            -c $Configuration -r win-x64 --self-contained true -o $uiPath `
            --nologo -p:Platform=x64
        if ($LASTEXITCODE -ne 0) {
            throw "UI publish failed"
        }

        Write-Host "Publishing FFmpeg command proxy..." -ForegroundColor Yellow
        $proxyPath = Join-Path $PublishPath "tools/ffmpeg-proxy"
        dotnet publish "$SrcPath/UniversalConverterX.FfmpegProxy/UniversalConverterX.FfmpegProxy.csproj" `
            -c $Configuration -r win-x64 --self-contained false -o $proxyPath --nologo
        if ($LASTEXITCODE -ne 0) {
            throw "FFmpeg command proxy publish failed"
        }
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
