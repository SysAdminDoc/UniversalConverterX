[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$PortableArchivePath,
    [Parameter(Mandatory=$true)][string]$ReleaseTag,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$packageIdentifier = 'SysAdminDoc.UniversalConverterX'
$manifestVersion = '1.12.0'

if (-not (Test-Path -LiteralPath $PortableArchivePath -PathType Leaf)) {
    throw "Portable archive not found: $PortableArchivePath"
}
if ((Get-Item -LiteralPath $PortableArchivePath).Length -eq 0) {
    throw "Portable archive is empty: $PortableArchivePath"
}

$archiveName = Split-Path -Leaf $PortableArchivePath
$sha256 = (Get-FileHash -LiteralPath $PortableArchivePath -Algorithm SHA256).Hash.ToUpperInvariant()
$releaseUrl = "https://github.com/SysAdminDoc/UniversalConverterX/releases/download/$ReleaseTag/$archiveName"
$versionDirectory = Join-Path $OutputDirectory $Version
New-Item -ItemType Directory -Path $versionDirectory -Force | Out-Null

$versionManifest = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.version.$manifestVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
DefaultLocale: en-US
ManifestType: version
ManifestVersion: $manifestVersion
"@

$installerManifest = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.installer.$manifestVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
InstallerType: zip
NestedInstallerType: portable
NestedInstallerFiles:
  - RelativeFilePath: UniversalConverterX.exe
    PortableCommandAlias: universalconverterx
  - RelativeFilePath: ucx.exe
    PortableCommandAlias: ucx
Installers:
  - Architecture: x64
    InstallerUrl: $releaseUrl
    InstallerSha256: $sha256
ManifestType: installer
ManifestVersion: $manifestVersion
"@

$localeManifest = @"
# yaml-language-server: `$schema=https://aka.ms/winget-manifest.defaultLocale.$manifestVersion.schema.json
PackageIdentifier: $packageIdentifier
PackageVersion: $Version
PackageLocale: en-US
Publisher: SysAdminDoc
PublisherUrl: https://github.com/SysAdminDoc
PublisherSupportUrl: https://github.com/SysAdminDoc/UniversalConverterX/issues
PackageName: UniversalConverter X
PackageUrl: https://github.com/SysAdminDoc/UniversalConverterX
License: MIT
LicenseUrl: https://github.com/SysAdminDoc/UniversalConverterX/blob/main/LICENSE
ShortDescription: Offline-first Windows file and media conversion workspace.
Description: Convert media, documents, archives, subtitles, images, and AI-assisted workflows locally with a WinUI desktop app and the ucx command-line interface.
Tags:
  - converter
  - ffmpeg
  - media
  - offline
  - winui
ManifestType: defaultLocale
ManifestVersion: $manifestVersion
"@

Set-Content -LiteralPath (Join-Path $versionDirectory "$packageIdentifier.yaml") -Value $versionManifest -Encoding utf8NoBOM
Set-Content -LiteralPath (Join-Path $versionDirectory "$packageIdentifier.installer.yaml") -Value $installerManifest -Encoding utf8NoBOM
Set-Content -LiteralPath (Join-Path $versionDirectory "$packageIdentifier.locale.en-US.yaml") -Value $localeManifest -Encoding utf8NoBOM

[pscustomobject]@{
    PackageIdentifier = $packageIdentifier
    PackageVersion = $Version
    InstallerUrl = $releaseUrl
    InstallerSha256 = $sha256
    ManifestDirectory = $versionDirectory
}
