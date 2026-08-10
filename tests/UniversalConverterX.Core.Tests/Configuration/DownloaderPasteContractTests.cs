using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class DownloaderPasteContractTests
{
    [Fact]
    public void DownloaderPaste_UsesAwaitedClipboardReadInsideAnExceptionBoundary()
    {
        var root = FindRepoRoot();
        var path = Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "DownloaderPage.xaml.cs");
        var source = File.ReadAllText(path);

        source.Should().Contain("private async void Paste_Click");
        source.Should().Contain("var pkg = Clipboard.GetContent();");
        source.Should().Contain("var text = await pkg.GetTextAsync();");
        source.Should().Contain("Clipboard could not be read");
        source.Should().NotContain("ContinueWith");
        source.Should().NotContain("t.Result");
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
