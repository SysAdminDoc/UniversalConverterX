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

        Version.TryParse(package.Attribute("Version")?.Value, out var version).Should().BeTrue();
        version.Should().NotBeNull();
        version!.Should().BeGreaterThanOrEqualTo(new Version(2, 0));
        SingleElementValue(project, "TargetFramework")
            .Should().StartWith("net10.0-windows10.0.19041.0");
        SingleElementValue(project, "WindowsAppSDKSelfContained").Should().Be("true");
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
