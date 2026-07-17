using CommunityToolkit.Mvvm.ComponentModel;

namespace UniversalConverterX.Core.ViewModels;

public sealed record VideoSummaryInvocation(
    WorkflowInvocation Invocation,
    string? TranscriptOutput,
    string? HighlightReelOutput);

public sealed class VideoSummaryWorkflowViewModel : ObservableObject
{
    private static readonly HashSet<string> TranscriptExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".srt", ".vtt", ".json", ".txt" };
    private static readonly HashSet<string> VideoExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".ts" };
    private static readonly HashSet<string> AudioExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac" };

    private string? _sourcePath;
    private bool _isBusy;

    public string? SourcePath
    {
        get => _sourcePath;
        private set
        {
            if (SetProperty(ref _sourcePath, value))
                OnPropertyChanged(nameof(CanSummarize));
        }
    }

    public bool IsTranscript { get; private set; }
    public bool IsVideo { get; private set; }
    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            if (SetProperty(ref _isBusy, value))
                OnPropertyChanged(nameof(CanSummarize));
        }
    }

    public bool CanSummarize => !IsBusy && SourcePath is not null;

    public bool TryLoadSource(string path)
    {
        var extension = Path.GetExtension(path);
        if (!TranscriptExtensions.Contains(extension)
            && !VideoExtensions.Contains(extension)
            && !AudioExtensions.Contains(extension))
            return false;

        SourcePath = path;
        IsTranscript = TranscriptExtensions.Contains(extension);
        IsVideo = VideoExtensions.Contains(extension);
        OnPropertyChanged(nameof(IsTranscript));
        OnPropertyChanged(nameof(IsVideo));
        OnPropertyChanged(nameof(SourceStatus));
        return true;
    }

    public string SourceStatus => IsTranscript
        ? "Transcript loaded — summarizes instantly, no transcription needed."
        : IsVideo
            ? "Video loaded — Whisper transcribes the audio first, then summarizes."
            : "Audio loaded — Whisper transcribes it first, then summarizes.";

    public VideoSummaryInvocation BuildInvocation(
        string output,
        string summaryLength,
        string summaryFormat,
        string engine,
        string whisperModel,
        bool includeChapters,
        bool exportTranscript,
        bool createHighlightReel)
    {
        if (SourcePath is null)
            throw new InvalidOperationException("A supported source must be loaded first.");

        var arguments = new List<string>
        {
            "summarize", "--output", output,
            IsTranscript ? "--transcript" : "--input", SourcePath,
            "--summary-length", summaryLength,
            "--summary-format", summaryFormat,
            "--engine", engine,
        };
        if (!IsTranscript)
            arguments.AddRange(["--whisper-model", whisperModel]);
        if (!includeChapters)
            arguments.Add("--no-chapters");

        string? transcriptOutput = null;
        if (exportTranscript)
        {
            transcriptOutput = Path.ChangeExtension(output, ".transcript.txt");
            arguments.AddRange(["--export-transcript", transcriptOutput]);
        }

        string? reelOutput = null;
        if (IsVideo && createHighlightReel)
        {
            reelOutput = Path.ChangeExtension(output, ".highlights.mp4");
            arguments.AddRange(["--highlight-reel", reelOutput]);
        }

        return new VideoSummaryInvocation(
            new WorkflowInvocation("videosummary", arguments, output),
            transcriptOutput,
            reelOutput);
    }

    public static string FormatExtension(string format) =>
        format.Equals("markdown", StringComparison.OrdinalIgnoreCase) ? "md" : "txt";

    public static string MapError(string? errorCode, string? errorMessage) => errorCode switch
    {
        "cancelled" => "Summarization cancelled.",
        "sidecar_not_found" => "Video Summarizer engine is not built. Run tools/videosummary/build.ps1.",
        "transcription_failed" => "Could not transcribe the media. Build the whisper-stt sidecar, or drop an existing transcript (.srt/.vtt).",
        _ => $"Summarization failed: {errorMessage ?? errorCode}",
    };
}
