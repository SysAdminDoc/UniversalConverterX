using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class SidecarNamingTests
{
    [Theory]
    [InlineData("videocrush", "videocrush.exe")]
    [InlineData("ab-av1", "ab-av1-sidecar.exe")]
    [InlineData("AB-AV1", "ab-av1-sidecar.exe")]
    public void ExecutableName_AvoidsUpstreamBinaryCollisions(string engine, string expected)
    {
        Assert.Equal(expected, SidecarNaming.ExecutableName(engine));
    }
}
