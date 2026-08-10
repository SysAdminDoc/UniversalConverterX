using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class OpenOutputFolderContractTests
{
    [Fact]
    public void RecorderAndDownloaderOpenDirectoriesDirectly()
    {
        var root = FindRepoRoot();
        foreach (var page in new[] { "RecorderPage.xaml.cs", "DownloaderPage.xaml.cs" })
        {
            var source = File.ReadAllText(Path.Combine(
                root,
                "src",
                "UniversalConverterX.UI",
                "Views",
                "Pages",
                page));

            source.Should().Contain("FileName = folder");
            source.Should().Contain("/select");
            source.Should().Contain("Directory.Exists(path)");
        }
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "ROADMAP.md")))
            directory = directory.Parent;
        return directory?.FullName
            ?? throw new DirectoryNotFoundException("Repository root not found.");
    }
}
