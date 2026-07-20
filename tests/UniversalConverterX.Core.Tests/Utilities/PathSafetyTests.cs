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

    [Theory]
    [InlineData("holiday photo", "holiday photo")]
    [InlineData("na/me:with*bad?", "na_me_with_bad_")]
    public void SanitizeFileNameComponent_WithOrdinaryName_ShouldSanitizeSeparatorsOnly(
        string input, string expected)
    {
        PathSafety.SanitizeFileNameComponent(input).Should().Be(expected);
    }

    [Theory]
    [InlineData("CON", "_CON")]
    [InlineData("con", "_con")]
    [InlineData("NUL.txt", "_NUL.txt")]
    [InlineData("COM1", "_COM1")]
    [InlineData("lpt9.jpg", "_lpt9.jpg")]
    [InlineData("PRN.tar.gz", "_PRN.tar.gz")]
    public void SanitizeFileNameComponent_WithReservedDeviceName_ShouldNeutralize(
        string input, string expected)
    {
        PathSafety.SanitizeFileNameComponent(input).Should().Be(expected);
    }

    [Theory]
    [InlineData("CON.", "_CON")]
    [InlineData("report.  ", "report")]
    public void SanitizeFileNameComponent_WithTrailingDotsOrSpaces_ShouldStripThem(
        string input, string expected)
    {
        PathSafety.SanitizeFileNameComponent(input).Should().Be(expected);
    }

    [Theory]
    [InlineData("console", "console")]
    [InlineData("COM0", "COM0")]
    [InlineData("COM10", "COM10")]
    [InlineData("NULL", "NULL")]
    public void SanitizeFileNameComponent_WithNonReservedLookalikes_ShouldLeaveUnchanged(
        string input, string expected)
    {
        PathSafety.SanitizeFileNameComponent(input).Should().Be(expected);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("...")]
    public void SanitizeFileNameComponent_WithEmptyOrDots_ShouldReturnFallback(string input)
    {
        PathSafety.SanitizeFileNameComponent(input, "fallback").Should().Be("fallback");
    }
}
