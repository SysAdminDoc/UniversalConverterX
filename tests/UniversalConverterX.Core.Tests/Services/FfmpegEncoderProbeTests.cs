using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class FfmpegEncoderProbeTests
{
    private const string EncodersOutput = """
        Encoders:
         V..... = Video
         A..... = Audio
         S..... = Subtitle
         ------
         V....D libx264              libx264 H.264 / AVC (codec h264)
         V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
         V....D hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)
         V....D av1_amf              AMD AMF AV1 encoder (codec av1)
         V....D hevc_qsv             Intel Quick Sync Video HEVC encoder (codec hevc)
         V....D av1_qsv              Intel Quick Sync Video AV1 encoder (codec av1)
         V....D h264_d3d12va         D3D12VA H.264 encoder (codec h264)
         A....D aac                  AAC (Advanced Audio Coding)
        """;

    [Fact]
    public void ParseEncoderNames_ExtractsAllEncoderTokens()
    {
        var names = FfmpegEncoderProbe.ParseEncoderNames(EncodersOutput);

        names.Should().Contain(["libx264", "h264_nvenc", "av1_amf", "hevc_qsv", "av1_qsv", "aac"]);
        names.Should().NotContain("Encoders:");
    }

    [Fact]
    public void DetectHardwareEncoders_ClassifiesVendorAndCodec()
    {
        var hw = FfmpegEncoderProbe.DetectHardwareEncoders(EncodersOutput);

        hw.Should().Contain(e => e.Name == "av1_amf" && e.Codec == "av1" && e.Vendor == HardwareAcceleration.Amf);
        hw.Should().Contain(e => e.Name == "hevc_qsv" && e.Codec == "hevc" && e.Vendor == HardwareAcceleration.Qsv);
        hw.Should().Contain(e => e.Name == "h264_nvenc" && e.Codec == "h264" && e.Vendor == HardwareAcceleration.Nvenc);

        // Software encoders and audio codecs are not hardware encoders.
        hw.Should().NotContain(e => e.Name == "libx264");
        hw.Should().NotContain(e => e.Codec == "aac");
    }

    [Fact]
    public void DetectHardwareEncoders_FindsIntelAndAmdBeyondNvenc()
    {
        var hw = FfmpegEncoderProbe.DetectHardwareEncoders(EncodersOutput);

        hw.Should().Contain(e => e.Vendor == HardwareAcceleration.Amf);
        hw.Should().Contain(e => e.Vendor == HardwareAcceleration.Qsv);
    }

    [Theory]
    [InlineData("nvenc", true)]
    [InlineData("amf", true)]
    [InlineData("qsv", true)]
    [InlineData("d3d12", true)]
    [InlineData("vaapi", false)]
    public void SupportsAcceleration_UsesOnlyProbedEncoderNames(
        string acceleration,
        bool expected)
    {
        FfmpegEncoderProbe.SupportsAcceleration(
                acceleration,
                FfmpegEncoderProbe.ParseEncoderNames(EncodersOutput))
            .Should().Be(expected);
    }

    [Fact]
    public void DescribeUnavailable_ExplainsToolDriverAndVramRequirements()
    {
        var message = FfmpegEncoderProbe.DescribeUnavailable("nvenc", true, []);

        message.Should().Contain("FFmpeg");
        message.Should().Contain("GPU driver");
        message.Should().Contain("VRAM");
    }

    [Fact]
    public void ParseEncoderNames_EmptyOrNull_ReturnsEmpty()
    {
        FfmpegEncoderProbe.ParseEncoderNames("").Should().BeEmpty();
        FfmpegEncoderProbe.ParseEncoderNames("no encoder lines here").Should().BeEmpty();
    }

    [Fact]
    public void Probe_MissingExecutable_ReturnsEmpty()
    {
        FfmpegEncoderProbe.Probe(Path.Combine(Path.GetTempPath(), "does-not-exist-ffmpeg.exe"))
            .Should().BeEmpty();
    }
}
