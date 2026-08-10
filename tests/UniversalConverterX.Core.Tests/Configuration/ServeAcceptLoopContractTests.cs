using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ServeAcceptLoopContractTests
{
    [Fact]
    public void ServeUsesListenerStopForCancellationWithoutPerRequestInfiniteDelay()
    {
        var root = FindRepoRoot();
        var source = File.ReadAllText(
            Path.Combine(root, "src", "UniversalConverterX.Console", "Commands", "ServeCommand.cs"));

        source.Should().Contain("using var stopRegistration = stopCts.Token.Register");
        source.Should().Contain("try { listener.Stop(); } catch { }");
        source.Should().Contain("await listener.GetContextAsync()");
        source.Should().NotContain("Task.Delay(Timeout.Infinite, stopCts.Token)");
        source.Should().NotContain("Task.WhenAny(ctxTask");
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "ROADMAP.md")))
            directory = directory.Parent;
        return directory?.FullName
            ?? throw new InvalidOperationException("Repository root not found.");
    }
}
