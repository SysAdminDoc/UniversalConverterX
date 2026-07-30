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
    [InlineData("yt-dlp", "2026.07.04", true, "2026.07.04")]
    [InlineData("yt-dlp", "2026.06.09", false, "2026.06.09")]
    [InlineData("deno", "deno 2.9.3", true, "2.9.3")]
    [InlineData("deno", "deno 2.2.0", false, "2.2.0")]
    [InlineData("libheif", "libheif version: 1.22.0", true, "1.22.0")]
    [InlineData("libheif", "1.18.1", false, "1.18.1")]
    [InlineData("heif-enc", "1.19.0", false, "1.19.0")]
    [InlineData("libjxl", "cjxl v0.11.2 [AVX2]", true, "0.11.2")]
    [InlineData("cjxl", "0.11.1", false, "0.11.1")]
    [InlineData("vips", "vips-8.18.3", true, "8.18.3")]
    [InlineData("libvips", "8.18.2", false, "8.18.2")]
    [InlineData("vips", "vips-8.19.0", false, "8.19.0")]
    [InlineData("vips", "vips-8.19.1", true, "8.19.1")]
    [InlineData("ghostscript", "GPL Ghostscript 10.07.1", true, "10.07.1")]
    [InlineData("gswin64c", "10.05.1", false, "10.05.1")]
    [InlineData("gs", "10.07.1", true, "10.07.1")]
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
    public void Assess_ExplicitlyRejectedBuild_ReportsPolicyReason()
    {
        var result = ToolVersionPolicy.Assess("vips", "vips-8.19.0");

        result.MeetsMinimum.Should().BeFalse();
        result.IsExplicitlyRejected.Should().BeTrue();
        result.Requirement!.MinimumVersion.Should().Be("8.18.3");
        result.Requirement.RejectedVersions.Should().Contain("8.19.0");
    }

    [Fact]
    public void Assess_UnknownTool_HasNoSecurityFloor()
    {
        var result = ToolVersionPolicy.Assess("pandoc", "3.7.0");

        result.HasRequirement.Should().BeFalse();
        result.MeetsMinimum.Should().BeTrue();
    }
}
