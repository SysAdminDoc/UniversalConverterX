using System.Text.RegularExpressions;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

/// <summary>
/// The runtime UI smoke harness sweeps exactly what
/// <c>NavigationRoutes</c> declares. A page that is not registered there is a
/// page the gate never opens, so coverage is asserted from source.
/// </summary>
public sealed class UiRouteCoverageTests
{
    [Fact]
    public void EveryShippedPage_IsReachableFromTheRouteTable()
    {
        var root = FindRepoRoot();
        var routesSource = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "NavigationRoutes.cs"));

        var registered = Regex
            .Matches(routesSource, @"typeof\((?<page>\w+Page)\)")
            .Select(match => match.Groups["page"].Value)
            .ToHashSet(StringComparer.Ordinal);

        var shipped = Directory
            .EnumerateFiles(
                Path.Combine(root, "src", "UniversalConverterX.UI", "Views", "Pages"),
                "*.xaml")
            .Select(Path.GetFileNameWithoutExtension)
            .Where(name => name is not null && name.EndsWith("Page", StringComparison.Ordinal))
            .Select(name => name!)
            .ToHashSet(StringComparer.Ordinal);

        shipped.Should().NotBeEmpty();
        var unreachable = shipped.Except(registered).OrderBy(name => name).ToArray();
        unreachable.Should().BeEmpty(
            "every page must have a route so the runtime UI smoke harness opens it");

        var dangling = registered.Except(shipped).OrderBy(name => name).ToArray();
        dangling.Should().BeEmpty("the route table must not point at a deleted page");
    }

    [Fact]
    public void MainWindow_ResolvesNavigationThroughTheSharedRouteTable()
    {
        var root = FindRepoRoot();
        var mainWindow = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "MainWindow.xaml.cs"));

        // A second inline switch would drift from the swept table without any
        // build error, which is exactly how untested pages appeared before.
        mainWindow.Should().Contain("NavigationRoutes.Resolve(");
        mainWindow.Should().NotContain("=> typeof(");
    }

    [Fact]
    public void SmokeHarness_SweepsBothThemesAndTheNarrowReflowWidth()
    {
        var root = FindRepoRoot();
        var harness = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Services", "UiSmokeHarness.cs"));

        harness.Should().Contain("ElementTheme.Light");
        harness.Should().Contain("ElementTheme.Dark");
        harness.Should().Contain("dark-narrow");
        harness.Should().Contain("FindFirstFocusableElement");
        harness.Should().Contain("NavigationRoutes.RouteKeys");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null
            && !File.Exists(Path.Combine(directory.FullName, "UniversalConverterX.sln"))
            && !Directory.Exists(Path.Combine(directory.FullName, ".git")))
        {
            directory = directory.Parent;
        }

        directory.Should().NotBeNull();
        return directory!.FullName;
    }
}
