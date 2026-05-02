using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class OutputSizeEstimatorTests
{
    [Fact]
    public void ForLosslessCopy_Returns_InputPlusSmallOverhead()
    {
        var inputBytes = 100L * 1024 * 1024; // 100 MiB

        var result = OutputSizeEstimator.ForLosslessCopy(inputBytes);

        result.Kind.Should().Be(OutputSizeEstimateKind.LosslessCopy);
        result.Bytes.Should().NotBeNull();
        result.Bytes.Should().BeGreaterThan(inputBytes);
        // Overhead is 0.5%, floored at 32 KiB — for 100 MiB that's 512 KiB.
        result.Bytes.Should().BeLessThan(inputBytes + (long)(inputBytes * 0.02));
        result.DisplayLabel.Should().NotStartWith("~");
    }

    [Fact]
    public void ForLosslessCopy_ZeroInput_ReturnsUnavailable()
    {
        var result = OutputSizeEstimator.ForLosslessCopy(0);

        result.Kind.Should().Be(OutputSizeEstimateKind.Unavailable);
        result.Bytes.Should().BeNull();
    }

    [Fact]
    public void ForConstantBitrate_KnownInputs_ProducesPlausibleEstimate()
    {
        // 5 Mbps video + 192 kbps audio for 60s → ~38.94 MB payload + 1% overhead.
        var result = OutputSizeEstimator.ForConstantBitrate(
            videoBitsPerSecond: 5_000_000,
            audioBitsPerSecond: 192_000,
            durationSeconds: 60.0);

        result.Kind.Should().Be(OutputSizeEstimateKind.ConstantBitrate);
        result.Bytes.Should().NotBeNull();
        var expectedPayload = (5_000_000L + 192_000L) * 60L / 8L;
        result.Bytes.Should().BeInRange(expectedPayload,
            (long)(expectedPayload * 1.05) + 32 * 1024);
        result.DisplayLabel.Should().NotStartWith("~");
    }

    [Fact]
    public void ForConstantBitrate_NoBitrate_ReturnsUnavailable()
    {
        var result = OutputSizeEstimator.ForConstantBitrate(0, 0, 60.0);

        result.Kind.Should().Be(OutputSizeEstimateKind.Unavailable);
    }

    [Fact]
    public void ForConstantBitrate_ZeroDuration_ReturnsUnavailable()
    {
        var result = OutputSizeEstimator.ForConstantBitrate(5_000_000, 192_000, 0);

        result.Kind.Should().Be(OutputSizeEstimateKind.Unavailable);
    }

    [Fact]
    public void ForVariableBitrate_PrefixesWithTilde()
    {
        var result = OutputSizeEstimator.ForVariableBitrate(
            targetAverageBitsPerSecond: 4_000_000,
            audioBitsPerSecond: 128_000,
            durationSeconds: 120.0);

        result.Kind.Should().Be(OutputSizeEstimateKind.VariableBitrate);
        result.Bytes.Should().NotBeNull();
        result.DisplayLabel.Should().StartWith("~");
        result.Caveat.Should().Contain("±25%");
    }

    [Fact]
    public void ForVariableBitrate_SceneComplexityScalesEstimate()
    {
        var baseline = OutputSizeEstimator.ForVariableBitrate(
            targetAverageBitsPerSecond: 4_000_000,
            audioBitsPerSecond: 128_000,
            durationSeconds: 120.0);
        var complex = OutputSizeEstimator.ForVariableBitrate(
            targetAverageBitsPerSecond: 4_000_000,
            audioBitsPerSecond: 128_000,
            durationSeconds: 120.0,
            sceneComplexityFactor: 1.4);

        complex.Bytes.Should().BeGreaterThan(baseline.Bytes!.Value);
    }

    [Fact]
    public void ForVariableBitrate_ClampsExtremeComplexityFactor()
    {
        // 5x complexity is unrealistic; estimator should clamp to <= 1.8.
        var sane = OutputSizeEstimator.ForVariableBitrate(
            targetAverageBitsPerSecond: 4_000_000,
            audioBitsPerSecond: 128_000,
            durationSeconds: 60.0,
            sceneComplexityFactor: 1.8);
        var insane = OutputSizeEstimator.ForVariableBitrate(
            targetAverageBitsPerSecond: 4_000_000,
            audioBitsPerSecond: 128_000,
            durationSeconds: 60.0,
            sceneComplexityFactor: 5.0);

        insane.Bytes.Should().Be(sane.Bytes);
    }

    [Theory]
    [InlineData(0L, "0 B")]
    [InlineData(1023L, "1023 B")]
    [InlineData(1024L, "1.0 KiB")]
    [InlineData(1024L * 1024, "1.0 MiB")]
    [InlineData(2L * 1024 * 1024 * 1024, "2.0 GiB")]
    public void FormatBytes_RendersBinaryPrefixes(long bytes, string expected)
    {
        OutputSizeEstimator.FormatBytes(bytes).Should().Be(expected);
    }

    [Fact]
    public void Unavailable_ReturnsExpectedDisplay()
    {
        var result = OutputSizeEstimator.Unavailable("custom reason");

        result.Kind.Should().Be(OutputSizeEstimateKind.Unavailable);
        result.Bytes.Should().BeNull();
        result.DisplayLabel.Should().Be("—");
        result.Caveat.Should().Be("custom reason");
    }
}
