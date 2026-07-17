using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;

namespace UniversalConverterX.Core.ViewModels;

public enum HighlightExportKind { Reel, Edl, Otio }

public sealed class AutoHighlightCandidateViewModel : ObservableObject
{
    private bool _isSelected = true;
    public int Rank { get; init; }
    public double StartSeconds { get; init; }
    public double EndSeconds { get; init; }
    public int StartFrame { get; init; }
    public int EndFrame { get; init; }
    public double Score { get; init; }
    public string Reason { get; init; } = "Selected highlight";
    public bool IsSelected { get => _isSelected; set => SetProperty(ref _isSelected, value); }
    public string RankLabel => $"#{Rank:D2}";
    public string RangeLabel => $"{FormatTime(StartSeconds)} - {FormatTime(EndSeconds)}";
    public string ScoreLabel => $"{Score:F1} pts";

    private static string FormatTime(double seconds) =>
        TimeSpan.FromSeconds(Math.Max(0, seconds)).ToString(@"hh\:mm\:ss\.fff", CultureInfo.InvariantCulture);
}

public sealed class AutoHighlightWorkflowViewModel : ObservableObject
{
    private string? _sourcePath;
    private bool _isBusy;
    public ObservableCollection<AutoHighlightCandidateViewModel> Highlights { get; } = [];
    public string? SourcePath
    {
        get => _sourcePath;
        private set
        {
            if (SetProperty(ref _sourcePath, value))
                OnPropertyChanged(nameof(CanAnalyze));
        }
    }
    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            if (SetProperty(ref _isBusy, value))
            {
                OnPropertyChanged(nameof(CanAnalyze));
                OnPropertyChanged(nameof(CanExport));
            }
        }
    }
    public bool CanAnalyze => !IsBusy && SourcePath is not null;
    public bool CanExport => !IsBusy && Highlights.Any(item => item.IsSelected);

    public void LoadVideo(string path)
    {
        SourcePath = path;
        Highlights.Clear();
        OnPropertyChanged(nameof(CanExport));
    }

    public IReadOnlyList<string> BuildAnalyzeArguments(
        double threshold, double clipLength, int topN, double minimumGap) =>
        SourcePath is null
            ? throw new InvalidOperationException("A video must be loaded first.")
            : [
                "highlights", "--input", SourcePath,
                "--threshold", threshold.ToString("0.##", CultureInfo.InvariantCulture),
                "--min-scene-len", "15",
                "--clip-length", clipLength.ToString("0.##", CultureInfo.InvariantCulture),
                "--top-n", topN.ToString(CultureInfo.InvariantCulture),
                "--min-gap", minimumGap.ToString("0.##", CultureInfo.InvariantCulture),
            ];

    public AutoHighlightCandidateViewModel ParseHighlight(JsonElement root) => new()
    {
        Rank = root.TryGetProperty("rank", out var rank) ? rank.GetInt32() : 0,
        StartSeconds = root.TryGetProperty("start_seconds", out var start) ? start.GetDouble() : 0,
        EndSeconds = root.TryGetProperty("end_seconds", out var end) ? end.GetDouble() : 0,
        StartFrame = root.TryGetProperty("start_frame", out var startFrame) ? startFrame.GetInt32() : 0,
        EndFrame = root.TryGetProperty("end_frame", out var endFrame) ? endFrame.GetInt32() : 0,
        Score = root.TryGetProperty("score", out var score) ? score.GetDouble() : 0,
        Reason = root.TryGetProperty("reason", out var reason)
            ? reason.GetString() ?? "Selected highlight"
            : "Selected highlight",
    };

    public WorkflowInvocation BuildRenderInvocation(HighlightExportKind kind, string outputPath)
    {
        if (SourcePath is null)
            throw new InvalidOperationException("A video must be loaded first.");
        var selected = Highlights.Where(item => item.IsSelected).ToList();
        if (selected.Count == 0)
            throw new InvalidOperationException("At least one highlight must be selected.");
        var ranges = selected.Select(item => new Dictionary<string, object>
        {
            ["rank"] = item.Rank,
            ["start_seconds"] = item.StartSeconds,
            ["end_seconds"] = item.EndSeconds,
            ["start_frame"] = item.StartFrame,
            ["end_frame"] = item.EndFrame,
            ["score"] = item.Score,
            ["reason"] = item.Reason,
        });
        var option = kind switch
        {
            HighlightExportKind.Reel => "--output-reel",
            HighlightExportKind.Edl => "--output-edl",
            _ => "--output-otio",
        };
        return new WorkflowInvocation(
            "scenedetect",
            ["render", "--input", SourcePath, "--ranges-json", JsonSerializer.Serialize(ranges), option, outputPath],
            outputPath);
    }

    public void NotifySelectionChanged() => OnPropertyChanged(nameof(CanExport));

    public static string MapAnalysisResult(bool success, string? errorCode, string? errorMessage, int count) =>
        errorCode switch
        {
            "sidecar_not_found" => "Auto Highlight is not installed. Build the scenedetect sidecar from Settings or with tools/scenedetect/build.ps1.",
            "cancelled" => "Analysis cancelled.",
            _ when success => $"Found {count} highlight candidate(s). Uncheck any clips you do not want to export.",
            _ => $"Analysis failed: {errorMessage ?? errorCode}",
        };
}
