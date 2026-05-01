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

function Resolve-MSBuild {
    $vsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vsWhere) {
        $fromVsWhere = & $vsWhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\Current\Bin\amd64\MSBuild.exe" |
            Select-Object -First 1
        if ($fromVsWhere -and (Test-Path $fromVsWhere)) {
            return $fromVsWhere
        }

        $fromVsWhere = & $vsWhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\Current\Bin\MSBuild.exe" |
            Select-Object -First 1
        if ($fromVsWhere -and (Test-Path $fromVsWhere)) {
            return $fromVsWhere
        }
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\amd64\MSBuild.exe"),
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\amd64\MSBuild.exe"),
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\amd64\MSBuild.exe"),
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\amd64\MSBuild.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

function Invoke-VSBuild {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectPath,
        [string]$Target = "Build",
        [switch]$Restore,
        [hashtable]$Properties = @{}
    )

    $msbuild = Resolve-MSBuild
    if (-not $msbuild) {
        throw "Visual Studio MSBuild with Windows App SDK build tools is required to build the WinUI project. Install Visual Studio or Build Tools with the Windows application development workload."
    }

    $args = @(
        $ProjectPath,
        "/t:$Target",
        "/p:Configuration=$Configuration",
        "/p:Platform=x64",
        "/nologo",
        "/v:minimal",
        "/m"
    )

    if ($Restore) {
        $args += "/restore"
    }

    foreach ($entry in $Properties.GetEnumerator()) {
        $args += "/p:$($entry.Key)=$($entry.Value)"
    }

    & $msbuild @args
    if ($LASTEXITCODE -ne 0) {
        throw "MSBuild failed for $ProjectPath"
    }
}

function Invoke-Clean {
    Write-Step "Cleaning"
    
    if (Test-IsWindows) {
        Invoke-VSBuild $SolutionPath -Target "Clean"
    }
    else {
        dotnet clean $SolutionPath -c $Configuration --nologo -v q
        if ($LASTEXITCODE -ne 0) {
            throw "Clean failed"
        }
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
    
    if (Test-IsWindows) {
        Invoke-VSBuild $SolutionPath -Target "Build" -Restore
    }
    else {
        dotnet restore $SolutionPath --nologo -v q
        dotnet build $SolutionPath -c $Configuration --nologo --no-restore

        if ($LASTEXITCODE -ne 0) {
            throw "Build failed"
        }
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
    
    # Publish UI (Windows only)
    if (Test-IsWindows) {
        Write-Host "Publishing UI..." -ForegroundColor Yellow
        $uiPath = Join-Path $PublishPath "ui"
        Invoke-VSBuild "$SrcPath/UniversalConverterX.UI/UniversalConverterX.UI.csproj" -Target "Publish" -Restore -Properties @{
            RuntimeIdentifier = "win-x64"
            SelfContained = "true"
            PublishDir = "$uiPath\"
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
