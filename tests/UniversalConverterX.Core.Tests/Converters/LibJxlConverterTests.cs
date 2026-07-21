using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class LibJxlConverterTests
{
    private readonly LibJxlConverter _converter = new(Path.Combine(Path.GetTempPath(), "ucx-jxl-tests"));

    private static ConversionJob Job(string input, string output) => new()
    {
        InputPath = input,
        OutputPath = output,
        Options = new ConversionOptions(),
    };

    [Fact]
    public void BuildArguments_LosslessJpegInput_UsesReversibleRecompression()
    {
        var job = Job("photo.jpg", "photo.jxl");
        var options = new ConversionOptions { Quality = QualityPreset.Lossless };

        var args = _converter.BuildArguments(job, options);

        args.Should().Contain("--lossless_jpeg=1");
        // Distance/effort/progressive are ignored by (and conflict with) JPEG
        // recompression, so they must not be emitted.
        args.Should().NotContain("--progressive");
        args.Should().NotContain("-d");
    }

    [Fact]
    public void BuildArguments_LosslessNonJpegInput_DoesNotUseJpegRecompression()
    {
        var job = Job("photo.png", "photo.jxl");
        var options = new ConversionOptions { Quality = QualityPreset.Lossless };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        args.Should().NotContain("--lossless_jpeg=1");
        joined.Should().Contain("-d 0.0"); // mathematically lossless pixels
    }

    [Fact]
    public void BuildArguments_LossyJpegInput_ReEncodesRatherThanRecompresses()
    {
        var job = Job("photo.jpg", "photo.jxl");
        var options = new ConversionOptions { Quality = QualityPreset.High };

        var args = _converter.BuildArguments(job, options);

        args.Should().NotContain("--lossless_jpeg=1");
        args.Should().Contain("-d");
    }
}
