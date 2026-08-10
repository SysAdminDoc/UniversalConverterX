using System.Text.RegularExpressions;
using System.Xml.Linq;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public class VersionConsistencyTests
{
    private static readonly Regex SemVer = new(@"^\d+\.\d+\.\d+$", RegexOptions.Compiled);

    [Fact]
    public void ActiveReleaseSurfaces_ShouldUseDirectoryBuildVersion()
    {
        var repoRoot = FindRepoRoot();
        var rootProps = XDocument.Load(Path.Combine(repoRoot, "Directory.Build.props"));
        var version = SingleElementValue(rootProps, "Version");

        version.Should().MatchRegex(SemVer.ToString());
        SingleElementValue(rootProps, "AssemblyVersion").Should().Be(version + ".0");
        SingleElementValue(rootProps, "FileVersion").Should().Be(version + ".0");

        AssertSrcPropsImportsRootVersion(repoRoot);
        AssertProjectsDoNotOverrideVersion(repoRoot);
        AssertActiveFilesContain(repoRoot, version);
    }

    [Fact]
    public void UiProject_ShouldRemainOnWinAppSdk2OrNewer()
    {
        var repoRoot = FindRepoRoot();
        var projectPath = Path.Combine(
            repoRoot,
            "src",
            "UniversalConverterX.UI",
            "UniversalConverterX.UI.csproj");
        var project = XDocument.Load(projectPath);
        var package = project
            .Descendants("PackageReference")
            .Where(element => string.Equals(
                element.Attribute("Include")?.Value,
                "Microsoft.WindowsAppSDK",
                StringComparison.Ordinal))
            .Should()
            .ContainSingle()
            .Which;

        package.Attribute("Version")?.Value.Should().Be("$(WindowsAppSdkPackageVersion)");
        var rootProps = XDocument.Load(Path.Combine(repoRoot, "Directory.Build.props"));
        var packageVersion = SingleElementValue(rootProps, "WindowsAppSdkPackageVersion");
        Version.TryParse(packageVersion, out var version).Should().BeTrue();
        version.Should().NotBeNull();
        version!.Should().BeGreaterThanOrEqualTo(new Version(2, 0));
        SingleElementValue(project, "TargetFramework")
          .Should().StartWith("net10.0-windows10.0.22621.0");
        SingleElementValue(project, "WindowsAppSDKSelfContained").Should().Be("true");
    }

    [Fact]
    public void PlatformPackagePins_ShouldBeCentralizedAndServiced()
    {
        var repoRoot = FindRepoRoot();
        var rootProps = XDocument.Load(Path.Combine(repoRoot, "Directory.Build.props"));
        var dotnetVersion = SingleElementValue(rootProps, "DotnetServicingPackageVersion");
        var windowsAppSdkVersion = SingleElementValue(rootProps, "WindowsAppSdkPackageVersion");

        dotnetVersion.Should().Be("10.0.10");
        windowsAppSdkVersion.Should().Be("2.3.1");

        var servicedReferenceCount = 0;
        var windowsAppSdkReferenceCount = 0;
        var projectRoots = new[] { "src", "tests" };
        foreach (var projectRoot in projectRoots)
        {
            foreach (var projectPath in Directory.EnumerateFiles(
                         Path.Combine(repoRoot, projectRoot),
                         "*.csproj",
                         SearchOption.AllDirectories))
            {
                var project = XDocument.Load(projectPath);
                var relativePath = Path.GetRelativePath(repoRoot, projectPath);
                foreach (var package in project.Descendants("PackageReference"))
                {
                    var packageName = package.Attribute("Include")?.Value;
                    var packageVersion = package.Attribute("Version")?.Value;
                    if (string.Equals(packageName, "Microsoft.WindowsAppSDK", StringComparison.Ordinal))
                    {
                        windowsAppSdkReferenceCount++;
                        packageVersion.Should().Be("$(WindowsAppSdkPackageVersion)", relativePath);
                    }

                    if (IsDotnetServicingPackage(packageName))
                    {
                        servicedReferenceCount++;
                        packageVersion.Should().Be("$(DotnetServicingPackageVersion)", relativePath);
                    }
                }
            }
        }

        servicedReferenceCount.Should().BeGreaterThan(0);
        windowsAppSdkReferenceCount.Should().Be(2);
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);

        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "README.md")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }

    private static bool IsDotnetServicingPackage(string? packageName)
    {
        return packageName is not null &&
               (packageName.StartsWith("Microsoft.Extensions.", StringComparison.Ordinal) ||
                string.Equals(packageName, "Microsoft.Data.Sqlite.Core", StringComparison.Ordinal) ||
                string.Equals(packageName, "System.Drawing.Common", StringComparison.Ordinal) ||
                string.Equals(
                    packageName,
                    "System.Security.Cryptography.ProtectedData",
                    StringComparison.Ordinal));
    }

    private static string SingleElementValue(XDocument document, string elementName)
    {
        return document
            .Descendants(elementName)
            .Should()
            .ContainSingle()
            .Which.Value
            .Trim();
    }

    private static void AssertSrcPropsImportsRootVersion(string repoRoot)
    {
        var srcPropsPath = Path.Combine(repoRoot, "src", "Directory.Build.props");
        var srcProps = XDocument.Load(srcPropsPath);

        srcProps.Root.Should().NotBeNull();
        srcProps.Root!
            .Elements("Import")
            .Select(import => import.Attribute("Project")?.Value)
            .Should()
            .Contain(@"..\Directory.Build.props");

        srcProps.Descendants("Version").Should().BeEmpty("src projects inherit the root release version");
        srcProps.Descendants("AssemblyVersion").Should().BeEmpty();
        srcProps.Descendants("FileVersion").Should().BeEmpty();
    }

    private static void AssertProjectsDoNotOverrideVersion(string repoRoot)
    {
        var projectFiles = Directory
            .EnumerateFiles(Path.Combine(repoRoot, "src"), "*.csproj", SearchOption.AllDirectories)
            .ToArray();

        projectFiles.Should().NotBeEmpty();

        foreach (var projectFile in projectFiles)
        {
            var project = XDocument.Load(projectFile);
            project
                .Descendants("Version")
                .Should()
                .BeEmpty($"{Path.GetRelativePath(repoRoot, projectFile)} should inherit Directory.Build.props");
        }
    }

    private static void AssertActiveFilesContain(string repoRoot, string version)
    {
        var fourPartVersion = version + ".0";
        var activeSurfaces = new Dictionary<string, string[]>
        {
            ["README.md"] = [$"version-{version}-blue"],
            [Path.Combine("installer", "build-installer.ps1")] = [$"'{fourPartVersion}'"],
            [Path.Combine("installer", "wix", "Product.wxs")] = [fourPartVersion],
            [Path.Combine("installer", "msix", "Package.appxmanifest")] = [$"Version=\"{fourPartVersion}\""],
            [Path.Combine("src", "UniversalConverterX.UI", "app.manifest")] = [$"version=\"{fourPartVersion}\""],
            [Path.Combine("src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml")] = [$"Version {version}"],
            [Path.Combine("src", "UniversalConverterX.UI", "Views", "Pages", "HomePage.xaml")] = [$"UniversalConverter X v{version}"],
        };

        foreach (var (relativePath, expectedFragments) in activeSurfaces)
        {
            var text = File.ReadAllText(Path.Combine(repoRoot, relativePath));
            foreach (var expectedFragment in expectedFragments)
            {
                text.Should().Contain(expectedFragment, relativePath);
            }
        }
    }
}
