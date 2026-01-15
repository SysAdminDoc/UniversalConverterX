# UniversalConverter X - Installer Build Script
# Builds MSIX and MSI installers

param(
    [ValidateSet('msix', 'msi', 'all')]
    [string]$Type = 'all',
    
    [ValidateSet('Debug', 'Release')]
    [string]$Configuration = 'Release',
    
    [string]$Version = '1.0.0.0',
    
    [switch]$Sign,
    
    [string]$CertificatePath,
    
    [string]$CertificatePassword
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
$publishDir = Join-Path $rootDir "publish"
$outputDir = Join-Path $rootDir "installer\output"

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

# Ensure output directory exists
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

# Build the application first
Write-Header "Building UniversalConverter X"

Write-Step "Publishing UI application..."
dotnet publish "$rootDir\src\UniversalConverterX.UI\UniversalConverterX.UI.csproj" `
    -c $Configuration `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=false `
    -p:Version=$Version `
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
    -p:Version=$Version `
    -o "$publishDir\win-x64"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish Console application"
    exit 1
}

Write-Step "Publishing Shell Extension..."
dotnet publish "$rootDir\src\UniversalConverterX.ShellExtension\UniversalConverterX.ShellExtension.csproj" `
    -c $Configuration `
    -r win-x64 `
    -p:Version=$Version `
    -o "$publishDir\win-x64"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to publish Shell Extension"
    exit 1
}

Write-Success "Build completed"

# Build MSIX
if ($Type -eq 'msix' -or $Type -eq 'all') {
    Write-Header "Building MSIX Package"
    
    $msixDir = Join-Path $scriptDir "msix"
    $msixOutput = Join-Path $outputDir "UniversalConverterX_$Version.msix"
    
    Write-Step "Creating MSIX package..."
    
    # Copy manifest and assets
    $msixBuildDir = Join-Path $publishDir "msix-build"
    if (Test-Path $msixBuildDir) {
        Remove-Item -Recurse -Force $msixBuildDir
    }
    New-Item -ItemType Directory -Path $msixBuildDir -Force | Out-Null
    
    # Copy published files
    Copy-Item -Path "$publishDir\win-x64\*" -Destination $msixBuildDir -Recurse
    
    # Copy manifest
    Copy-Item -Path "$msixDir\Package.appxmanifest" -Destination $msixBuildDir
    
    # Create Assets folder with placeholder icons if not present
    $assetsDir = Join-Path $msixBuildDir "Assets"
    if (-not (Test-Path $assetsDir)) {
        New-Item -ItemType Directory -Path $assetsDir -Force | Out-Null
    }
    
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
            Write-Success "MSIX package created: $msixOutput"
            
            # Sign if requested
            if ($Sign -and $CertificatePath) {
                Write-Step "Signing MSIX package..."
                $signTool = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"
                if (-not (Test-Path $signTool)) {
                    $signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue | 
                                Sort-Object FullName -Descending | 
                                Select-Object -First 1 -ExpandProperty FullName
                }
                
                if ($signTool -and (Test-Path $signTool)) {
                    $signArgs = "sign /fd SHA256 /f `"$CertificatePath`""
                    if ($CertificatePassword) {
                        $signArgs += " /p `"$CertificatePassword`""
                    }
                    $signArgs += " `"$msixOutput`""
                    
                    & $signTool $signArgs.Split(' ')
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Success "MSIX package signed"
                    } else {
                        Write-Error "Failed to sign MSIX package"
                    }
                } else {
                    Write-Error "SignTool not found"
                }
            }
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
    $msiOutput = Join-Path $outputDir "UniversalConverterX_$Version.msi"
    
    Write-Step "Checking for WiX Toolset..."
    
    # Check for WiX v4 (dotnet tool) or WiX v3
    $wixExe = $null
    
    # Try WiX v4 (dotnet tool)
    try {
        $wixVersion = dotnet tool run wix --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $wixExe = "dotnet tool run wix"
        }
    } catch {}
    
    # Try WiX v3 (candle/light)
    if (-not $wixExe) {
        $candlePath = "${env:WIX}bin\candle.exe"
        if (Test-Path $candlePath) {
            $wixExe = "v3"
        }
    }
    
    if ($wixExe -eq "dotnet tool run wix") {
        Write-Step "Building with WiX v4..."
        
        Push-Location $wixDir
        try {
            & dotnet tool run wix build Product.wxs `
                -d "PublishDir=$publishDir\win-x64\" `
                -d "Version=$Version" `
                -o $msiOutput
            
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
            -d "Version=$Version" `
            -out "$wixObjDir\Product.wixobj"
        
        if ($LASTEXITCODE -eq 0) {
            # Link
            & $lightPath "$wixObjDir\Product.wixobj" `
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
    
    # Sign MSI if requested
    if ($Sign -and $CertificatePath -and (Test-Path $msiOutput)) {
        Write-Step "Signing MSI installer..."
        $signTool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue | 
                    Sort-Object FullName -Descending | 
                    Select-Object -First 1 -ExpandProperty FullName
        
        if ($signTool) {
            $signArgs = @("sign", "/fd", "SHA256", "/f", $CertificatePath)
            if ($CertificatePassword) {
                $signArgs += @("/p", $CertificatePassword)
            }
            $signArgs += @("/tr", "http://timestamp.digicert.com", "/td", "SHA256", $msiOutput)
            
            & $signTool $signArgs
            
            if ($LASTEXITCODE -eq 0) {
                Write-Success "MSI installer signed"
            } else {
                Write-Error "Failed to sign MSI"
            }
        }
    }
}

Write-Header "Build Complete"
Write-Host "Output directory: $outputDir"
Get-ChildItem $outputDir | ForEach-Object {
    $size = "{0:N2} MB" -f ($_.Length / 1MB)
    Write-Host "  • $($_.Name) ($size)"
}
