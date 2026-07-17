using System.Text.Json;
using FluentAssertions;
using UniversalConverterX.Core.ViewModels;

namespace UniversalConverterX.Core.Tests.ViewModels;

public sealed class WorkflowViewModelTests
{
    [Fact]
    public void VideoSummary_TranscriptBuildsInstantPathWithoutWhisperOrReel()
    {
        var model = new VideoSummaryWorkflowViewModel();
        model.TryLoadSource(@"C:\media\captions.srt").Should().BeTrue();

        var request = model.BuildInvocation(
            @"C:\out\summary.md", "detailed", "markdown", "extractive", "large-v3",
            includeChapters: false, exportTranscript: true, createHighlightReel: true);

        model.IsTranscript.Should().BeTrue();
        model.IsVideo.Should().BeFalse();
        request.Invocation.Arguments.Should().ContainInOrder(
            "summarize", "--output", @"C:\out\summary.md", "--transcript", @"C:\media\captions.srt");
        request.Invocation.Arguments.Should().NotContain("--whisper-model");
        request.Invocation.Arguments.Should().Contain("--no-chapters");
        request.HighlightReelOutput.Should().BeNull();
        request.TranscriptOutput.Should().Be(@"C:\out\summary.transcript.txt");
    }

    [Fact]
    public void VideoSummary_VideoIncludesWhisperAndHighlightOutputs()
    {
        var model = new VideoSummaryWorkflowViewModel();
        model.TryLoadSource(@"C:\media\clip.mp4").Should().BeTrue();

        var request = model.BuildInvocation(
            @"C:\out\summary.txt", "standard", "text", "extractive", "small",
            includeChapters: true, exportTranscript: false, createHighlightReel: true);

        request.Invocation.Arguments.Should().ContainInOrder("--whisper-model", "small");
        request.Invocation.Arguments.Should().ContainInOrder(
            "--highlight-reel", @"C:\out\summary.highlights.mp4");
        model.IsBusy = true;
        model.CanSummarize.Should().BeFalse();
    }

    [Theory]
    [InlineData("cancelled", null, "Summarization cancelled.")]
    [InlineData("transcription_failed", "details", "Could not transcribe")]
    [InlineData("other", "boom", "Summarization failed: boom")]
    public void VideoSummary_MapsSidecarErrors(string code, string? message, string expected)
    {
        VideoSummaryWorkflowViewModel.MapError(code, message).Should().Contain(expected);
    }

    [Fact]
    public void Colorize_TracksReadinessAndBuildsDefaultVideoInvocation()
    {
        var model = new ColorizeWorkflowViewModel();
        model.TryLoadSource(@"C:\media\mono.mov").Should().BeTrue();
        model.CanColorize.Should().BeFalse();
        model.ModelReady = true;

        var request = model.BuildInvocation();

        model.CanColorize.Should().BeTrue();
        request.Engine.Should().Be("colorize");
        request.OutputPath.Should().Be(@"C:\media\mono_color.mp4");
        request.Arguments.Should().Equal(
            "video", "--input", @"C:\media\mono.mov", "--output", @"C:\media\mono_color.mp4");
    }

    [Fact]
    public void Colorize_RejectsUnsupportedInputAndRespectsExplicitOutput()
    {
        var model = new ColorizeWorkflowViewModel { ModelReady = true };
        model.TryLoadSource(@"C:\media\notes.txt").Should().BeFalse();
        model.TryLoadSource(@"C:\media\photo.png").Should().BeTrue();
        model.OutputPath = @"D:\exports\photo.png";

        model.BuildInvocation().OutputPath.Should().Be(@"D:\exports\photo.png");
        model.IsVideo.Should().BeFalse();
    }

    [Fact]
    public void AutoHighlight_BuildsInvariantAnalysisAndSelectedRenderPayload()
    {
        var model = new AutoHighlightWorkflowViewModel();
        model.LoadVideo(@"C:\media\source.mp4");
        model.BuildAnalyzeArguments(27.5, 8.25, 12, 3.5).Should().ContainInOrder(
            "--threshold", "27.5", "--clip-length", "8.25", "--top-n", "12", "--min-gap", "3.5");
        model.Highlights.Add(new AutoHighlightCandidateViewModel
        {
            Rank = 1, StartSeconds = 2.5, EndSeconds = 8, StartFrame = 75, EndFrame = 240,
            Score = 91.2, Reason = "motion",
        });
        model.Highlights.Add(new AutoHighlightCandidateViewModel { Rank = 2, IsSelected = false });

        var request = model.BuildRenderInvocation(HighlightExportKind.Edl, @"C:\out\highlights.edl");

        request.Arguments.Should().ContainInOrder("render", "--input", @"C:\media\source.mp4", "--ranges-json");
        request.Arguments.Should().ContainInOrder("--output-edl", @"C:\out\highlights.edl");
        request.Arguments.Single(item => item.StartsWith("[", StringComparison.Ordinal))
            .Should().Contain("\"rank\":1").And.NotContain("\"rank\":2");
    }

    [Fact]
    public void AutoHighlight_ParsesProtocolDefaultsAndMapsResults()
    {
        using var document = JsonDocument.Parse(
            """{"rank":3,"start_seconds":1.25,"end_seconds":4.5,"score":77.1,"reason":"scene"}""");
        var model = new AutoHighlightWorkflowViewModel();

        var row = model.ParseHighlight(document.RootElement);

        row.RankLabel.Should().Be("#03");
        row.RangeLabel.Should().Be("00:00:01.250 - 00:00:04.500");
        row.Reason.Should().Be("scene");
        AutoHighlightWorkflowViewModel.MapAnalysisResult(true, null, null, 3)
            .Should().StartWith("Found 3 highlight");
    }

    [Fact]
    public void BackgroundRemoval_BuildsAllSelectedOptionsAndIgnoresMissingImage()
    {
        var model = new BackgroundRemovalWorkflowViewModel
        {
            Model = "sam2", Format = "mov", Quality = 150, Edge = 4,
            InvertMask = true, KeepAudio = false, BackgroundColor = " #112233 ",
            BackgroundImagePath = @"Z:\missing\background.png",
        };

        var request = model.BuildInvocation("input.mp4", "output.mov");

        request.Arguments.Should().ContainInOrder(
            "--model", "sam2", "--format", "mov", "--quality", "100", "--edge", "4");
        request.Arguments.Should().Contain("--invert").And.Contain("--no-audio");
        request.Arguments.Should().ContainInOrder("--bg-color", "#112233");
        request.Arguments.Should().NotContain("--bg-image");
    }

    [Fact]
    public void Compressor_StandardUsesSelectedPresetAndHardwarePath()
    {
        var model = new CompressorWorkflowViewModel
        {
            Mode = CompressionWorkflowMode.Standard,
            Preset = "archive-av1",
            HardwareAcceleration = "cuda",
        };

        var request = model.BuildInvocation("input.mkv", "output.mp4");

        request.Engine.Should().Be("videocrush");
        request.Arguments.Should().ContainInOrder("--preset", "archive-av1", "--hwaccel", "cuda");
    }

    [Fact]
    public void Compressor_CustomTargetAppliesSafetyHeadroomAndSoftwareEncoding()
    {
        var model = new CompressorWorkflowViewModel
        {
            Mode = CompressionWorkflowMode.TargetSize,
            TargetPreset = "custom",
            TargetMegabytes = 20,
        };

        var request = model.BuildInvocation("input.mkv", "output.mp4");

        request.Arguments.Should().ContainInOrder("--target-mb", "19", "--codec", "libx264");
        request.Arguments.Should().ContainInOrder("--hwaccel", "none");
    }

    [Fact]
    public void Compressor_D3D12CanRequestGuardedDeinterlacing()
    {
        var model = new CompressorWorkflowViewModel
        {
            Mode = CompressionWorkflowMode.Standard,
            Preset = "web-1080p",
            HardwareAcceleration = "d3d12",
            D3D12Deinterlace = true,
        };

        var request = model.BuildInvocation("input.mkv", "output.mp4");

        request.Arguments.Should().ContainInOrder(
            "--preset", "web-1080p", "--hwaccel", "d3d12", "--d3d12-deinterlace");
    }

    [Theory]
    [InlineData("libx264", "slow")]
    [InlineData("libx265", "medium")]
    [InlineData("libsvtav1", "6")]
    public void Compressor_VmafBuildsEncoderSpecificSearch(string encoder, string preset)
    {
        var model = new CompressorWorkflowViewModel
        {
            Mode = CompressionWorkflowMode.Vmaf,
            VmafEncoder = encoder,
            VmafTarget = 93.5,
        };

        var request = model.BuildInvocation("input.mkv", "output.mkv");

        request.Engine.Should().Be("ab-av1");
        request.Arguments.Should().ContainInOrder(
            "--encoder", encoder, "--target-vmaf", "93.5", "--preset", preset, "--verify-vmaf");
    }
}
