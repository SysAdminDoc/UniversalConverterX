using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class RecorderCancelContractTests
{
    [Fact]
    public void Recorder_CleansCancelledPartialOutputsAndNeverPublishesThemAsFinished()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "RecorderPage.xaml.cs"));
        var cleanupStart = source.IndexOf("private static SidecarResult RemoveCancelledOutput", StringComparison.Ordinal);
        var cancelHandlerStart = source.IndexOf("private void Cancel_Click", StringComparison.Ordinal);

        cleanupStart.Should().BeGreaterThanOrEqualTo(0);
        cancelHandlerStart.Should().BeGreaterThan(cleanupStart);
        var cleanup = source[cleanupStart..cancelHandlerStart];

        source.Should().Contain("if (result.ErrorCode == \"cancelled\")\n                    result = RemoveCancelledOutput(outputPath, result);");
        cleanup.Should().Contain("File.Delete(outputPath)");
        cleanup.Should().Contain("OutputPath = null");
        cleanup.Should().Contain("partial recording could not be removed");
        source.Should().Contain("public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);");
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
