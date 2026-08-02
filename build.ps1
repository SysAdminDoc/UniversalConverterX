<#
.SYNOPSIS
    Build script for UniversalConverter X

.DESCRIPTION
    Builds, tests, and packages UniversalConverter X

.PARAMETER Configuration
    Build configuration (Debug or Release)

.PARAMETER Target
    Build target: Build, Test, Publish, Clean, All

.PARAMETER Architecture
    Target architecture: x64 or arm64

.EXAMPLE
    .\build.ps1 -Target Build -Configuration Release
#>

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    
    [ValidateSet("Build", "Test", "UiSmoke", "Publish", "Clean", "All")]
    [string]$Target = "Build",

    [ValidateSet("x64", "arm64")]
    [string]$Architecture = "x64",

    [string]$Version,

    [string]$FfmpegArchivePath,

    [string]$SidecarBuildReport,

    # Optional launcher used by the runtime UI gate so the swept window opens
    # somewhere isolated instead of on the operator's desktop.
    [string]$UiSmokeLauncher
)

$ErrorActionPreference = "Stop"

$SolutionPath = [System.IO.Path]::Combine($PSScriptRoot, "src", "UniversalConverterX.sln")
$RuntimeIdentifier = "win-$Architecture"
$PublishPath = if ($Architecture -eq "x64") {
    Join-Path $PSScriptRoot "publish"
} else {
    Join-Path $PSScriptRoot "publish\$RuntimeIdentifier"
}
$SrcPath = [System.IO.Path]::Combine($PSScriptRoot, "src")
$CoreTestsPath = [System.IO.Path]::Combine($PSScriptRoot, "tests", "UniversalConverterX.Core.Tests", "UniversalConverterX.Core.Tests.csproj")
$VideoScalerSmokePath = [System.IO.Path]::Combine($PSScriptRoot, "tests", "UniversalConverterX.VideoScalerSmoke", "UniversalConverterX.VideoScalerSmoke.csproj")
if ([string]::IsNullOrWhiteSpace($Version)) {
    [xml]$versionProps = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Directory.Build.props')
    $Version = [string]($versionProps.Project.PropertyGroup.Version |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -First 1)
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}

function Test-IsWindows {
    return ($IsWindows -or $env:OS -eq "Windows_NT")
}

function Invoke-Clean {
    Write-Step "Cleaning"

    dotnet clean $SolutionPath -c $Configuration --nologo -v q -p:Platform=$Architecture
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
    dotnet build $SolutionPath -c $Configuration --nologo --verbosity minimal -p:Platform=$Architecture
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed"
    }
    
    Write-Host "Build complete" -ForegroundColor Green
}

function Invoke-Test {
    Write-Step "Running Tests"
    
    if ($Architecture -eq "arm64") {
        Write-Host "Skipping execution of ARM64 test binaries on this host; x64 tests remain the runtime gate." -ForegroundColor Yellow
        return
    }

    dotnet test $CoreTestsPath -c $Configuration --nologo --no-build --no-restore --verbosity minimal -p:Platform=$Architecture
    
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed"
    }

    if (Test-IsWindows) {
        Write-Host "Running Windows AI VideoScaler capability/benchmark smoke..." -ForegroundColor Yellow
        dotnet run --project $VideoScalerSmokePath -c $Configuration --nologo --verbosity quiet
        if ($LASTEXITCODE -ne 0) {
            throw "Windows AI VideoScaler smoke failed"
        }
    }
    
    Write-Host "Tests complete" -ForegroundColor Green
}

function Invoke-UiSmoke {
    Write-Step "Runtime UI smoke"

    if ($Architecture -eq "arm64" -or -not (Test-IsWindows)) {
        Write-Host "Runtime UI smoke requires an x64 Windows host; skipping." -ForegroundColor Yellow
        return
    }

    $smokeScript = Join-Path $PSScriptRoot 'tests\ui_smoke\Invoke-UiSmoke.ps1'
    $smokeArguments = @{
        ExePath = Join-Path $PSScriptRoot (
            'src\UniversalConverterX.UI\bin\x64\' + $Configuration +
            '\net10.0-windows10.0.19041.0\UniversalConverterX.exe')
    }
    if (-not [string]::IsNullOrWhiteSpace($UiSmokeLauncher)) {
        $smokeArguments.Launcher = $UiSmokeLauncher
    }
    & $smokeScript @smokeArguments | Out-Null

    Write-Host "Runtime UI smoke complete" -ForegroundColor Green
}

function Invoke-Publish {
    Write-Step "Publishing"

    $resolvedRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\', '/')
    $resolvedPublish = [IO.Path]::GetFullPath($PublishPath)
    if (-not $resolvedPublish.StartsWith(
            $resolvedRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean publish path outside the repository: $resolvedPublish"
    }
    if (Test-Path -LiteralPath $resolvedPublish) {
        Remove-Item -LiteralPath $resolvedPublish -Recurse -Force
    }
    New-Item -ItemType Directory -Path $PublishPath -Force | Out-Null
    
    # Publish CLI
    Write-Host "Publishing CLI..." -ForegroundColor Yellow
    $cliPath = Join-Path $PublishPath "cli"
    if ($Architecture -eq "arm64") {
        dotnet publish "$SrcPath/UniversalConverterX.Console" -c $Configuration `
            -r $RuntimeIdentifier --self-contained true -o $cliPath --nologo `
            -p:Platform=$Architecture
    } else {
        dotnet publish "$SrcPath/UniversalConverterX.Console" -c $Configuration -o $cliPath --nologo
    }
    if ($LASTEXITCODE -ne 0) {
        throw "CLI publish failed"
    }
    
    # Publish UI (Windows only)
    if (Test-IsWindows) {
        Write-Host "Publishing UI..." -ForegroundColor Yellow
        $uiPath = Join-Path $PublishPath "ui"
        dotnet publish "$SrcPath/UniversalConverterX.UI/UniversalConverterX.UI.csproj" `
            -c $Configuration -r $RuntimeIdentifier --self-contained true -o $uiPath `
            --nologo -p:Platform=$Architecture
        if ($LASTEXITCODE -ne 0) {
            throw "UI publish failed"
        }

        Write-Host "Publishing FFmpeg command proxy..." -ForegroundColor Yellow
        $proxyPath = Join-Path $PublishPath "tools/ffmpeg-proxy"
        dotnet publish "$SrcPath/UniversalConverterX.FfmpegProxy/UniversalConverterX.FfmpegProxy.csproj" `
            -c $Configuration -r $RuntimeIdentifier --self-contained false -o $proxyPath `
            --nologo -p:Platform=$Architecture
        if ($LASTEXITCODE -ne 0) {
            throw "FFmpeg command proxy publish failed"
        }

        Write-Host "Publishing Explorer shell extension..." -ForegroundColor Yellow
        $shellPath = Join-Path $PublishPath "shell"
        dotnet publish "$SrcPath/UniversalConverterX.ShellExtension/UniversalConverterX.ShellExtension.csproj" `
            -c $Configuration -r $RuntimeIdentifier --self-contained false -o $shellPath `
            --nologo -p:Platform=$Architecture
        if ($LASTEXITCODE -ne 0) {
            throw "Shell extension publish failed"
        }
    }
    
    # Copy README and LICENSE
    Copy-Item "README.md" $PublishPath -ErrorAction SilentlyContinue

    Write-Host "Staging presets..." -ForegroundColor Yellow
    $presetsPath = Join-Path $PublishPath 'presets'
    New-Item -ItemType Directory -Path $presetsPath -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'presets') -Filter '*.preset.xml' |
        Copy-Item -Destination $presetsPath -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'presets\README.md') `
        -Destination $presetsPath -Force

    $toolsPath = Join-Path $PublishPath 'tools\bin'
    New-Item -ItemType Directory -Path $toolsPath -Force | Out-Null
    if ($Architecture -eq 'x64') {
        Write-Host "Staging pinned FFmpeg..." -ForegroundColor Yellow
        $ffmpegArguments = @{
            ManifestPath = (Join-Path $PSScriptRoot 'tools\ffmpeg\bundle.json')
            DestinationPath = $toolsPath
        }
        if (-not [string]::IsNullOrWhiteSpace($FfmpegArchivePath)) {
            $ffmpegArguments.ArchivePath = $FfmpegArchivePath
        }
        & (Join-Path $PSScriptRoot 'installer\Stage-PinnedFfmpeg.ps1') @ffmpegArguments |
            Out-Null
    }

    Write-Host "Staging sidecar readiness..." -ForegroundColor Yellow
    $readinessScript = Join-Path $PSScriptRoot 'tools\release\sidecar_readiness.py'
    $readinessArguments = @(
        $readinessScript,
        'stage',
        '--repo-root', $PSScriptRoot,
        '--stage-root', $PublishPath,
        '--source-tools', (Join-Path $PSScriptRoot 'tools'),
        '--architecture', $RuntimeIdentifier,
        '--product-version', $Version
    )
    if (-not [string]::IsNullOrWhiteSpace($SidecarBuildReport)) {
        $readinessArguments += @('--build-report', $SidecarBuildReport)
    }
    & python @readinessArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Sidecar readiness staging failed"
    }
    & python $readinessScript verify `
        --stage-root $PublishPath `
        --source-tools (Join-Path $PSScriptRoot 'tools') `
        --architecture $RuntimeIdentifier
    if ($LASTEXITCODE -ne 0) {
        throw "Sidecar readiness verification failed"
    }

    if ($Architecture -eq "arm64") {
        Write-Host "Auditing ARM64 artifacts and sidecar compatibility..." -ForegroundColor Yellow
        $auditScript = Join-Path $PSScriptRoot "tools\Test-Arm64Publish.ps1"
        $compatibilityPath = Join-Path $PublishPath "compatibility\arm64-publish.json"
        & $auditScript -PublishRoot $PublishPath `
            -SourceToolsRoot (Join-Path $PSScriptRoot "tools") `
            -OutputPath $compatibilityPath
        if ($LASTEXITCODE -ne 0) {
            throw "ARM64 artifact audit failed"
        }
    }
    
    Write-Host "Publish complete ($RuntimeIdentifier): $PublishPath" -ForegroundColor Green
}

# Main execution
try {
    Push-Location $PSScriptRoot
    
    switch ($Target) {
        "Clean" { Invoke-Clean }
        "Build" { Invoke-Build }
        "Test" { Invoke-Build; Invoke-Test }
        "UiSmoke" { Invoke-Build; Invoke-UiSmoke }
        "Publish" { Invoke-Build; Invoke-Publish }
        "All" { Invoke-Clean; Invoke-Build; Invoke-Test; Invoke-UiSmoke; Invoke-Publish }
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
