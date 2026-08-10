using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class AudioConversionCommandBuilderTests
{
    [Fact]
    public void Build_ShouldUseVbrQualityInsteadOfFixedBitrate()
    {
        var arguments = AudioConversionCommandBuilder.Build(
            [@"C:\Audio Files\café.wav"],
            new AudioConversionOptions
            {
                Format = "mp3",
                OutputDirectory = @"C:\Converted Audio",
                UseVariableBitrate = true,
                VariableBitrateQuality = 3,
                Bitrate = "320k",
            });

        arguments.Should().Equal(
            "convert",
            "--format", "mp3",
            "--output-dir", @"C:\Converted Audio",
            "--vbr-quality", "3",
            "--input", @"C:\Audio Files\café.wav");
        arguments.Should().NotContain("--bitrate");
    }

    [Fact]
    public void Build_ShouldIncludeOnlyMatchingEncoderAdvancedOptions()
    {
        var arguments = AudioConversionCommandBuilder.Build(
            ["input.flac"],
            new AudioConversionOptions
            {
                Format = "fdk-aac",
                OutputDirectory = Path.GetTempPath(),
                UseVariableBitrate = true,
                VariableBitrateQuality = 2,
                SampleRate = 48_000,
                Channels = 2,
                FdkCutoff = 20_000,
                FdkAfterburner = true,
                FdkProfile = "aac_low",
                OpusApplication = "voip",
                OpusFrameDuration = 5,
                VorbisManaged = true,
            });

        arguments.Should().ContainInOrder(
            "--vbr-quality", "2",
            "--sample-rate", "48000",
            "--channels", "2",
            "--fdk-cutoff", "20000",
            "--fdk-afterburner", "true",
            "--fdk-profile", "aac_low");
        arguments.Should().NotContain("--opus-application");
        arguments.Should().NotContain("--vorbis-managed");
    }

    [Fact]
    public void Build_ShouldEmitOpusAmbisonicsOnlyWhenEnabled()
    {
        var enabled = AudioConversionCommandBuilder.Build(
            ["foa.wav"],
            new AudioConversionOptions
            {
                Format = "opus",
                OutputDirectory = Path.GetTempPath(),
                Channels = 4,
                OpusAmbisonics = "acn-sn3d",
            });
        enabled.Should().ContainInOrder("--opus-ambisonics", "acn-sn3d");

        var disabled = AudioConversionCommandBuilder.Build(
            ["stereo.wav"],
            new AudioConversionOptions
            {
                Format = "opus",
                OutputDirectory = Path.GetTempPath(),
                OpusAmbisonics = "off",
            });
        disabled.Should().NotContain("--opus-ambisonics");
    }

    [Fact]
    public void Build_ShouldRejectUnknownOpusAmbisonicsMode()
    {
        var action = () => AudioConversionCommandBuilder.Build(
            ["foa.wav"],
            new AudioConversionOptions
            {
                Format = "opus",
                OutputDirectory = Path.GetTempPath(),
                OpusAmbisonics = "b-format",
            });
        action.Should().Throw<ArgumentException>();
    }

    [Theory]
    [InlineData(44_100)]
    [InlineData(96_000)]
    public void Build_ShouldRejectUnsupportedOpusSampleRates(int sampleRate)
    {
        var action = () => AudioConversionCommandBuilder.Build(
            ["input.wav"],
            new AudioConversionOptions
            {
                Format = "opus",
                OutputDirectory = Path.GetTempPath(),
                SampleRate = sampleRate,
            });

        action.Should().Throw<ArgumentOutOfRangeException>()
            .WithMessage("*Opus HD at 96000 Hz is not enabled.*");
    }

    [Fact]
    public void Build_ShouldAllowTheBundledOpusEncoderSampleRate()
    {
        var arguments = AudioConversionCommandBuilder.Build(
            ["input.wav"],
            new AudioConversionOptions
            {
                Format = "opus",
                OutputDirectory = Path.GetTempPath(),
                SampleRate = 48_000,
            });

        arguments.Should().ContainInOrder("--sample-rate", "48000");
    }

    [Fact]
    public void Build_ShouldMakeManagedVorbisUseBoundedBitrateMode()
    {
        var arguments = AudioConversionCommandBuilder.Build(
            ["one.wav", "two.wav"],
            new AudioConversionOptions
            {
                Format = "vorbis",
                OutputDirectory = Path.GetTempPath(),
                UseVariableBitrate = true,
                VariableBitrateQuality = 1,
                Bitrate = "160K",
                VorbisManaged = true,
            });

        arguments.Should().ContainInOrder("--vorbis-managed", "--bitrate", "160k");
        arguments.Should().NotContain("--vbr-quality");
        arguments.TakeLast(3).Should().Equal("--input", "one.wav", "two.wav");
    }

    [Theory]
    [InlineData("shell|inject")]
    [InlineData("0k")]
    [InlineData("192")]
    public void Build_ShouldRejectInvalidFixedBitrates(string bitrate)
    {
        var action = () => AudioConversionCommandBuilder.Build(
            ["input.wav"],
            new AudioConversionOptions
            {
                Format = "aac",
                OutputDirectory = Path.GetTempPath(),
                Bitrate = bitrate,
            });

        action.Should().Throw<ArgumentException>();
    }
}
