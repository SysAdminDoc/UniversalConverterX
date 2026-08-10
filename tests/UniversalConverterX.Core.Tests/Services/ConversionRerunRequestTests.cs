using FluentAssertions;
using System.Text.Json;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class ConversionRerunRequestTests
{
    [Fact]
    public void Codec_ShouldRoundTripConverterSettingsWithoutMaterializedArguments()
    {
        var request = new ConversionRerunRequest
        {
            Surface = "compressor",
            SourcePaths = [@"C:\Media\café source.mov"],
            OutputFormat = ".mp4",
            OutputDirectory = @"C:\Output Folder",
            OutputPath = @"C:\Output Folder\café source.mp4",
            FfmpegCommandTemplate = "-i {input} -c:v libx264 {output}",
            Options = new ConversionOptions
            {
                Quality = QualityPreset.Highest,
                PreserveMetadata = false,
                UseHardwareAcceleration = false,
                ForceConverter = "ffmpeg",
                PostConversionAction = PostConversionAction.Move,
                PostConversionArchiveFolder = "converted-sources",
                FfmpegArgumentOverride = ["materialized", "paths", "must", "not", "persist"],
                Video = new VideoOptions { Crf = 18, PixelFormat = "yuv420p10le" },
            },
            PageSettings = new Dictionary<string, string?>
            {
                ["preset"] = "__target__",
                ["targetMegabytes"] = "25",
            },
        };

        var json = ConversionRerunRequestCodec.Serialize(request);
        var parsed = ConversionRerunRequestCodec.TryDeserialize(json, out var restored, out var error);

        parsed.Should().BeTrue(error);
        restored.Should().NotBeNull();
        restored!.SourcePaths.Should().Equal(@"C:\Media\café source.mov");
        restored.Surface.Should().Be("compressor");
        restored.OutputFormat.Should().Be(".mp4");
        restored.PageSettings["preset"].Should().Be("__target__");
        restored.Options.Should().BeEquivalentTo(request.Options, options => options
            .Excluding(item => item.FfmpegArgumentOverride));
        restored.Options.FfmpegArgumentOverride.Should().BeNull();
        json.Should().NotContain("materialized");
    }

    [Theory]
    [InlineData(2, "mp4", "source.mov")]
    [InlineData(1, "../exe", "source.mov")]
    [InlineData(1, "mp4", "")]
    public void Codec_ShouldRejectUnsupportedOrUnsafePayloads(
        int schemaVersion,
        string format,
        string source)
    {
        var json = $"{{\"schemaVersion\":{schemaVersion}," +
                   $"\"sourcePaths\":[{JsonSerializer.Serialize(source)}]," +
                   $"\"outputFormat\":{JsonSerializer.Serialize(format)},\"options\":{{}}}}";

        ConversionRerunRequestCodec.TryDeserialize(json, out var request, out var error)
            .Should().BeFalse();
        request.Should().BeNull();
        error.Should().NotBeNullOrWhiteSpace();
    }
}
