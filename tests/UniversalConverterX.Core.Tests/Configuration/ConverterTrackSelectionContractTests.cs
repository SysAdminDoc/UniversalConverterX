using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ConverterTrackSelectionContractTests
{
    [Fact]
    public void ConverterPreflight_ShouldExposeNamedTracksAndSnapshotSelections()
    {
        var converterCode = ReadUiFile(Path.Combine("Views", "Pages"), "ConverterPage.xaml.cs");
        var converterXaml = ReadUiFile(Path.Combine("Views", "Pages"), "ConverterPage.xaml");
        var queueStore = File.ReadAllText(Path.Combine(
            FindRepoRoot(), "src", "UniversalConverterX.Core", "Services", "BatchQueueStore.cs"));

        converterCode.Should().Contain("MediaFidelityProbe.ProbeAsync");
        converterCode.Should().Contain("AudioTrackSelection");
        converterCode.Should().Contain("SubtitleTrackSelection");
        converterCode.Should().Contain("CaptureTrackSelection");
        converterXaml.Should().Contain("ConverterPage_TrackSelectionButton");
        converterXaml.Should().Contain("TrackSelectionTemplate");
        queueStore.Should().Contain("AudioTrackSelection");
        queueStore.Should().Contain("SubtitleTrackSelection");
    }

    private static string ReadUiFile(params string[] relativeParts) =>
        File.ReadAllText(Path.Combine(
            FindRepoRoot(),
            "src",
            "UniversalConverterX.UI",
            Path.Combine(relativeParts)));

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props"))
                && File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
                return directory.FullName;
            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }
}
