using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class DownloaderOutputDirectoryContractTests
{
    [Fact]
    public void Downloader_UsesConfiguredOutputBeforeFallbacksAndSurfacesTheEffectivePath()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "DownloaderPage.xaml.cs"));
        var markup = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "DownloaderPage.xaml"));
        var downloadStart = source.IndexOf("private async void Download_Click", StringComparison.Ordinal);
        var downloadEnd = source.IndexOf("private void Cancel_Click", downloadStart, StringComparison.Ordinal);

        source.Should().Contain("IOptions<ConverterXOptions>");
        source.Should().Contain("options.DefaultOutputDirectory");
        source.Should().Contain("ResolveOutputDirectory");
        source.Should().Contain("OutputDirectoryText.Text = BuildOutputDirectoryStatus()");
        source.Should().Contain("Environment.ExpandEnvironmentVariables(candidate.Path)");
        source.Should().Contain("Path.Combine(Path.GetTempPath(), \"UniversalConverterX-Downloads\")");
        source.Should().Contain("_outputDirectoryWarning");
        markup.Should().Contain("x:Name=\"OutputDirectoryText\"");

        downloadStart.Should().BeGreaterThanOrEqualTo(0);
        downloadEnd.Should().BeGreaterThan(downloadStart);
        var handler = source[downloadStart..downloadEnd];
        handler.Should().Contain("if (!_outputDirectoryAvailable)");
        handler.Should().Contain("Directory.CreateDirectory(_outputDir)");
        handler.Should().Contain("return;");
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
