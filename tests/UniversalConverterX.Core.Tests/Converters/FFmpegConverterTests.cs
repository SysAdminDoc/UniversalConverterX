using FluentAssertions;
using Microsoft.Extensions.Logging;
using Moq;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class FFmpegConverterTests
{
    private readonly string _toolsBasePath;
    private readonly Mock<ILogger<FFmpegConverter>> _loggerMock;
    private readonly FFmpegConverter _converter;

    public FFmpegConverterTests()
    {
        _toolsBasePath = Path.Combine(Path.GetTempPath(), "ucx-test-tools");
        _loggerMock = new Mock<ILogger<FFmpegConverter>>();
        _converter = new FFmpegConverter(_toolsBasePath, _loggerMock.Object);
    }

    [Fact]
    public void Id_ShouldBeFFmpeg()
    {
        _converter.Id.Should().Be("ffmpeg");
    }

    [Fact]
    public void Name_ShouldBeFFmpeg()
    {
        _converter.Name.Should().Be("FFmpeg");
    }

    [Fact]
    public void Priority_ShouldBe100()
    {
        _converter.Priority.Should().Be(100);
    }

    [Fact]
    public void ExecutableName_ShouldBeFFmpeg()
    {
        _converter.ExecutableName.Should().Be("ffmpeg");
    }

    [Theory]
    [InlineData("mp4", "mp3", true)]
    [InlineData("mp4", "mkv", true)]
    [InlineData("wav", "mp3", true)]
    [InlineData("mp4", "webm", true)]
    [InlineData("png", "mp4", true)]  // Image sequence to video
    [InlineData("docx", "pdf", false)] // Not a video/audio format
    [InlineData("xyz", "abc", false)]  // Unknown formats
    public void CanConvert_ShouldReturnExpectedResult(string input, string output, bool expected)
    {
        var source = new FileFormat(input, $"test/{input}", FormatCategory.Unknown);
        var target = new FileFormat(output, $"test/{output}", FormatCategory.Unknown);

        var result = _converter.CanConvert(source, target);

        result.Should().Be(expected);
    }

    [Fact]
    public void GetSupportedInputFormats_ShouldContainCommonVideoFormats()
    {
        var formats = _converter.GetSupportedInputFormats();

        formats.Should().Contain("mp4");
        formats.Should().Contain("mkv");
        formats.Should().Contain("avi");
        formats.Should().Contain("mov");
        formats.Should().Contain("webm");
    }

    [Fact]
    public void GetSupportedInputFormats_ShouldContainCommonAudioFormats()
    {
        var formats = _converter.GetSupportedInputFormats();

        formats.Should().Contain("mp3");
        formats.Should().Contain("wav");
        formats.Should().Contain("flac");
        formats.Should().Contain("aac");
        formats.Should().Contain("ogg");
    }

    [Fact]
    public void GetSupportedOutputFormats_ShouldContainCommonFormats()
    {
        var formats = _converter.GetSupportedOutputFormats();

        formats.Should().Contain("mp4");
        formats.Should().Contain("mp3");
        formats.Should().Contain("webm");
        formats.Should().Contain("gif");
    }

    [Fact]
    public void GetOutputFormatsFor_Mp4_ShouldReturnAllOutputFormats()
    {
        var formats = _converter.GetOutputFormatsFor("mp4");

        formats.Should().NotBeEmpty();
        formats.Should().Contain("mp3"); // Audio extraction
        formats.Should().Contain("mkv"); // Video transcode
    }

    [Fact]
    public void BuildArguments_BasicVideoConversion_ShouldIncludeRequiredFlags()
    {
        var job = CreateTestJob("input.mp4", "output.mkv");
        var options = new ConversionOptions();

        var args = _converter.BuildArguments(job, options);

        args.Should().Contain("-y");
        args.Should().Contain("-hide_banner");
        args.Should().Contain("-i");
        args.Should().Contain(job.InputPath);
        args.Should().Contain(job.OutputPath);
    }

    [Fact]
    public void BuildArguments_AudioExtraction_ShouldIncludeNoVideoFlag()
    {
        var job = CreateTestJob("input.mp4", "output.mp3");
        var options = new ConversionOptions();

        var args = _converter.BuildArguments(job, options);

        args.Should().Contain("-vn"); // No video
    }

    [Fact]
    public void BuildArguments_WithQualityPreset_ShouldSetAppropriateCrf()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions { Quality = QualityPreset.High };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-crf");
        argsString.Should().Contain("18"); // High quality CRF
    }

    [Fact]
    public void BuildArguments_WithResolution_ShouldSetScaleFilter()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions
        {
            Video = new VideoOptions { Width = 1920, Height = 1080 }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-s");
        argsString.Should().Contain("1920x1080");
    }

    [Fact]
    public void BuildArguments_WithFrameRate_ShouldSetFps()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions
        {
            Video = new VideoOptions { Fps = 30 }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-r");
        argsString.Should().Contain("30");
    }

    [Fact]
    public void BuildArguments_WithStartTime_ShouldSetSeekFlag()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions
        {
            Video = new VideoOptions { StartTime = TimeSpan.FromSeconds(30) }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-ss");
    }

    [Fact]
    public void BuildArguments_WithDuration_ShouldSetTimeFlag()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions
        {
            Video = new VideoOptions { Duration = TimeSpan.FromMinutes(5) }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-t");
    }

    [Fact]
    public void BuildArguments_WithHardwareAcceleration_ShouldSetHwaccelFlag()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions
        {
            UseHardwareAcceleration = true,
            HardwareAccel = HardwareAcceleration.Cuda
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-hwaccel");
        argsString.Should().Contain("cuda");
    }

    [Fact]
    public void BuildArguments_PreserveMetadata_ShouldSetMapMetadataFlag()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var options = new ConversionOptions { PreserveMetadata = true };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-map_metadata");
    }

    [Fact]
    public void BuildArguments_AudioOptions_ShouldSetBitrateAndSampleRate()
    {
        var job = CreateTestJob("input.wav", "output.mp3");
        var options = new ConversionOptions
        {
            Audio = new AudioOptions
            {
                Bitrate = 320,
                SampleRate = 44100
            }
        };

        var args = _converter.BuildArguments(job, options);
        var argsString = string.Join(" ", args);

        argsString.Should().Contain("-b:a");
        argsString.Should().Contain("320k");
        argsString.Should().Contain("-ar");
        argsString.Should().Contain("44100");
    }

    [Fact]
    public void ParseProgress_ValidProgressLine_ShouldReturnProgress()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var line = "frame=  100 fps=30.0 time=00:00:03.33 speed=1.0x";

        var progress = _converter.ParseProgress(line, job);

        progress.Should().NotBeNull();
        progress!.CurrentFrame.Should().Be(100);
        progress.Fps.Should().Be(30.0);
        progress.Speed.Should().Be(1.0);
    }

    [Fact]
    public void ParseProgress_DurationLine_ShouldSetTotalDuration()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        var durationLine = "Duration: 00:05:30.00, start: 0.000000";

        var progress1 = _converter.ParseProgress(durationLine, job);
        
        // Now parse a time progress line
        var timeLine = "frame=  100 fps=30.0 time=00:02:45.00 speed=1.0x";
        var progress2 = _converter.ParseProgress(timeLine, job);

        progress2.Should().NotBeNull();
        progress2!.TotalDuration.Should().NotBeNull();
        progress2.Percent.Should().BeApproximately(50, 1);
    }

    [Fact]
    public void ParseProgress_EmptyLine_ShouldReturnNull()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");

        var progress = _converter.ParseProgress("", job);

        progress.Should().BeNull();
    }

    [Fact]
    public void ParseProgress_NonProgressLine_ShouldReturnNull()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");

        var progress = _converter.ParseProgress("Some random output", job);

        progress.Should().BeNull();
    }

    [Fact]
    public void ValidateJob_MissingInputFile_ShouldReturnInvalid()
    {
        var job = CreateTestJob("nonexistent.mp4", "output.mp4");

        var result = _converter.ValidateJob(job);

        result.IsValid.Should().BeFalse();
        result.ErrorMessage.Should().Contain("not found");
    }

    [Fact]
    public void ValidateJob_UnsupportedInputFormat_ShouldReturnInvalid()
    {
        var tempFile = Path.GetTempFileName();
        File.Move(tempFile, tempFile + ".xyz");
        tempFile += ".xyz";

        try
        {
            var job = CreateTestJob(tempFile, "output.mp4");

            var result = _converter.ValidateJob(job);

            result.IsValid.Should().BeFalse();
            result.ErrorMessage.Should().Contain("Unsupported input format");
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public void ValidateJob_OutputExistsNoOverwrite_ShouldReturnInvalid()
    {
        var inputFile = Path.GetTempFileName();
        File.Move(inputFile, inputFile.Replace(".tmp", ".mp4"));
        inputFile = inputFile.Replace(".tmp", ".mp4");

        var outputFile = Path.GetTempFileName();
        File.Move(outputFile, outputFile.Replace(".tmp", ".mkv"));
        outputFile = outputFile.Replace(".tmp", ".mkv");

        try
        {
            var job = new ConversionJob
            {
                InputPath = inputFile,
                OutputPath = outputFile,
                Options = new ConversionOptions { OverwriteExisting = false }
            };

            var result = _converter.ValidateJob(job);

            result.IsValid.Should().BeFalse();
            result.ErrorMessage.Should().Contain("already exists");
        }
        finally
        {
            if (File.Exists(inputFile)) File.Delete(inputFile);
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
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
