using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class VipsConverterTests
{
    private readonly VipsConverter _converter =
        new(Path.Combine(Path.GetTempPath(), "ucx-test-tools"));

    [Fact]
    public void BuildArguments_NoResize_UsesSaveOperationWithTrailingOptions()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Quality = QualityPreset.High,
            Image = new ImageOptions { StripMetadata = true, Progressive = true }
        };

        var args = _converter.BuildArguments(job, options);

        args[0].Should().Be("jpegsave");
        args.Should().Contain("output.jpg");
        args.Should().Contain("Q=85");
        args.Should().Contain("interlace=true");
        args.Should().Contain("strip=true");
    }

    [Fact]
    public void BuildArguments_WithResize_PreservesSaveOptionsInFilenameSuffix()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Quality = QualityPreset.Low, // Q=55
            Image = new ImageOptions
            {
                Width = 500,
                StripMetadata = true,
            }
        };

        var args = _converter.BuildArguments(job, options);

        args[0].Should().Be("thumbnail");
        args[1].Should().Be("input.png");
        // The critical regression: quality/strip must ride in the output suffix,
        // not be discarded when a resize dimension is set.
        args[2].Should().Be("output.jpg[Q=55,strip=true]");
        args.Should().Contain("500");
    }

    [Fact]
    public void BuildArguments_WithResize_NoOptions_LeavesOutputPathClean()
    {
        var job = CreateTestJob("input.png", "output.gif");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Width = 200, Height = 100 }
        };

        var args = _converter.BuildArguments(job, options);

        args[0].Should().Be("thumbnail");
        // gif carries effort=7, so it still gets a suffix; assert it's bracketed.
        args[2].Should().Be("output.gif[effort=7]");
        args.Should().Contain("200x100");
    }

    [Fact]
    public void BuildArguments_WithResizeNoAspect_AddsCropCentre()
    {
        var job = CreateTestJob("input.png", "output.png");
        var options = new ConversionOptions
        {
            Image = new ImageOptions
            {
                Width = 300,
                Height = 300,
                MaintainAspectRatio = false,
            }
        };

        var args = _converter.BuildArguments(job, options);

        args[0].Should().Be("thumbnail");
        args.Should().Contain("crop=centre");
    }

    private static ConversionJob CreateTestJob(string input, string output) => new()
    {
        InputPath = input,
        OutputPath = output,
        Options = new ConversionOptions()
    };
}
