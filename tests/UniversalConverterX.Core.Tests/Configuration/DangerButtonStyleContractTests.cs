using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class DangerButtonStyleContractTests
{
    [Fact]
    public void DangerButtonStyle_ContainsNoHardcodedBorderColor()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(root, "src", "UniversalConverterX.UI", "App.xaml"));
        var start = source.IndexOf("<Style x:Key=\"DangerButtonStyle\"", StringComparison.Ordinal);
        var end = source.IndexOf("</Style>", start, StringComparison.Ordinal);

        start.Should().BeGreaterThanOrEqualTo(0);
        end.Should().BeGreaterThan(start);
        source[start..end].Should().NotContain("#7f1d1d");
        source[start..end].Should().NotContain("BorderBrush");
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
