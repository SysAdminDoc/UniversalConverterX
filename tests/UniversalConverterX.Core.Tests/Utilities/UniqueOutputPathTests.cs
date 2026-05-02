using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class UniqueOutputPathTests : IDisposable
{
    private readonly string _tempDir;

    public UniqueOutputPathTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "ucx-uop-tests-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); } catch { /* best-effort */ }
        GC.SuppressFinalize(this);
    }

    [Fact]
    public void Resolve_NonExistentPath_ReturnsInputUnchanged()
    {
        var path = Path.Combine(_tempDir, "missing.mp4");

        var result = UniqueOutputPath.Resolve(path);

        result.Should().Be(path);
    }

    [Fact]
    public void Resolve_ExistingPath_AppendsParenOne()
    {
        var path = Path.Combine(_tempDir, "video.mp4");
        File.WriteAllText(path, "dummy");

        var result = UniqueOutputPath.Resolve(path);

        result.Should().Be(Path.Combine(_tempDir, "video (1).mp4"));
    }

    [Fact]
    public void Resolve_ExistingPathAndParenOne_AppendsParenTwo()
    {
        var path = Path.Combine(_tempDir, "video.mp4");
        File.WriteAllText(path, "dummy");
        File.WriteAllText(Path.Combine(_tempDir, "video (1).mp4"), "dummy");

        var result = UniqueOutputPath.Resolve(path);

        result.Should().Be(Path.Combine(_tempDir, "video (2).mp4"));
    }

    [Fact]
    public void Resolve_PreservesFinalExtension_OnDualExtension()
    {
        var path = Path.Combine(_tempDir, "archive.tar.gz");
        File.WriteAllText(path, "dummy");

        var result = UniqueOutputPath.Resolve(path);

        // Path.GetExtension returns ".gz", so the stem is "archive.tar".
        result.Should().Be(Path.Combine(_tempDir, "archive.tar (1).gz"));
    }

    [Fact]
    public void Resolve_NoExtension_HandlesGracefully()
    {
        var path = Path.Combine(_tempDir, "README");
        File.WriteAllText(path, "dummy");

        var result = UniqueOutputPath.Resolve(path);

        result.Should().Be(Path.Combine(_tempDir, "README (1)"));
    }

    [Fact]
    public void Resolve_DirectoryAtPath_TreatsAsCollision()
    {
        var path = Path.Combine(_tempDir, "outdir");
        Directory.CreateDirectory(path);

        var result = UniqueOutputPath.Resolve(path);

        result.Should().Be(Path.Combine(_tempDir, "outdir (1)"));
    }

    [Fact]
    public void Resolve_EmptyOrWhitespace_Throws()
    {
        FluentActions.Invoking(() => UniqueOutputPath.Resolve(""))
            .Should().Throw<ArgumentException>();
        FluentActions.Invoking(() => UniqueOutputPath.Resolve("   "))
            .Should().Throw<ArgumentException>();
    }

    [Fact]
    public void Resolve_InvalidMaxSuffix_Throws()
    {
        var path = Path.Combine(_tempDir, "x.txt");

        FluentActions.Invoking(() => UniqueOutputPath.Resolve(path, maxSuffix: 0))
            .Should().Throw<ArgumentOutOfRangeException>();
    }

    [Fact]
    public void Resolve_SaturationCap_ThrowsIOException()
    {
        var path = Path.Combine(_tempDir, "x.txt");
        File.WriteAllText(path, "0");
        File.WriteAllText(Path.Combine(_tempDir, "x (1).txt"), "1");
        File.WriteAllText(Path.Combine(_tempDir, "x (2).txt"), "2");

        FluentActions.Invoking(() => UniqueOutputPath.Resolve(path, maxSuffix: 2))
            .Should().Throw<IOException>();
    }

    [Fact]
    public void TryResolve_NonExistent_ReturnsTrueAndUnchanged()
    {
        var path = Path.Combine(_tempDir, "fresh.png");

        var ok = UniqueOutputPath.TryResolve(path, out var resolved);

        ok.Should().BeTrue();
        resolved.Should().Be(path);
    }

    [Fact]
    public void TryResolve_Saturation_ReturnsFalseAndOriginal()
    {
        var path = Path.Combine(_tempDir, "y.txt");
        File.WriteAllText(path, "0");
        File.WriteAllText(Path.Combine(_tempDir, "y (1).txt"), "1");

        var ok = UniqueOutputPath.TryResolve(path, out var resolved, maxSuffix: 1);

        ok.Should().BeFalse();
        resolved.Should().Be(path);
    }
}
