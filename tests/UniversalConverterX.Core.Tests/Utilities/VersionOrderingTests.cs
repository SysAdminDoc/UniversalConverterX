using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class VersionOrderingTests
{
    [Theory]
    [InlineData("2.22.0", "v2.22.1", -1)]
    [InlineData("2.22.1", "v2.22.1", 0)]
    [InlineData("2.22.1.0", "v2.22.1", 0)]
    [InlineData("2.23.0-nightly.20260716", "v2.22.1", 1)]
    [InlineData("whisper.cpp version 1.7.7", "v1.7.6", 1)]
    [InlineData("deno 2.9.3", "v2.9.3", 0)]
    [InlineData("2026.07.04\r\n", "2026.07.04", 0)]
    [InlineData("1.10", "v1.9.9", 1)]
    [InlineData("1.2", "v1.2.0", 0)]
    [InlineData("2.22.1-rc.2", "v2.22.1", -1)]
    [InlineData("2.22.1+build.9", "v2.22.1", 0)]
    [InlineData("8.1.2-essentials_build", "v8.1.2", 0)]
    public void TryCompare_OrdersNormalizedVersions(
        string installed,
        string latest,
        int expectedSign)
    {
        var comparison = VersionOrdering.TryCompare(installed, latest);

        comparison.Should().NotBeNull();
        Math.Sign(comparison!.Value).Should().Be(expectedSign);
    }

    [Theory]
    [InlineData(null, "v2.22.1")]
    [InlineData("2.22.1", null)]
    [InlineData("not a version", "v2.22.1")]
    [InlineData("8.1.2", "latest")]
    [InlineData("8.1.2", "autobuild-2026-07-16")]
    public void TryCompare_UnparseableValues_ReturnsUnknown(string? installed, string? latest)
    {
        VersionOrdering.TryCompare(installed, latest).Should().BeNull();
        VersionOrdering.IsUpdateAvailable(installed, latest).Should().BeFalse();
    }

    [Fact]
    public void IsUpdateAvailable_DoesNotDowngradeNewerNightly()
    {
        VersionOrdering.IsUpdateAvailable(
            "UniversalConverterX 2.23.0-nightly.20260716",
            "v2.22.1").Should().BeFalse();
    }
}
