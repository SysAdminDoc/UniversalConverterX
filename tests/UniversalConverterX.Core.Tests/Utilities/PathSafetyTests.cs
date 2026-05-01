using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class PathSafetyTests
{
    [Theory]
    [InlineData("mp4", "mp4")]
    [InlineData(".PNG", "png")]
    [InlineData("tar.gz", "tar.gz")]
    [InlineData("  .WebP  ", "webp")]
    public void TryNormalizeExtension_WithSafeExtension_ShouldNormalize(string input, string expected)
    {
        var ok = PathSafety.TryNormalizeExtension(input, out var normalized);

        ok.Should().BeTrue();
        normalized.Should().Be(expected);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData(".")]
    [InlineData("..")]
    [InlineData("../mp4")]
    [InlineData(@"mp4\png")]
    [InlineData("mp4/png")]
    [InlineData("mp4:png")]
    [InlineData("bad ext")]
    public void TryNormalizeExtension_WithUnsafeExtension_ShouldReject(string input)
    {
        var ok = PathSafety.TryNormalizeExtension(input, out var normalized);

        ok.Should().BeFalse();
        normalized.Should().BeEmpty();
    }

    [Fact]
    public void TryNormalizeExtension_WithDirectorySentinel_ShouldPreserveSentinelWhenRequested()
    {
        PathSafety.TryNormalizeExtension(
                PathSafety.DirectoryOutputSentinel,
                out var normalized,
                allowDirectorySentinel: true)
            .Should().BeTrue();
        normalized.Should().Be(PathSafety.DirectoryOutputSentinel);
    }
}
