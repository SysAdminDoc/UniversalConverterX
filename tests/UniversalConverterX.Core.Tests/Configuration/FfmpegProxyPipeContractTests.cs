using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class FfmpegProxyPipeContractTests
{
    [Fact]
    public void ClientPinsTheNamedPipeToTheCurrentUserWithoutDelegation()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(Path.Combine(
            root,
            "src",
            "UniversalConverterX.FfmpegProxy",
            "Program.cs"));

        source.Should().Contain("PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly");
        source.Should().Contain("TokenImpersonationLevel.None");
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
