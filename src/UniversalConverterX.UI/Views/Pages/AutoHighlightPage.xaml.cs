using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class AutoHighlightRow
{
    public int Rank { get; init; }
    public double StartSeconds { get; init; }
    public double EndSeconds { get; init; }
    public int StartFrame { get; init; }
    public int EndFrame { get; init; }
    public double Score { get; init; }
    public string Reason { get; init; } = "Selected highlight";
    public bool IsSelected { get; set; } = true;

    public string RankLabel => $"#{Rank:D2}";
    public string RangeLabel => $"{FormatTime(StartSeconds)} - {FormatTime(EndSeconds)}";
    public string ScoreLabel => $"{Score:F1} pts";

    private static string FormatTime(double seconds) =>
        TimeSpan.FromSeconds(Math.Max(0, seconds)).ToString(@"hh\:mm\:ss\.fff", CultureInfo.InvariantCulture);
}

public sealed partial class AutoHighlightPage : Page
{
    private enum ExportKind
    {
        Reel,
        Edl,
        Otio,
    }

    private static readonly string[] VideoExtensions =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<AutoHighlightRow> _highlights = [];
    private CancellationTokenSource? _activeRun;
    private string? _currentPath;
    private bool _isBusy;

    public AutoHighlightPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        HighlightsList.ItemsSource = _highlights;
    }

    private async void OpenVideo_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var extension in VideoExtensions)
            picker.FileTypeFilter.Add(extension);

        InitializePicker(picker);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
            return;

        _currentPath = file.Path;
        _highlights.Clear();
        AnalysisProgress.Value = 0;
        StatusText.Text = $"Loaded: {Path.GetFileName(_currentPath)}";
        UpdateUi();
    }

    private async void Analyze_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null || _isBusy)
            return;

        _highlights.Clear();
        AnalysisProgress.Value = 0;
        StatusText.Text = "Analyzing scene changes and motion energy...";
        SetBusy(true);

        var args = new List<string>
        {
            "highlights",
            "--input", _currentPath,
            "--threshold", ThresholdBox.Value.ToString("0.##", CultureInfo.InvariantCulture),
            "--min-scene-len", "15",
            "--clip-length", ClipLengthBox.Value.ToString("0.##", CultureInfo.InvariantCulture),
            "--top-n", ((int)CandidateCountBox.Value).ToString(CultureInfo.InvariantCulture),
            "--min-gap", MinimumGapBox.Value.ToString("0.##", CultureInfo.InvariantCulture),
        };
        var progress = new Progress<SidecarProgress>(update =>
            DispatcherQueue.TryEnqueue(() =>
            {
                AnalysisProgress.Value = update.Percent;
                if (!string.IsNullOrWhiteSpace(update.Stage))
                    StatusText.Text = update.Stage;
            }));
        var log = new Progress<SidecarLog>(_ => { });
        _activeRun = new CancellationTokenSource(TimeSpan.FromHours(2));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                "scenedetect", args, progress, log, _activeRun.Token,
                onRawEvent: (eventName, root) =>
                {
                    if (eventName != "highlight")
                        return;
                    var row = new AutoHighlightRow
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
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        _highlights.Add(row);
                        UpdateUi();
                    });
                });
        }
        finally
        {
            _activeRun?.Dispose();
            _activeRun = null;
            SetBusy(false);
        }

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "Auto Highlight is not installed. Build the scenedetect sidecar from Settings or with tools/scenedetect/build.ps1.";
        }
        else if (result.ErrorCode == "cancelled")
        {
            StatusText.Text = "Analysis cancelled.";
        }
        else
        {
            StatusText.Text = result.Success
                ? $"Found {_highlights.Count} highlight candidate(s). Uncheck any clips you do not want to export."
                : $"Analysis failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        UpdateUi();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Cancelling...";
        _activeRun?.Cancel();
    }

    private void HighlightSelection_Click(object sender, RoutedEventArgs e) => UpdateExportButtons();

    private async void ExportReel_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(ExportKind.Reel);

    private async void ExportEdl_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(ExportKind.Edl);

    private async void ExportOtio_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(ExportKind.Otio);

    private async Task ExportAsync(ExportKind kind)
    {
        if (_currentPath is null || _isBusy)
            return;
        var selected = _highlights.Where(item => item.IsSelected).ToList();
        if (selected.Count == 0)
            return;

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) + "_highlights",
        };
        var outputOption = kind switch
        {
            ExportKind.Reel => "--output-reel",
            ExportKind.Edl => "--output-edl",
            _ => "--output-otio",
        };
        switch (kind)
        {
            case ExportKind.Reel:
                picker.FileTypeChoices.Add("MP4 video", [".mp4"]);
                break;
            case ExportKind.Edl:
                picker.FileTypeChoices.Add("CMX 3600 EDL", [".edl"]);
                break;
            case ExportKind.Otio:
                picker.FileTypeChoices.Add("OpenTimelineIO", [".otio"]);
                break;
        }

        InitializePicker(picker);
        var file = await picker.PickSaveFileAsync();
        if (file is null)
            return;

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
        var args = new List<string>
        {
            "render",
            "--input", _currentPath,
            "--ranges-json", JsonSerializer.Serialize(ranges),
            outputOption, file.Path,
        };

        SetBusy(true);
        AnalysisProgress.Value = 0;
        StatusText.Text = kind == ExportKind.Reel ? "Rendering highlight reel..." : "Exporting timeline...";
        _activeRun = new CancellationTokenSource(TimeSpan.FromHours(2));
        var progress = new Progress<SidecarProgress>(update =>
            DispatcherQueue.TryEnqueue(() => AnalysisProgress.Value = update.Percent));
        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("scenedetect", args, progress, null, _activeRun.Token);
        }
        finally
        {
            _activeRun?.Dispose();
            _activeRun = null;
            SetBusy(false);
        }

        StatusText.Text = result.Success
            ? $"Exported {selected.Count} highlight(s) to {Path.GetFileName(file.Path)}."
            : $"Export failed: {result.ErrorMessage ?? result.ErrorCode}";
    }

    private void SetBusy(bool busy)
    {
        _isBusy = busy;
        OpenVideoButton.IsEnabled = !busy;
        AnalyzeButton.IsEnabled = !busy && _currentPath is not null;
        CandidateCountBox.IsEnabled = !busy;
        ClipLengthBox.IsEnabled = !busy;
        ThresholdBox.IsEnabled = !busy;
        MinimumGapBox.IsEnabled = !busy;
        CancelButton.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        UpdateExportButtons();
    }

    private void UpdateUi()
    {
        EmptyState.Visibility = _highlights.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        HighlightsScroll.Visibility = _highlights.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        AnalyzeButton.IsEnabled = !_isBusy && _currentPath is not null;
        UpdateExportButtons();
    }

    private void UpdateExportButtons()
    {
        var enabled = !_isBusy && _highlights.Any(item => item.IsSelected);
        ExportReelButton.IsEnabled = enabled;
        ExportEdlButton.IsEnabled = enabled;
        ExportOtioButton.IsEnabled = enabled;
    }

    private static void InitializePicker(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }
}
