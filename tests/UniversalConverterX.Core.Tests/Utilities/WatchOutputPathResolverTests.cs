using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class WatchOutputPathResolverTests : IDisposable
{
    private readonly string _tempDir = Path.Combine(
        Path.GetTempPath(),
        "ucx-watch-output-tests-" + Guid.NewGuid().ToString("N"));

    public WatchOutputPathResolverTests() => Directory.CreateDirectory(_tempDir);

    [Fact]
    public void TryResolve_SameTargetExtensionGetsAUniqueSibling()
    {
        var input = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(input, "source");

        var ok = WatchOutputPathResolver.TryResolve(
            input,
            input,
            out var resolved,
            out var error);

        ok.Should().BeTrue(error);
        resolved.Should().Be(Path.Combine(_tempDir, "clip (1).mp4"));
        File.ReadAllText(input).Should().Be("source");
    }

    [Fact]
    public void TryResolve_ExistingPriorOutputGetsAUniqueSibling()
    {
        var input = Path.Combine(_tempDir, "clip.mov");
        var existingOutput = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(input, "source");
        File.WriteAllText(existingOutput, "prior output");

        var ok = WatchOutputPathResolver.TryResolve(
            input,
            existingOutput,
            out var resolved,
            out var error);

        ok.Should().BeTrue(error);
        resolved.Should().Be(Path.Combine(_tempDir, "clip (1).mp4"));
        File.ReadAllText(existingOutput).Should().Be("prior output");
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); }
        catch (IOException) { }
    }
}
