using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.Core.ViewModels;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

/// <summary>
/// Transcript-driven video summarizer (ROADMAP Item 55). Whisper transcription
/// feeds an offline extractive TextRank summarizer that produces a written
/// summary, timestamped chapters, and an optional speech-driven highlight reel.
/// Distinct from Auto Highlight, which ranks visual scene/motion energy.
/// </summary>
public sealed partial class VideoSummarizerPage : Page
{
    private static readonly string[] MediaExts =
        [".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".ts", ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"];
    private static readonly string[] TranscriptExts = [".srt", ".vtt", ".json", ".txt"];

    private readonly ISidecarRunner _runner;
    private readonly VideoSummaryWorkflowViewModel _viewModel = new();
    private CancellationTokenSource? _cts;

    public VideoSummarizerPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
    }

    // ── Input ────────────────────────────────────────────────────────────────

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Summarize");
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null)
            return;
        var file = items.OfType<StorageFile>().FirstOrDefault(f => IsSupported(f.Path));
        if (file is not null)
            LoadSource(file.Path);
    }

    private async void Browse_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in MediaExts.Concat(TranscriptExts))
            picker.FileTypeFilter.Add(ext);

        InitializeWithWindow(picker);
        var file = await picker.PickSingleFileAsync();
        if (file is not null)
            LoadSource(file.Path);
    }

    private static bool IsSupported(string path)
    {
        var ext = Path.GetExtension(path).ToLowerInvariant();
        return MediaExts.Contains(ext) || TranscriptExts.Contains(ext);
    }

    private void LoadSource(string path)
    {
        if (!_viewModel.TryLoadSource(path))
            return;

        DropZoneLabel.Text = Path.GetFileName(path);
        StatusText.Text = _viewModel.SourceStatus;
        HighlightToggle.IsEnabled = _viewModel.IsVideo;
        if (!_viewModel.IsVideo)
            HighlightToggle.IsOn = false;
        ResultCard.Visibility = Visibility.Collapsed;
        UpdateEnabled();
    }

    private void UpdateEnabled() =>
        SummarizeButton.IsEnabled = _viewModel.CanSummarize;

    private static string SelectedTag(ComboBox box) =>
        (box.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "";

    // ── Summarize ────────────────────────────────────────────────────────────

    private async void Summarize_Click(object sender, RoutedEventArgs e)
    {
        if (!_viewModel.CanSummarize)
            return;

        var output = Path.Combine(
            Path.GetTempPath(),
            $"ucx_summary_{Guid.NewGuid():N}.{VideoSummaryWorkflowViewModel.FormatExtension(SelectedTag(FormatBox))}");
        var request = _viewModel.BuildInvocation(
            output, SelectedTag(LengthBox), SelectedTag(FormatBox), SelectedTag(EngineBox),
            SelectedTag(ModelBox), ChaptersToggle.IsOn, TranscriptToggle.IsOn, HighlightToggle.IsOn);

        _viewModel.IsBusy = true;
        _cts = new CancellationTokenSource();
        SummarizeButton.IsEnabled = false;
        BrowseButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        SummaryProgress.Visibility = Visibility.Visible;
        SummaryProgress.Value = 0;
        StatusText.Text = _viewModel.IsTranscript
            ? AppLocalizer.Get("Summarizing transcript…")
            : AppLocalizer.Get("Transcribing and summarizing…");

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            SummaryProgress.Value = Math.Clamp(p.Percent, 0, 100);
            if (!string.IsNullOrWhiteSpace(p.Stage))
                StatusText.Text = AppLocalizer.Format($"{p.Percent:F0}% — {p.Stage}");
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                request.Invocation.Engine, request.Invocation.Arguments, progress, null, _cts.Token,
                silenceTimeout: TimeSpan.FromHours(6));
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _viewModel.IsBusy = false;
            _cts = null;
            CancelButton.IsEnabled = false;
            BrowseButton.IsEnabled = true;
            SummaryProgress.Visibility = Visibility.Collapsed;
            UpdateEnabled();
        }

        if (result.Success && File.Exists(output))
        {
            ResultBox.Text = await File.ReadAllTextAsync(output);
            ResultCard.Visibility = Visibility.Visible;
            var extras = new List<string>();
            if (request.TranscriptOutput is not null && File.Exists(request.TranscriptOutput))
                extras.Add("transcript saved next to the summary");
            if (request.HighlightReelOutput is not null && File.Exists(request.HighlightReelOutput))
                extras.Add($"highlight reel: {Path.GetFileName(request.HighlightReelOutput)}");
            StatusText.Text = extras.Count > 0
                ? AppLocalizer.Get("Summary ready — ") + string.Join(AppLocalizer.Get("; "), extras) + AppLocalizer.Get(".")
                : AppLocalizer.Get("Summary ready.");
        }
        else
        {
            StatusText.Text = VideoSummaryWorkflowViewModel.MapError(result.ErrorCode, result.ErrorMessage);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = AppLocalizer.Get("Cancelling…");
        _cts?.Cancel();
    }

    // ── Result actions ───────────────────────────────────────────────────────

    private void Copy_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(ResultBox.Text))
            return;
        var data = new DataPackage();
        data.SetText(ResultBox.Text);
        Clipboard.SetContent(data);
        StatusText.Text = AppLocalizer.Get("Summary copied to clipboard.");
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(ResultBox.Text))
            return;
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
        var format = SelectedTag(FormatBox);
        if (format == "markdown")
            picker.FileTypeChoices.Add("Markdown", [".md"]);
        picker.FileTypeChoices.Add("Text", [".txt"]);
        picker.SuggestedFileName =
            (_viewModel.SourcePath is null ? "summary" : Path.GetFileNameWithoutExtension(_viewModel.SourcePath) + "_summary");

        InitializeWithWindow(picker);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            await FileIO.WriteTextAsync(file, ResultBox.Text);
            StatusText.Text = AppLocalizer.Format($"Saved to {file.Name}.");
        }
    }

    private static void InitializeWithWindow(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }
}
