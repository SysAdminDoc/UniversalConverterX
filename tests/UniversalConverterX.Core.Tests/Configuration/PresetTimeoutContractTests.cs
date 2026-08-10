using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class PresetTimeoutContractTests
{
    [Fact]
    public void PresetsPage_DoesNotImposeAnArbitraryWallClockCancellation()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Views", "Pages", "PresetsPage.xaml.cs"));

        source.Should().Contain(
            "cancellationToken: CancellationToken.None");
        source.Should().NotContain(
            "new CancellationTokenSource(TimeSpan.FromHours(1))");
    }

    [Fact]
    public void SidecarWatchdog_UsesADistinctStuckError()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root, "src", "UniversalConverterX.UI", "Services", "SidecarRunner.cs"));

        source.Should().Contain("stuckByWatchdog = watchdogCts.IsCancellationRequested && !ct.IsCancellationRequested");
        source.Should().Contain("ErrorCode: \"stuck_sidecar\"");
        source.Should().Contain("new SidecarResult(false, null, null, \"cancelled\", \"Cancelled by user.\", -1)");
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
