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

    [Fact]
    public void AppStartup_DefersResourceMutationUntilTheWindowExists()
    {
        var root = FindRepoRoot();
        var app = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "App.xaml.cs"));
        var constructor = Regex.Match(
            app,
            @"public App\(\)\s*\{(?<body>.*?)\n\s*\}",
            RegexOptions.Singleline).Groups["body"].Value;

        constructor.Should().NotBeNullOrWhiteSpace();
        constructor.Should().NotContain("ApplyAccentColor(",
            "WinUI resources are unavailable during the Application constructor");
        app.IndexOf("_mainWindow = new MainWindow();", StringComparison.Ordinal)
            .Should().BeLessThan(
                app.IndexOf("_mainWindow.Activate();", StringComparison.Ordinal),
                "normal startup must create the shell before activating it");
    }

    [Fact]
    public void UnpackagedLocalization_FallsBackWhenTheLanguageBrokerIsUnavailable()
    {
        var root = FindRepoRoot();
        var localizer = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Services", "AppLocalizer.cs"));

        localizer.Should().Contain("ApplicationLanguages.PrimaryLanguageOverride");
        localizer.Should().Contain("catch (InvalidOperationException)");
        localizer.Should().Contain("return false;");
    }

    [Fact]
    public void SmokeHarness_RendersWithoutTouchingTheOperatorDesktop()
    {
        var root = FindRepoRoot();
        var app = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "App.xaml.cs"));
        var hooks = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Services", "UiTestHooks.cs"));
        var harness = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Services", "UiSmokeHarness.cs"));

        app.Should().Contain("UiTestHooks.ShowOffscreen(_mainWindow);");
        hooks.Should().Contain("WsExToolWindow | WsExLayered | WsExNoActivate");
        hooks.Should().Contain("appWindow.IsShownInSwitchers = false;");
        hooks.Should().Contain("SetLayeredWindowAttributes(hwnd, 0, 0, LwaAlpha)");
        hooks.Should().Contain("virtualRight + 512");
        harness.Should().Contain("await Task.Delay(450)",
            "captures must wait for the navigation transition to finish");
    }

    [Fact]
    public void ToolboxTiles_AreKeyboardFocusableButtons()
    {
        var root = FindRepoRoot();
        var toolbox = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "ToolboxPage.xaml"));

        toolbox.Should().Contain("<Button Width=\"216\"");
        toolbox.Should().Contain("Click=\"Tile_Click\"");
        toolbox.Should().NotContain("Tapped=\"Tile_Tapped\"");
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
