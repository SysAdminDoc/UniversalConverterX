using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class PluginsFolderContractTests
{
    [Fact]
    public void PluginsFolderHandler_CatchesAccessFailuresAndKeepsAPathFallback()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml.cs"));
        var start = source.IndexOf("private async void OpenPluginsFolder_Click", StringComparison.Ordinal);
        var end = source.IndexOf("private void LoadSettings", start, StringComparison.Ordinal);

        start.Should().BeGreaterThanOrEqualTo(0);
        end.Should().BeGreaterThan(start);
        var region = source[start..end];

        region.Should().Contain("Directory.CreateDirectory(pluginDirectory)");
        region.Should().Contain("StorageFolder.GetFolderFromPathAsync(pluginDirectory)");
        region.Should().Contain("catch (Exception ex)");
        region.Should().Contain("ShowPluginsFolderFallbackAsync(pluginDirectory)");
        region.Should().Contain("ShowMessageAsync(AppLocalizer.Get(\"Plugins folder\")");
        region.Should().Contain("InfoBarSeverity.Error");
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
