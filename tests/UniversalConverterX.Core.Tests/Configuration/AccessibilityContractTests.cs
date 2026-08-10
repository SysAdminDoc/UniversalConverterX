using System.Text.RegularExpressions;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class AccessibilityContractTests
{
    private static readonly string[] RequiredTextKeys =
    [
        "BrandTextPrimary",
        "BrandTextSecondary",
        "BrandTextMuted",
        "BrandTextSubtle",
    ];

    [Fact]
    public void SharedUi_ShouldExposeLiveRegionsWithoutFocusStealing()
    {
        var root = FindRepoRoot();
        var app = ReadUiFile(root, "App.xaml");
        var shell = ReadUiFile(root, Path.Combine("Views", "MainWindow.xaml.cs"));
        var behavior = ReadUiFile(root, Path.Combine("Services", "AccessibilityPrimitives.cs"));

        app.Should().Contain("x:Key=\"StatusTextStyle\"");
        app.Should().Contain("AutomationProperties.LiveSetting");
        behavior.Should().Contain("AutomationLiveSetting.Polite");
        behavior.Should().Contain("ApplyLiveRegions");
        shell.Should().Contain("ContentFrame.Navigated += ContentFrame_Navigated");
        shell.Should().Contain("AccessibilityPrimitives.ApplyLiveRegions(args.Content as DependencyObject)");
        behavior.Should().NotContain("Focus(", "live-region application must never steal focus");
    }

    [Fact]
    public void Shell_ShouldDocumentStableKeyboardAcceleratorsForCoreActions()
    {
        var root = FindRepoRoot();
        var shell = ReadUiFile(root, Path.Combine("Views", "MainWindow.xaml.cs"));

        shell.Should().Contain("Ctrl+K");
        shell.Should().Contain("Ctrl+1");
        shell.Should().Contain("Ctrl+2");
        shell.Should().Contain("Ctrl+J");
        shell.Should().Contain("KeyboardAccelerator");
        shell.Should().Contain("VirtualKey.K");
        shell.Should().Contain("VirtualKey.Number1");
        shell.Should().Contain("VirtualKey.Number2");
        shell.Should().Contain("VirtualKey.J");
        shell.Should().Contain("args.Handled = true");
    }

    [Fact]
    public void EveryPage_ShouldInheritResponsiveReflowBehavior()
    {
        var root = FindRepoRoot();
        var behavior = ReadUiFile(root, Path.Combine("Services", "AccessibilityPrimitives.cs"));
        var app = ReadUiFile(root, "App.xaml");
        var pagesRoot = Path.Combine(root, "src", "UniversalConverterX.UI", "Views", "Pages");
        var pages = Directory.GetFiles(pagesRoot, "*.xaml", SearchOption.TopDirectoryOnly);

        pages.Should().HaveCount(54);
        app.Should().Contain("ResponsiveLayoutEnabled");
        behavior.Should().Contain("NarrowWindowWidth");
        behavior.Should().Contain("WideFixedColumnThreshold");
        behavior.Should().Contain("GridUnitType.Star");

        foreach (var page in pages)
        {
            var xaml = File.ReadAllText(page);
            (xaml.Contains("PageLayoutStyle", StringComparison.Ordinal)
                || xaml.Contains("PageStackLayoutStyle", StringComparison.Ordinal))
                .Should().BeTrue($"{Path.GetFileName(page)} must inherit the shared responsive layout style");
        }
    }

    [Fact]
    public void SharedTextPalette_ShouldMeetWcagAaAgainstBothNormalThemes()
    {
        var root = FindRepoRoot();
        var app = ReadUiFile(root, "App.xaml");

        foreach (var theme in new[] { "Default", "Light", "HighContrast" })
        {
            var palette = ReadPalette(app, theme);
            palette.Keys.Should().Contain(RequiredTextKeys);

            foreach (var textKey in RequiredTextKeys)
            {
                var contrast = ContrastRatio(palette[textKey], palette["BrandBackground"]);
                contrast.Should().BeGreaterThanOrEqualTo(
                    4.5,
                    $"{textKey} in {theme} must remain readable at normal text sizes");
            }
        }
    }

    [Fact]
    public void SharedResources_ShouldProvideHighContrastFocusAndReflowTokens()
    {
        var root = FindRepoRoot();
        var app = ReadUiFile(root, "App.xaml");
        var shell = ReadUiFile(root, Path.Combine("Views", "MainWindow.xaml"));

        app.Should().Contain("x:Key=\"HighContrast\"");
        app.Should().Contain("FocusVisualPrimaryBrush");
        app.Should().Contain("FocusVisualSecondaryBrush");
        app.Should().Contain("UseSystemFocusVisuals");
        app.Should().Contain("TextWrapping");
        shell.Should().Contain("SizeChanged=\"ShellRoot_SizeChanged\"");
        shell.Should().Contain("CompactPaneLength=\"48\"");
    }

    private static Dictionary<string, uint> ReadPalette(string app, string theme)
    {
        var marker = $"<ResourceDictionary x:Key=\"{theme}\">";
        var start = app.IndexOf(marker, StringComparison.Ordinal);
        start.Should().BeGreaterThanOrEqualTo(0, $"App.xaml must define the {theme} theme dictionary");
        var end = app.IndexOf("</ResourceDictionary>", start, StringComparison.Ordinal);
        end.Should().BeGreaterThan(start);

        var block = app.Substring(start, end - start);
        return Regex.Matches(
                block,
                "<Color\\s+x:Key=\"(?<name>Brand[A-Za-z]+)\">(?<value>#[0-9a-fA-F]{6})</Color>")
            .ToDictionary(
                match => match.Groups["name"].Value,
                match => Convert.ToUInt32(match.Groups["value"].Value[1..], 16),
                StringComparer.Ordinal);
    }

    private static double ContrastRatio(uint foreground, uint background)
    {
        var foregroundLuminance = RelativeLuminance(foreground);
        var backgroundLuminance = RelativeLuminance(background);
        return (Math.Max(foregroundLuminance, backgroundLuminance) + 0.05)
            / (Math.Min(foregroundLuminance, backgroundLuminance) + 0.05);
    }

    private static double RelativeLuminance(uint color)
    {
        var red = Linearize((color >> 16) & 0xff);
        var green = Linearize((color >> 8) & 0xff);
        var blue = Linearize(color & 0xff);
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
    }

    private static double Linearize(uint channel)
    {
        var srgb = channel / 255d;
        return srgb <= 0.04045
            ? srgb / 12.92
            : Math.Pow((srgb + 0.055) / 1.055, 2.4);
    }

    private static string ReadUiFile(string root, string relativePath) =>
        File.ReadAllText(Path.Combine(root, "src", "UniversalConverterX.UI", relativePath));

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }
}
