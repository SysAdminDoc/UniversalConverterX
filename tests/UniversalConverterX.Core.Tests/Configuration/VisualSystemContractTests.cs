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

        var cardStart = appXaml.IndexOf("x:Key=\"CardStyle\"", StringComparison.Ordinal);
        cardStart.Should().BeGreaterThanOrEqualTo(0);
        var cardStyle = appXaml.Substring(cardStart, Math.Min(700, appXaml.Length - cardStart));
        cardStyle.Should().Contain("<Setter Property=\"BorderThickness\" Value=\"0\"/>");
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
