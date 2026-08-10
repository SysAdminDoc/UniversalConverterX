using System.Globalization;
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
    [InlineData("h264_nvenc", true)]
    [InlineData("hevc_amf", true)]
    [InlineData("av1_qsv", true)]
    [InlineData("h264_d3d12va", true)]
    [InlineData("libx264", false)]
    public void IsHardwareEncoder_RecognizesVendorEncoders(string codec, bool expected)
    {
        FFmpegConverter.IsHardwareEncoder(codec).Should().Be(expected);
    }

    [Theory]
    [InlineData("h264_nvenc", "libx264")]
    [InlineData("hevc_qsv", "libx265")]
    [InlineData("av1_amf", "libsvtav1")]
    [InlineData("vp9_qsv", "libvpx-vp9")]
    [InlineData("libx264", "libx264")]
    public void SoftwareCodecFor_MapsHardwareCodecToEquivalentCpuCodec(
        string codec,
        string expected)
    {
        FFmpegConverter.SoftwareCodecFor(codec).Should().Be(expected);
    }

    [Fact]
    public void ShouldFallbackToSoftware_OnlyForHardwareDiagnostics()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        job.Options.UseHardwareAcceleration = true;
        job.Options.HardwareAccel = HardwareAcceleration.Nvenc;
        var hardwareFailure = ConversionResult.Failed(
            job,
            "Error while opening encoder h264_nvenc",
            TimeSpan.FromSeconds(1),
            exitCode: 1,
            standardError: "Cannot load nvcuda.dll",
            commandLine: "ffmpeg -hwaccel cuda -c:v h264_nvenc output.mp4");

        FFmpegConverter.ShouldFallbackToSoftware(job, hardwareFailure).Should().BeTrue();

        var ordinaryFailure = ConversionResult.Failed(
            job,
            "Invalid data found when processing input",
            TimeSpan.FromSeconds(1),
            exitCode: 1,
            standardError: "Invalid data found when processing input",
            commandLine: "ffmpeg -i input.mp4 output.mp4");
        FFmpegConverter.ShouldFallbackToSoftware(job, ordinaryFailure).Should().BeFalse();
    }

    [Fact]
    public void ShouldFallbackToSoftware_RespectsOptOut()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        job.Options.AllowHardwareFallback = false;
        job.Options.HardwareAccel = HardwareAcceleration.Nvenc;
        var result = ConversionResult.Failed(
            job,
            "Unknown encoder 'h264_nvenc'",
            TimeSpan.FromSeconds(1),
            exitCode: 1,
            commandLine: "ffmpeg -c:v h264_nvenc output.mp4");

        FFmpegConverter.ShouldFallbackToSoftware(job, result).Should().BeFalse();
    }

    [Fact]
    public async Task ConvertAsync_HardwareFailureRetriesCpuAndPreservesVisibleScale()
    {
        var root = Directory.CreateTempSubdirectory("ucx-ffmpeg-fallback-");
        try
        {
            var tools = Path.Combine(root.FullName, "tools");
            Directory.CreateDirectory(Path.Combine(tools, "bin"));
            File.WriteAllBytes(Path.Combine(tools, "bin", "ffmpeg.exe"), [0]);
            var input = Path.Combine(root.FullName, "input.mp4");
            var output = Path.Combine(root.FullName, "output.mp4");
            File.WriteAllBytes(input, [1, 2, 3]);

            var converter = new FailingHardwareFfmpegConverter(tools);
            var job = new ConversionJob
            {
                InputPath = input,
                OutputPath = output,
                Options = new ConversionOptions
                {
                    UseHardwareAcceleration = true,
                    HardwareAccel = HardwareAcceleration.Nvenc,
                    Video = new VideoOptions { Width = 1280, Height = 720 },
                },
            };

            var result = await converter.ConvertAsync(job);

            result.Success.Should().BeTrue();
            result.Capability.Should().BeEquivalentTo(new CapabilityDecision(
                "Nvenc", "libx264", true,
                "Error while opening encoder h264_nvenc | Cannot load nvcuda.dll"));
            converter.Commands.Should().HaveCount(2);
            string.Join(" ", converter.Commands[0]).Should().Contain("h264_nvenc");
            string.Join(" ", converter.Commands[1]).Should().Contain("libx264");
            string.Join(" ", converter.Commands[1]).Should().Contain("1280x720");
            job.Options.UseHardwareAcceleration.Should().BeTrue();
            job.Options.HardwareAccel.Should().Be(HardwareAcceleration.Nvenc);
            File.Exists(output).Should().BeTrue();
        }
        finally
        {
            try { root.Delete(recursive: true); } catch { }
        }
    }

    private sealed class FailingHardwareFfmpegConverter : FFmpegConverter
    {
        public FailingHardwareFfmpegConverter(string toolsBasePath)
            : base(toolsBasePath) { }

        public List<string[]> Commands { get; } = [];

        protected override Task<ProcessResult> ExecuteProcessAsync(
            string executable,
            string[] arguments,
            ConversionJob job,
            IProgress<ConversionProgress>? progress,
            List<string> warnings,
            CancellationToken cancellationToken)
        {
            Commands.Add([.. arguments]);
            if (Commands.Count == 1)
            {
                return Task.FromResult(new ProcessResult
                {
                    Success = false,
                    ExitCode = 1,
                    ErrorMessage = "Error while opening encoder h264_nvenc",
                    StandardError = "Cannot load nvcuda.dll",
                });
            }

            File.WriteAllBytes(job.OutputPath, [4, 5, 6]);
            return Task.FromResult(new ProcessResult
            {
                Success = true,
                ExitCode = 0,
            });
        }
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

    [Theory]
    [InlineData("mp3", "libmp3lame")]
    [InlineData("wav", "pcm_s16le")]
    [InlineData("aiff", "pcm_s16be")]
    [InlineData("flac", "flac")]
    [InlineData("ogg", "libvorbis")]
    [InlineData("opus", "libopus")]
    [InlineData("wma", "wmav2")]
    [InlineData("ac3", "ac3")]
    [InlineData("m4a", "aac")]
    public void BuildArguments_DefaultAudioCodec_MatchesOutputContainer(
        string extension,
        string expectedCodec)
    {
        var job = CreateTestJob("input.wav", $"output.{extension}");

        var args = _converter.BuildArguments(job, new ConversionOptions());

        var codecIndex = Array.IndexOf(args, "-c:a");
        codecIndex.Should().BeGreaterThanOrEqualTo(0);
        args[codecIndex + 1].Should().Be(expectedCodec);
    }

    [Theory]
    [InlineData("webm", "libopus")]
    [InlineData("ogv", "libvorbis")]
    [InlineData("mp4", "aac")]
    public void BuildArguments_DefaultVideoAudioCodec_MatchesOutputContainer(
        string extension,
        string expectedCodec)
    {
        var job = CreateTestJob("input.mp4", $"output.{extension}");

        var args = _converter.BuildArguments(job, new ConversionOptions());

        var codecIndex = Array.IndexOf(args, "-c:a");
        codecIndex.Should().BeGreaterThanOrEqualTo(0);
        args[codecIndex + 1].Should().Be(expectedCodec);
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
    public void BuildArguments_FractionalFrameRate_UsesInvariantDecimalUnderCommaLocale()
    {
        // FFmpeg only accepts '.' as the decimal separator. Under a comma-decimal
        // OS locale (e.g. de-DE) culture-sensitive formatting would emit "29,97",
        // which FFmpeg rejects. The builder must format invariantly regardless of
        // the ambient thread culture.
        var original = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo("de-DE");
            var job = CreateTestJob("input.mp4", "output.mp4");
            var options = new ConversionOptions
            {
                Video = new VideoOptions { Fps = 29.97 },
                Audio = new AudioOptions { Volume = 1.5 },
            };

            var args = _converter.BuildArguments(job, options);

            args.Should().Contain("29.97").And.NotContain("29,97");
            string.Join(" ", args).Should().Contain("volume=1.50").And.NotContain("volume=1,50");
        }
        finally
        {
            CultureInfo.CurrentCulture = original;
        }
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
    public void BuildArguments_WithValidatedOverride_ShouldReturnExactArgumentVector()
    {
        var job = CreateTestJob("input.mp4", "output.mkv");
        var options = new ConversionOptions
        {
            FfmpegArgumentOverride = ["-y", "-i", job.InputPath, "-c", "copy", job.OutputPath],
        };

        var arguments = _converter.BuildArguments(job, options);

        arguments.Should().Equal(options.FfmpegArgumentOverride);
    }

    [Fact]
    public void BuildArguments_WithOverrideForDifferentFile_ShouldFailClosed()
    {
        var job = CreateTestJob("input.mp4", "output.mkv");
        var options = new ConversionOptions
        {
            FfmpegArgumentOverride = ["-i", "different.mp4", job.OutputPath],
        };

        FluentActions.Invoking(() => _converter.BuildArguments(job, options))
            .Should().Throw<InvalidDataException>()
            .WithMessage("*exact input and output paths*");
    }

    [Fact]
    public void BuildArguments_WithInjectedOverrideToken_ShouldFailClosed()
    {
        var job = CreateTestJob("input.mp4", "output.mkv");
        var options = new ConversionOptions
        {
            FfmpegArgumentOverride = ["-i", job.InputPath, "; calc", job.OutputPath],
        };

        FluentActions.Invoking(() => _converter.BuildArguments(job, options))
            .Should().Throw<InvalidDataException>()
            .WithMessage("*forbidden shell metacharacter*");
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
    public void ParseProgress_ConcurrentJobs_ShouldKeepDurationStatePerJob()
    {
        var shortJob = CreateTestJob("short.mp4", "short-output.mp4");
        var longJob = CreateTestJob("long.mp4", "long-output.mp4");

        _converter.ParseProgress("Duration: 00:01:00.00, start: 0.000000", shortJob);
        _converter.ParseProgress("Duration: 00:02:00.00, start: 0.000000", longJob);

        var shortProgress = _converter.ParseProgress(
            "frame=  60 fps=30.0 time=00:01:00.00 speed=1.0x", shortJob);
        var longProgress = _converter.ParseProgress(
            "frame= 120 fps=30.0 time=00:02:00.00 speed=1.0x", longJob);

        shortProgress.Should().NotBeNull();
        shortProgress!.Percent.Should().BeApproximately(100, 0.1);
        shortProgress.TotalDuration.Should().Be(TimeSpan.FromMinutes(1));

        longProgress.Should().NotBeNull();
        longProgress!.Percent.Should().BeApproximately(100, 0.1);
        longProgress.TotalDuration.Should().Be(TimeSpan.FromMinutes(2));
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
    public void ValidateJob_WithDetectedSourceFormat_ShouldUseDetectedFormat()
    {
        var tempFile = Path.GetTempFileName();
        var renamed = tempFile + ".jpg";
        File.Move(tempFile, renamed);

        try
        {
            var job = CreateTestJob(renamed, "output.mp3");
            job.SourceFormat = new FileFormat("mp4", "video/mp4", FormatCategory.Video);

            var result = _converter.ValidateJob(job);

            result.IsValid.Should().BeTrue();
        }
        finally
        {
            if (File.Exists(renamed))
                File.Delete(renamed);
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

    [Fact]
    public void BuildArguments_StreamCopyVideo_CopiesAllStreamsWithoutReencoding()
    {
        var job = CreateTestJob("input.mkv", "output.mp4");
        var options = new ConversionOptions { StreamCopy = true };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-map 0");
        joined.Should().Contain("-c copy");
        joined.Should().NotContain("-crf");
        joined.Should().NotContain("-c:v");
        joined.Should().NotContain("-preset");
        args.Should().Contain(job.OutputPath);
    }

    [Fact]
    public void BuildArguments_StreamCopyAudioContainer_CopiesAudioOnly()
    {
        var job = CreateTestJob("input.mkv", "output.m4a");
        var options = new ConversionOptions { StreamCopy = true };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-c:a copy");
        args.Should().Contain("-vn");
        joined.Should().NotContain("-crf");
    }

    [Theory]
    [InlineData("vvc")]
    [InlineData("h266")]
    [InlineData("266")]
    public void CanConvert_VvcInputToCommonContainer_IsSupportedDecodeOnly(string vvcExt)
    {
        var source = new FileFormat(vvcExt, "video/vvc", FormatCategory.Video);
        var mp4 = new FileFormat("mp4", "video/mp4", FormatCategory.Video);

        _converter.CanConvert(source, mp4).Should().BeTrue("VVC is decode-only but transcodable to MP4");

        // Decode-only: VVC is not offered as an output container.
        var anySource = new FileFormat("mp4", "video/mp4", FormatCategory.Video);
        var vvcTarget = new FileFormat(vvcExt, "video/vvc", FormatCategory.Video);
        _converter.CanConvert(anySource, vvcTarget).Should().BeFalse("VVC encode is intentionally unsupported");
    }

    [Fact]
    public void BuildArguments_NoTrackSelection_EmitsNoExplicitMap()
    {
        var job = CreateTestJob("input.mkv", "output.mp4");
        var options = new ConversionOptions();

        var args = _converter.BuildArguments(job, options);

        args.Should().NotContain("-map"); // default ffmpeg stream selection
    }

    [Fact]
    public void BuildArguments_SelectedAudioTrack_MapsOnlyThatAudioStream()
    {
        var job = CreateTestJob("input.mkv", "output.mp4");
        var options = new ConversionOptions { AudioTrackSelection = [1] };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-map 0:v?");
        joined.Should().Contain("-map 0:a:1?");
        joined.Should().Contain("-map 0:s?");   // subtitles default to keep-all
        joined.Should().NotContain("0:a:0?");
    }

    [Fact]
    public void BuildArguments_EmptyAudioSelection_DropsAllAudio()
    {
        var job = CreateTestJob("input.mkv", "output.mp4");
        var options = new ConversionOptions { AudioTrackSelection = [] };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-map 0:v?");
        joined.Should().NotContain("0:a"); // no audio mapped
    }

    [Fact]
    public void BuildArguments_SubtitleSelection_MapsListedSubtitleStreams()
    {
        var job = CreateTestJob("input.mkv", "output.mkv");
        var options = new ConversionOptions { SubtitleTrackSelection = [0, 2] };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-map 0:s:0?");
        joined.Should().Contain("-map 0:s:2?");
        joined.Should().Contain("-map 0:a?"); // audio default keep-all
    }

    [Fact]
    public void BuildArguments_StreamCopyWithSelection_UsesExplicitMapsNotMapAll()
    {
        var job = CreateTestJob("input.mkv", "output.mp4");
        var options = new ConversionOptions { StreamCopy = true, AudioTrackSelection = [0] };

        var args = _converter.BuildArguments(job, options);
        var joined = string.Join(" ", args);

        joined.Should().Contain("-map 0:a:0?");
        joined.Should().Contain("-c copy");
        joined.Should().NotContain("-map 0 "); // not the copy-everything map
    }

    [Fact]
    public void ShouldRunNativeTwoPass_StreamCopy_IsFalse()
    {
        var job = CreateTwoPassJob();
        job.Options.StreamCopy = true;

        _converter.ShouldRunNativeTwoPass(job).Should().BeFalse();
    }

    private static ConversionJob CreateTwoPassJob()
    {
        var job = CreateTestJob("input.mp4", "output.mp4");
        job.Options.Video.TwoPass = true;
        job.Options.Video.Bitrate = 2000;
        return job;
    }

    [Fact]
    public void ShouldRunNativeTwoPass_BitrateTargetVideo_IsTrue()
    {
        _converter.ShouldRunNativeTwoPass(CreateTwoPassJob()).Should().BeTrue();
    }

    [Fact]
    public void ShouldRunNativeTwoPass_CrfModeOrNoBitrate_IsFalse()
    {
        var crfJob = CreateTwoPassJob();
        crfJob.Options.Video.Crf = 20; // CRF wins → two-pass is a no-op
        _converter.ShouldRunNativeTwoPass(crfJob).Should().BeFalse();

        var noBitrate = CreateTestJob("input.mp4", "output.mp4");
        noBitrate.Options.Video.TwoPass = true;
        _converter.ShouldRunNativeTwoPass(noBitrate).Should().BeFalse();
    }

    [Fact]
    public void ShouldRunNativeTwoPass_AudioOutputOrOverride_IsFalse()
    {
        var audio = CreateTwoPassJob();
        audio.OutputPath = "output.mp3";
        _converter.ShouldRunNativeTwoPass(audio).Should().BeFalse();

        var overridden = CreateTwoPassJob();
        overridden.Options.FfmpegArgumentOverride = ["-i", "{input}", "{output}"];
        _converter.ShouldRunNativeTwoPass(overridden).Should().BeFalse();
    }

    [Fact]
    public void BuildPassArguments_Pass1_AnalyzesToNullSinkWithoutAudio()
    {
        var job = CreateTwoPassJob();

        var args = _converter.BuildPassArguments(job, job.Options, 1, "PREFIX");
        var joined = string.Join(" ", args);

        joined.Should().Contain("-pass 1");
        joined.Should().Contain("-passlogfile PREFIX");
        args.Should().Contain("-an");
        args.Should().Contain("-f");
        args.Should().Contain("null");
        args.Should().NotContain("-progress");        // analysis pass emits no progress
        args.Should().NotContain(job.OutputPath);      // no real muxed output
    }

    [Fact]
    public void BuildPassArguments_Pass2_WritesRealOutputWithProgress()
    {
        var job = CreateTwoPassJob();

        var args = _converter.BuildPassArguments(job, job.Options, 2, "PREFIX");
        var joined = string.Join(" ", args);

        joined.Should().Contain("-pass 2");
        joined.Should().Contain("-passlogfile PREFIX");
        args.Should().Contain(job.OutputPath);
        args.Should().Contain("-progress");
        args.Should().NotContain("-an");
    }
}
