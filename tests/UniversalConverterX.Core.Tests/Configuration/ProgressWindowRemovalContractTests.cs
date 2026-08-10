using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ProgressWindowRemovalContractTests
{
    [Fact]
    public void DeadProgressWindow_IsRemovedAlongWithItsLocalizationEntries()
    {
        var root = FindRepoRoot();
        var uiRoot = Path.Combine(root, "src", "UniversalConverterX.UI");

        File.Exists(Path.Combine(uiRoot, "Views", "ProgressWindow.xaml")).Should().BeFalse();
        File.Exists(Path.Combine(uiRoot, "Views", "ProgressWindow.xaml.cs")).Should().BeFalse();
        File.ReadAllText(Path.Combine(root, "tools", "localization", "extract_xaml_resources.py"))
            .Should().NotContain("ProgressWindow_");

        foreach (var resourceFile in Directory.EnumerateFiles(
                     Path.Combine(uiRoot, "Strings"), "Resources.resw", SearchOption.AllDirectories))
        {
            File.ReadAllText(resourceFile).Should().NotContain("ProgressWindow_");
        }
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
