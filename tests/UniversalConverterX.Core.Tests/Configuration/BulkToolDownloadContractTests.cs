using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class BulkToolDownloadContractTests
{
    [Fact]
    public void BulkToolDownload_CatchesFailuresAndAlwaysRestoresButtonState()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "SettingsWindow.xaml.cs"));
        var start = source.IndexOf("private async void DownloadAllTools_Click", StringComparison.Ordinal);
        var end = source.IndexOf("private async Task ShowToolDownloadFailureAsync", start, StringComparison.Ordinal);

        start.Should().BeGreaterThanOrEqualTo(0);
        end.Should().BeGreaterThan(start);
        var handler = source[start..end];

        handler.Should().Contain("DownloadToolsAsync");
        handler.Should().Contain("catch (Exception ex)");
        handler.Should().Contain("await ShowToolDownloadFailureAsync(ex)");
        handler.Should().Contain("finally");
        handler.Should().Contain("DownloadAllToolsButton.IsEnabled = true");
        handler.Should().Contain("Install missing tools");
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
