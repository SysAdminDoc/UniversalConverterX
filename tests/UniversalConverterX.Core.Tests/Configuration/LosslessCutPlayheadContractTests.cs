using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class LosslessCutPlayheadContractTests
{
    [Fact]
    public void Playhead_UsesThemeAwareFillAndContrastingOutline()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "LosslessCutPage.xaml"));
        var start = source.IndexOf("<Rectangle x:Name=\"Playhead\"", StringComparison.Ordinal);
        var end = source.IndexOf("/>", start, StringComparison.Ordinal);

        start.Should().BeGreaterThanOrEqualTo(0);
        end.Should().BeGreaterThan(start);
        var playhead = source[start..(end + 2)];
        playhead.Should().Contain("Fill=\"{StaticResource AccentRedBrush}\"");
        playhead.Should().Contain("Stroke=\"{StaticResource TextInverseBrush}\"");
        playhead.Should().NotContain("Fill=\"White\"");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
                return directory.FullName;

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate repository root.");
    }
}
