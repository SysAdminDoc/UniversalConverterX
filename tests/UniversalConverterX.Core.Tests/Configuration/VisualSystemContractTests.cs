using System.Text.RegularExpressions;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public class VisualSystemContractTests
{
    [Fact]
    public void EveryPage_ShouldUseTheCompactReadableVisualSystem()
    {
        var repoRoot = FindRepoRoot();
        var pagesRoot = Path.Combine(
            repoRoot,
            "src",
            "UniversalConverterX.UI",
            "Views",
            "Pages");

        var pages = Directory.GetFiles(pagesRoot, "*.xaml", SearchOption.TopDirectoryOnly);
        pages.Should().HaveCount(53);

        foreach (var page in pages)
        {
            var xaml = File.ReadAllText(page);
            xaml.Should().Contain("PageTitleTextStyle", $"{Path.GetFileName(page)} needs the shared page hierarchy");
            xaml.Should().Contain("PageDescriptionTextStyle", $"{Path.GetFileName(page)} needs bounded supporting copy");
            Regex.IsMatch(xaml, "FontSize=\"(?:9|10|11)\"").Should().BeFalse(
                $"{Path.GetFileName(page)} must not reintroduce undersized text");
            xaml.Should().NotContain("StatusPillStyle");
            xaml.Should().NotContain("PillTextStyle");
            xaml.Should().NotContain("BorderThickness=\"1\"");
            xaml.Should().NotContain("HeroGradientBrush");
            xaml.Should().NotContain("AiGradientBrush");
            xaml.Should().NotContain("MinHeight=\"430\"");
            xaml.Should().NotContain("Width=\"116\" Height=\"116\"");
            xaml.Should().NotContain("FontSize=\"48\"");
            Regex.IsMatch(xaml, "PageDescriptionTextStyle[^\\r\\n]*FontSize=").Should().BeFalse(
                $"{Path.GetFileName(page)} must not shrink the shared page description style");
        }
    }

    [Fact]
    public void SharedStyles_ShouldKeepCardsTonalAndBodyTextReadable()
    {
        var repoRoot = FindRepoRoot();
        var appXaml = File.ReadAllText(Path.Combine(
            repoRoot,
            "src",
            "UniversalConverterX.UI",
            "App.xaml"));

        appXaml.Should().Contain("x:Key=\"PageTitleTextStyle\"");
        appXaml.Should().Contain("x:Key=\"PageDescriptionTextStyle\"");
        appXaml.Should().Contain("x:Key=\"PageLayoutStyle\"");
        appXaml.Should().Contain("<Setter Property=\"FontSize\" Value=\"15\"/>");
        appXaml.Should().NotContain("<Setter Property=\"FontSize\" Value=\"11\"/>");

        var cardStart = appXaml.IndexOf("x:Key=\"CardStyle\"", StringComparison.Ordinal);
        cardStart.Should().BeGreaterThanOrEqualTo(0);
        var cardStyle = appXaml.Substring(cardStart, Math.Min(700, appXaml.Length - cardStart));
        cardStyle.Should().Contain("<Setter Property=\"BorderThickness\" Value=\"0\"/>");
    }

    [Fact]
    public void PrimaryWorkflowAndSettings_ShouldLeadWithControlsNotLegacyChrome()
    {
        var repoRoot = FindRepoRoot();
        var viewsRoot = Path.Combine(repoRoot, "src", "UniversalConverterX.UI", "Views");
        var converterXaml = File.ReadAllText(Path.Combine(viewsRoot, "Pages", "ConverterPage.xaml"));
        var settingsXaml = File.ReadAllText(Path.Combine(viewsRoot, "SettingsWindow.xaml"));

        converterXaml.IndexOf("Text=\"Output format\"", StringComparison.Ordinal)
            .Should().BeLessThan(converterXaml.IndexOf("Text=\"Format Shortcuts\"", StringComparison.Ordinal));
        converterXaml.IndexOf("Text=\"Output format\"", StringComparison.Ordinal)
            .Should().BeLessThan(converterXaml.IndexOf("Header=\"Advanced FFmpeg command\"", StringComparison.Ordinal));
        settingsXaml.Should().NotContain("BorderThickness=\"1\"");
        settingsXaml.Should().NotContain("Text=\"Local defaults\"");
    }

    [Fact]
    public void Converter_ShouldMatchTheFlatQueueAndUnifiedOutputInspectorContract()
    {
        var repoRoot = FindRepoRoot();
        var converterPath = Path.Combine(
            repoRoot,
            "src",
            "UniversalConverterX.UI",
            "Views",
            "Pages",
            "ConverterPage.xaml");
        var converterXaml = File.ReadAllText(converterPath);
        var converterCode = File.ReadAllText(converterPath + ".cs");

        converterXaml.Should().Contain("<SplitButton x:Name=\"AddFilesSplitButton\"");
        converterXaml.Should().Contain("x:Name=\"OutputInspector\"");
        converterXaml.Should().Contain("Text=\"Output format\"");
        converterXaml.Should().Contain("x:Name=\"QualityPresetSelector\"");
        converterXaml.Should().Contain("x:Name=\"ResolutionSelector\"");
        converterXaml.Should().Contain("x:Name=\"FrameRateSelector\"");
        converterXaml.Should().Contain("x:Name=\"AudioSelector\"");
        converterXaml.Should().Contain("x:Name=\"SameAsSourceFolderCheckBox\"");
        converterXaml.Should().Contain("x:Name=\"OpenOutputAfterConversionCheckBox\"");
        converterXaml.Should().Contain("BorderThickness=\"0,0,0,1\"");
        converterXaml.Should().NotContain("Text=\"Output\" Style=\"{StaticResource PanelTitleTextStyle}\"");

        converterCode.Should().Contain("ApplyVisibleOutputProfile(conversionOptions)");
        converterCode.Should().Contain("options.Video.Width = _outputWidth");
        converterCode.Should().Contain("options.Video.Fps = _outputFrameRate");
        converterCode.Should().Contain("options.Audio.Bitrate =");
    }

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
