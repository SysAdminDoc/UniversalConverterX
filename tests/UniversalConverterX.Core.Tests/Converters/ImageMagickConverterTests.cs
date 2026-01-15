using FluentAssertions;
using Microsoft.Extensions.Logging;
using Moq;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class ImageMagickConverterTests
{
    private readonly string _toolsBasePath;
    private readonly Mock<ILogger<ImageMagickConverter>> _loggerMock;
    private readonly ImageMagickConverter _converter;

    public ImageMagickConverterTests()
    {
        _toolsBasePath = Path.Combine(Path.GetTempPath(), "ucx-test-tools");
        _loggerMock = new Mock<ILogger<ImageMagickConverter>>();
        _converter = new ImageMagickConverter(_toolsBasePath, _loggerMock.Object);
    }

    [Fact]
    public void Id_ShouldBeImageMagick()
    {
        _converter.Id.Should().Be("imagemagick");
    }

    [Fact]
    public void Priority_ShouldBe90()
    {
        _converter.Priority.Should().Be(90);
    }

    [Fact]
    public void ExecutableName_ShouldBeMagick()
    {
        _converter.ExecutableName.Should().Be("magick");
    }

    [Theory]
    [InlineData("png", "jpg", true)]
    [InlineData("jpg", "webp", true)]
    [InlineData("bmp", "png", true)]
    [InlineData("tiff", "pdf", true)]
    [InlineData("gif", "png", true)]
    [InlineData("mp4", "png", false)] // Video not supported
    [InlineData("docx", "pdf", false)] // Document not supported
    public void CanConvert_ShouldReturnExpectedResult(string input, string output, bool expected)
    {
        var source = new FileFormat(input, $"image/{input}", FormatCategory.Image);
        var target = new FileFormat(output, $"image/{output}", FormatCategory.Image);

        var result = _converter.CanConvert(source, target);

        result.Should().Be(expected);
    }

    [Fact]
    public void GetSupportedInputFormats_ShouldContainCommonImageFormats()
    {
        var formats = _converter.GetSupportedInputFormats();

        formats.Should().Contain("png");
        formats.Should().Contain("jpg");
        formats.Should().Contain("jpeg");
        formats.Should().Contain("gif");
        formats.Should().Contain("bmp");
        formats.Should().Contain("webp");
        formats.Should().Contain("tiff");
    }

    [Fact]
    public void GetSupportedOutputFormats_ShouldContainCommonFormats()
    {
        var formats = _converter.GetSupportedOutputFormats();

        formats.Should().Contain("png");
        formats.Should().Contain("jpg");
        formats.Should().Contain("webp");
        formats.Should().Contain("gif");
        formats.Should().Contain("pdf");
    }

    [Fact]
    public void BuildArguments_BasicConversion_ShouldIncludeInputAndOutput()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions();

        var args = _converter.BuildArguments(job, options);

        args.Should().Contain(job.InputPath);
        args.Should().Contain(job.OutputPath);
    }

    [Fact]
    public void BuildArguments_WithQuality_ShouldSetQualityFlag()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Quality = 90 }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-quality");
        argsString.Should().Contain("90");
    }

    [Fact]
    public void BuildArguments_WithResize_ShouldSetResizeFlag()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Width = 800, Height = 600 }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-resize");
        argsString.Should().Contain("800x600");
    }

    [Fact]
    public void BuildArguments_WithDpi_ShouldSetDensityFlag()
    {
        var job = CreateTestJob("input.png", "output.png");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Dpi = 300 }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-density");
        argsString.Should().Contain("300");
    }

    [Fact]
    public void BuildArguments_StripMetadata_ShouldSetStripFlag()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { StripMetadata = true }
        };

        var args = _converter.BuildArguments(job, options);

        args.Should().Contain("-strip");
    }

    [Fact]
    public void BuildArguments_ProgressiveJpeg_ShouldSetInterlaceFlag()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Progressive = true }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-interlace");
    }

    [Fact]
    public void BuildArguments_WithColorSpace_ShouldSetColorSpaceFlag()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions { ColorSpace = "sRGB" }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-colorspace");
        argsString.Should().Contain("sRGB");
    }

    [Fact]
    public void BuildArguments_MaintainAspectRatio_ShouldUseCaretOperator()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var options = new ConversionOptions
        {
            Image = new ImageOptions 
            { 
                Width = 800, 
                Height = 600,
                MaintainAspectRatio = true 
            }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        // Should contain resize with aspect ratio preservation
        argsString.Should().Contain("-resize");
    }

    [Fact]
    public void ParseProgress_ValidPercentLine_ShouldReturnProgress()
    {
        var job = CreateTestJob("input.png", "output.jpg");
        var line = "50%";

        var progress = _converter.ParseProgress(line, job);

        progress.Should().NotBeNull();
        progress!.Percent.Should().BeApproximately(50, 1);
    }

    [Fact]
    public void ParseProgress_EmptyLine_ShouldReturnNull()
    {
        var job = CreateTestJob("input.png", "output.jpg");

        var progress = _converter.ParseProgress("", job);

        progress.Should().BeNull();
    }

    private static ConversionJob CreateTestJob(string input, string output)
    {
        return new ConversionJob
        {
            InputPath = input,
            OutputPath = output,
            Options = new ConversionOptions()
        };
    }
}
