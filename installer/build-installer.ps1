# UniversalConverter X - Installer Build Script
# Builds unsigned MSIX, MSI, and portable ZIP artifacts

param(
    [ValidateSet('msix', 'msi', 'portable', 'all')]
    [string]$Type = 'all',
    
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    
    [string]$Version = '2.32.0.0',

    [string]$FfmpegArchivePath
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$publishDir = Join-Path $rootDir "publish"
$outputDir = Join-Path $rootDir "installer\output"
$minimumDotnetRuntime = [Version]'10.0.9'
$parsedVersion = [Version]$Version
$semanticVersion = $parsedVersion.ToString(3)
$msixVersion = $parsedVersion.ToString(4)
$releaseTag = "v$semanticVersion"

$installedDotnetRuntimes = @(dotnet --list-runtimes 2>$null |
    Where-Object { $_ -match '^Microsoft\.NETCore\.App\s+(\d+\.\d+\.\d+)' } |
    ForEach-Object { [Version]$Matches[1] })
$latestDotnetRuntime = $installedDotnetRuntimes |
    Where-Object { $_.Major -eq 10 } |
    Sort-Object -Descending |
    Select-Object -First 1
if ($null -eq $latestDotnetRuntime -or $latestDotnetRuntime -lt $minimumDotnetRuntime) {
    throw "UniversalConverterX installer builds require .NET runtime 10.0.9 or newer. Install the current .NET 10 SDK/runtime before publishing."
}

# Colors for output
function Write-Header($text) {
    Write-Host "`n═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " $text" -ForegroundColor Cyan
    Write-Host "═══════════════════════════════════════════════════════════`n" -ForegroundColor Cyan
}

function Write-Step($text) {
    Write-Host "→ $text" -ForegroundColor Yellow
}

function Write-Success($text) {
    Write-Host "✓ $text" -ForegroundColor Green
}

function Write-Error($text) {
    Write-Host "✗ $text" -ForegroundColor Red
}

function Write-PresetWixFragment {
    param(
        [Parameter(Mandatory=$true)][string]$PresetDirectory,
        [Parameter(Mandatory=$true)][string]$OutputPath
    )

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('<?xml version="1.0" encoding="UTF-8"?>')
    $lines.Add('<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">')
    $lines.Add('  <Fragment>')
    $lines.Add('    <ComponentGroup Id="PresetFiles" Directory="PresetsFolder">')

    $index = 0
    $readme = Join-Path $PresetDirectory 'README.md'
    if (Test-Path $readme) {
        $lines.Add('      <Component Id="PresetFile_0000" Guid="*">')
        $lines.Add('        <File Id="PresetFilePayload_0000" Source="$(var.PublishDir)presets\README.md" KeyPath="yes" />')
        $lines.Add('      </Component>')
        $index = 1
    }

    Get-ChildItem -Path $PresetDirectory -Filter '*.preset.xml' | Sort-Object Name | ForEach-Object {
        $componentId = 'PresetFile_{0:0000}' -f $index
        $fileId = 'PresetFilePayload_{0:0000}' -f $index
        $source = '$(var.PublishDir)presets\{0}' -f $_.Name
        $escapedSource = [Security.SecurityElement]::Escape($source)
        $lines.Add("      <Component Id=`"$componentId`" Guid=`"*`">")
        $lines.Add("        <File Id=`"$fileId`" Source=`"$escapedSource`" KeyPath=`"yes`" />")
        $lines.Add('      </Component>')
        $index++
    }

    $lines.Add('    </ComponentGroup>')
    $lines.Add('  </Fragment>')
    $lines.Add('</Wix>')
    Set-Content -Path $OutputPath -Value $lines -Encoding UTF8
}

# Ensure output directory exists
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$msixOutput = Join-Path $outputDir "UniversalConverterX_$semanticVersion.msix"
$msiOutput = Join-Path $outputDir "UniversalConverterX_$semanticVersion.msi"
$portableOutput = Join-Path $outputDir "UniversalConverterX_$semanticVersion`_portable.zip"
$releaseManifest = Join-Path $outputDir "UniversalConverterX_$semanticVersion.release.json"
$wingetOutput = Join-Path $outputDir 'winget\manifests\s\SysAdminDoc\UniversalConverterX'
$staleOutputs = @($releaseManifest)
if ($Type -eq 'msix' -or $Type -eq 'all') { $staleOutputs += $msixOutput }
if ($Type -eq 'msi' -or $Type -eq 'all') { $staleOutputs += $msiOutput }
if ($Type -eq 'portable' -or $Type -eq 'all') { $staleOutputs += $portableOutput }
foreach ($staleOutput in $staleOutputs) {
    if (Test-Path -LiteralPath $staleOutput) {
        Remove-Item -LiteralPath $staleOutput -Force
    }
}

# Build the application first
Write-Header "Building UniversalConverter X"

Write-Step "Publishing UI application..."
dotnet publish "$rootDir\src\UniversalConverterX.UI\UniversalConverterX.UI.csproj" `
    -c $Configuration `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=false `
    -p:Version=$semanticVersion `
    -o "$publishDir\win-x64"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish UI application"
    exit 1
}

Write-Step "Publishing Console application..."
dotnet publish "$rootDir\src\UniversalConverterX.Console\UniversalConverterX.Console.csproj" `
    -c $Configuration `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=false `
    -p:Version=$semanticVersion `
    -o "$publishDir\win-x64"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish Console application"
    exit 1
}

Write-Step "Publishing Shell Extension..."
dotnet publish "$rootDir\src\UniversalConverterX.ShellExtension\UniversalConverterX.ShellExtension.csproj" `
    -c $Configuration `
    -r win-x64 `
    -p:Version=$semanticVersion `
    -o "$publishDir\win-x64"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish Shell Extension"
    exit 1
}

Write-Step "Publishing FFmpeg command proxy..."
dotnet publish "$rootDir\src\UniversalConverterX.FfmpegProxy\UniversalConverterX.FfmpegProxy.csproj" `
    -c $Configuration `
    -r win-x64 `
    --self-contained false `
    -p:PublishSingleFile=false `
    -p:Version=$semanticVersion `
    -o "$publishDir\win-x64\tools\ffmpeg-proxy"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish FFmpeg command proxy"
    exit 1
}

Write-Success "Build completed"

# Stage preset XML files alongside the published binaries so WiX can pull
# them via $(var.PublishDir)presets\<file>.preset.xml without traversing
# back out of publish/.
Write-Step "Staging presets..."
$presetsSrc = Join-Path $rootDir 'presets'
$presetsDst = Join-Path $publishDir 'win-x64\presets'
if (-not (Test-Path $presetsDst)) { New-Item -ItemType Directory -Path $presetsDst -Force | Out-Null }
Get-ChildItem -Path $presetsSrc -Filter '*.preset.xml' | Copy-Item -Destination $presetsDst -Force
Copy-Item -Path (Join-Path $presetsSrc 'README.md') -Destination $presetsDst -Force
$presetCount = (Get-ChildItem -Path $presetsDst -Filter '*.preset.xml' | Measure-Object).Count
Write-Success "Staged $presetCount preset(s) -> $presetsDst"

$presetFragmentPath = Join-Path $scriptDir 'wix\PresetFiles.generated.wxs'
Write-Step "Generating WiX preset fragment..."
Write-PresetWixFragment -PresetDirectory $presetsDst -OutputPath $presetFragmentPath
Write-Success "Generated $presetFragmentPath"

# Bundle the exact FFmpeg build declared in tools/ffmpeg/bundle.json. The
# staging script verifies SHA-256 before extracting any executable.
Write-Step "Staging pinned FFmpeg..."
$ffmpegStageArguments = @{
    ManifestPath = (Join-Path $rootDir 'tools\ffmpeg\bundle.json')
    DestinationPath = (Join-Path $publishDir 'win-x64\tools\bin')
}
if (-not [string]::IsNullOrWhiteSpace($FfmpegArchivePath)) {
    $ffmpegStageArguments.ArchivePath = $FfmpegArchivePath
}
& (Join-Path $scriptDir 'Stage-PinnedFfmpeg.ps1') @ffmpegStageArguments | Out-Null
Write-Success "Staged FFmpeg 8.1.2 -> $($ffmpegStageArguments.DestinationPath)"

# Build a directly runnable, unsigned portable archive. This is the WinGet
# installer source and remains usable even when Windows refuses an unsigned
# MSIX sideload.
if ($Type -eq 'portable' -or $Type -eq 'all') {
    Write-Header "Building Portable ZIP"
    Compress-Archive -Path "$publishDir\win-x64\*" -DestinationPath $portableOutput -CompressionLevel Optimal -Force
    if (-not (Test-Path -LiteralPath $portableOutput -PathType Leaf) -or
        (Get-Item -LiteralPath $portableOutput).Length -eq 0) {
        throw "Portable ZIP was not produced: $portableOutput"
    }

    Write-Success "Portable ZIP created: $portableOutput"
    Write-Step "Generating WinGet manifest content..."
    & (Join-Path $scriptDir 'New-WinGetManifest.ps1') `
        -Version $semanticVersion `
        -PortableArchivePath $portableOutput `
        -ReleaseTag $releaseTag `
        -OutputDirectory $wingetOutput | Out-Null
    Write-Success "WinGet manifests created under: $wingetOutput\$semanticVersion"
}

# Build MSIX
if ($Type -eq 'msix' -or $Type -eq 'all') {
    Write-Header "Building MSIX Package"
    
    $msixDir = Join-Path $scriptDir "msix"
    Write-Step "Creating MSIX package..."
    
    # Copy manifest and assets
    $msixBuildDir = Join-Path $publishDir "msix-build"
    if (Test-Path $msixBuildDir) {
        Remove-Item -Recurse -Force $msixBuildDir
    }
    New-Item -ItemType Directory -Path $msixBuildDir -Force | Out-Null
    
    # Copy published files
    Copy-Item -Path "$publishDir\win-x64\*" -Destination $msixBuildDir -Recurse
    
    # Copy and stamp the manifest. The source manifest intentionally carries
    # the current release version for consistency tests; staging always uses
    # the requested build version.
    $stagedManifestPath = Join-Path $msixBuildDir 'AppxManifest.xml'
    Copy-Item -Path "$msixDir\Package.appxmanifest" -Destination $stagedManifestPath
    [xml]$stagedManifest = Get-Content -LiteralPath $stagedManifestPath
    $stagedManifest.Package.Identity.Version = $msixVersion
    $stagedManifest.Save($stagedManifestPath)
    
    # Generate correctly sized package assets from the repository logo.
    $assetsDir = Join-Path $msixBuildDir "Assets"
    & (Join-Path $scriptDir 'New-MsixAssets.ps1') `
        -SourceImage (Join-Path $rootDir 'icon.png') `
        -OutputDirectory $assetsDir
    
    # Use MakeAppx to create the package
    $makeAppx = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.0.22621.0\x64\makeappx.exe"
    if (-not (Test-Path $makeAppx)) {
        $makeAppx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue | 
                    Sort-Object FullName -Descending | 
                    Select-Object -First 1 -ExpandProperty FullName
    }
    
    if ($makeAppx -and (Test-Path $makeAppx)) {
        & $makeAppx pack /d $msixBuildDir /p $msixOutput /o
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Unsigned MSIX package created: $msixOutput"
        } else {
            Write-Error "Failed to create MSIX package"
        }
    } else {
        Write-Error "MakeAppx not found. Install Windows SDK."
    }
}

# Build MSI
if ($Type -eq 'msi' -or $Type -eq 'all') {
    Write-Header "Building MSI Installer"
    
    $wixDir = Join-Path $scriptDir "wix"
    Write-Step "Checking for WiX Toolset..."
    
    # Check for WiX v4 (dotnet tool) or WiX v3
    $wixExe = $null
    
    # Try WiX v4+ from a repository tool manifest.
    try {
        $wixVersion = dotnet tool run wix --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $wixExe = 'local-tool'
        }
    } catch {}

    # Fall back to the normal global-tool command. `dotnet tool run` does not
    # discover tools installed with `--global` even when `wix` is on PATH.
    if (-not $wixExe) {
        try {
            $wixVersion = wix --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                $wixExe = 'global-tool'
            }
        } catch {}
    }
    
    # Try WiX v3 (candle/light)
    if (-not $wixExe) {
        $candlePath = "${env:WIX}bin\candle.exe"
        if (Test-Path $candlePath) {
            $wixExe = "v3"
        }
    }
    
    if ($wixExe -eq 'local-tool' -or $wixExe -eq 'global-tool') {
        Write-Step "Building with WiX v4..."
        
        Push-Location $wixDir
        try {
            $wixArguments = @(
                'build', 'Product.wxs', $presetFragmentPath,
                '-d', "PublishDir=$publishDir\win-x64\",
                '-d', "Version=$semanticVersion",
                '-o', $msiOutput
            )
            if ($wixExe -eq 'local-tool') {
                & dotnet tool run wix @wixArguments
            } else {
                & wix @wixArguments
            }
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "MSI installer created: $msiOutput"
            } else {
                Write-Error "Failed to build MSI"
            }
        } finally {
            Pop-Location
        }
    } elseif ($wixExe -eq "v3") {
        Write-Step "Building with WiX v3..."
        
        $candlePath = "${env:WIX}bin\candle.exe"
        $lightPath = "${env:WIX}bin\light.exe"
        $wixObjDir = Join-Path $wixDir "obj"
        
        if (-not (Test-Path $wixObjDir)) {
            New-Item -ItemType Directory -Path $wixObjDir -Force | Out-Null
        }
        
        # Compile
        & $candlePath "$wixDir\Product.wxs" `
            -d "PublishDir=$publishDir\win-x64\" `
            -d "Version=$semanticVersion" `
            -out "$wixObjDir\Product.wixobj"
        if ($LASTEXITCODE -eq 0) {
            & $candlePath $presetFragmentPath `
                -d "PublishDir=$publishDir\win-x64\" `
                -d "Version=$Version" `
                -out "$wixObjDir\PresetFiles.generated.wixobj"
        }
        
        if ($LASTEXITCODE -eq 0) {
            # Link
            & $lightPath "$wixObjDir\Product.wixobj" "$wixObjDir\PresetFiles.generated.wixobj" `
                -ext WixUIExtension `
                -out $msiOutput
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "MSI installer created: $msiOutput"
            } else {
                Write-Error "Failed to link MSI"
            }
        } else {
            Write-Error "Failed to compile WiX source"
        }
    } else {
        Write-Error "WiX Toolset not found. Install WiX v4 (dotnet tool install wix) or WiX v3."
    }
    
}

# Generate release metadata only after packaging so every digest describes the
# exact bytes that will be uploaded. Missing requested artifacts
# are fatal; stale files from a previous build must never satisfy this check.
$releaseArtifacts = New-Object System.Collections.Generic.List[string]
if ($Type -eq 'msix' -or $Type -eq 'all') {
    if (-not (Test-Path -LiteralPath $msixOutput -PathType Leaf) -or
        (Get-Item -LiteralPath $msixOutput).Length -eq 0) {
        throw "Requested MSIX artifact was not produced: $msixOutput"
    }
    $releaseArtifacts.Add($msixOutput) | Out-Null
}
if ($Type -eq 'msi' -or $Type -eq 'all') {
    if (-not (Test-Path -LiteralPath $msiOutput -PathType Leaf) -or
        (Get-Item -LiteralPath $msiOutput).Length -eq 0) {
        throw "Requested MSI artifact was not produced: $msiOutput"
    }
    $releaseArtifacts.Add($msiOutput) | Out-Null
}
if ($Type -eq 'portable' -or $Type -eq 'all') {
    if (-not (Test-Path -LiteralPath $portableOutput -PathType Leaf) -or
        (Get-Item -LiteralPath $portableOutput).Length -eq 0) {
        throw "Requested portable artifact was not produced: $portableOutput"
    }
    $releaseArtifacts.Add($portableOutput) | Out-Null
}

$manifestScript = Join-Path $scriptDir 'New-ReleaseManifest.ps1'
Write-Step "Generating release manifest..."
& $manifestScript `
    -Version $semanticVersion `
    -ArtifactPath $releaseArtifacts.ToArray() `
    -BundleRoot (Join-Path $publishDir 'win-x64') `
    -PresetRoot $presetsDst `
    -OutputPath $releaseManifest `
    -RuntimeIdentifier 'win-x64' | Out-Null
Write-Success "Release manifest created: $releaseManifest"

Write-Header "Build Complete"
Write-Host "Output directory: $outputDir"
Get-ChildItem $outputDir | ForEach-Object {
    $size = "{0:N2} MB" -f ($_.Length / 1MB)
    Write-Host "  • $($_.Name) ($size)"
}
