using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class ToolVersionPolicyTests
{
    [Theory]
    [InlineData("ffmpeg", "ffmpeg version 8.1.2-full_build", true, "8.1.2")]
    [InlineData("ffmpeg", "7.1.2", false, "7.1.2")]
    [InlineData("imagemagick", "ImageMagick 7.1.2-15 Q16-HDRI", true, "7.1.2-15")]
    [InlineData("magick", "7.1.2-14", false, "7.1.2-14")]
    [InlineData("calibre", "ebook-convert.exe (calibre 9.10)", true, "9.10")]
    [InlineData("ebook-convert", "9.9.1", false, "9.9.1")]
    [InlineData("7z", "7-Zip 26.01 (x64)", true, "26.01")]
    [InlineData("7zip", "25.01", false, "25.01")]
    [InlineData("soffice", "LibreOffice 26.2.4.2", true, "26.2.4.2")]
    [InlineData("libreoffice", "25.8.7.1", false, "25.8.7.1")]
    public void Assess_KnownTool_ComparesNumericComponents(
        string toolId,
        string reportedVersion,
        bool expectedMeetsMinimum,
        string expectedDetectedVersion)
    {
        var result = ToolVersionPolicy.Assess(toolId, reportedVersion);

        result.HasRequirement.Should().BeTrue();
        result.VersionKnown.Should().BeTrue();
        result.MeetsMinimum.Should().Be(expectedMeetsMinimum);
        result.DetectedVersion.Should().Be(expectedDetectedVersion);
    }

    [Fact]
    public void Assess_KnownToolWithoutReadableVersion_IsUnverified()
    {
        var result = ToolVersionPolicy.Assess("ffmpeg", "custom nightly build");

        result.HasRequirement.Should().BeTrue();
        result.VersionKnown.Should().BeFalse();
        result.MeetsMinimum.Should().BeFalse();
        result.Requirement!.MinimumVersion.Should().Be("8.1.2");
    }

    [Fact]
    public void Assess_UnknownTool_HasNoSecurityFloor()
    {
        var result = ToolVersionPolicy.Assess("pandoc", "3.7.0");

        result.HasRequirement.Should().BeFalse();
        result.MeetsMinimum.Should().BeTrue();
    }
}
