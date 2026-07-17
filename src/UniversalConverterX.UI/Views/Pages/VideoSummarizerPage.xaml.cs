using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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
    private string? _sourcePath;
    private bool _isTranscript;
    private bool _isVideo;
    private bool _busy;
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
        e.DragUIOverride.Caption = "Summarize";
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;
        var items = await e.DataView.GetStorageItemsAsync();
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
        _sourcePath = path;
        var ext = Path.GetExtension(path).ToLowerInvariant();
        _isTranscript = TranscriptExts.Contains(ext);
        _isVideo = ext is ".mp4" or ".mkv" or ".mov" or ".m4v" or ".avi" or ".webm" or ".ts";

        DropZoneLabel.Text = Path.GetFileName(path);
        StatusText.Text = _isTranscript
            ? "Transcript loaded — summarizes instantly, no transcription needed."
            : _isVideo
                ? "Video loaded — Whisper transcribes the audio first, then summarizes."
                : "Audio loaded — Whisper transcribes it first, then summarizes.";
        HighlightToggle.IsEnabled = _isVideo;
        if (!_isVideo)
            HighlightToggle.IsOn = false;
        ResultCard.Visibility = Visibility.Collapsed;
        UpdateEnabled();
    }

    private void UpdateEnabled() =>
        SummarizeButton.IsEnabled = !_busy && _sourcePath is not null;

    private static string SelectedTag(ComboBox box) =>
        (box.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "";

    // ── Summarize ────────────────────────────────────────────────────────────

    private async void Summarize_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _sourcePath is null)
            return;

        var output = Path.Combine(
            Path.GetTempPath(),
            $"ucx_summary_{Guid.NewGuid():N}.{FormatExtension(SelectedTag(FormatBox))}");

        var args = new List<string> { "summarize", "--output", output };
        args.Add(_isTranscript ? "--transcript" : "--input");
        args.Add(_sourcePath);
        args.Add("--summary-length");
        args.Add(SelectedTag(LengthBox));
        args.Add("--summary-format");
        args.Add(SelectedTag(FormatBox));
        args.Add("--engine");
        args.Add(SelectedTag(EngineBox));
        if (!_isTranscript)
        {
            args.Add("--whisper-model");
            args.Add(SelectedTag(ModelBox));
        }
        if (!ChaptersToggle.IsOn)
            args.Add("--no-chapters");

        string? transcriptOut = null;
        if (TranscriptToggle.IsOn)
        {
            transcriptOut = Path.ChangeExtension(output, ".transcript.txt");
            args.Add("--export-transcript");
            args.Add(transcriptOut);
        }

        string? reelOut = null;
        if (_isVideo && HighlightToggle.IsOn)
        {
            reelOut = Path.ChangeExtension(output, ".highlights.mp4");
            args.Add("--highlight-reel");
            args.Add(reelOut);
        }

        _busy = true;
        _cts = new CancellationTokenSource();
        SummarizeButton.IsEnabled = false;
        BrowseButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        SummaryProgress.Visibility = Visibility.Visible;
        SummaryProgress.Value = 0;
        StatusText.Text = _isTranscript ? "Summarizing transcript…" : "Transcribing and summarizing…";

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            SummaryProgress.Value = Math.Clamp(p.Percent, 0, 100);
            if (!string.IsNullOrWhiteSpace(p.Stage))
                StatusText.Text = $"{p.Percent:F0}% — {p.Stage}";
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                "videosummary", args, progress, null, _cts.Token,
                silenceTimeout: TimeSpan.FromHours(6));
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _busy = false;
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
            if (transcriptOut is not null && File.Exists(transcriptOut))
                extras.Add("transcript saved next to the summary");
            if (reelOut is not null && File.Exists(reelOut))
                extras.Add($"highlight reel: {Path.GetFileName(reelOut)}");
            StatusText.Text = extras.Count > 0
                ? "Summary ready — " + string.Join("; ", extras) + "."
                : "Summary ready.";
        }
        else
        {
            StatusText.Text = result.ErrorCode switch
            {
                "cancelled" => "Summarization cancelled.",
                "sidecar_not_found" =>
                    "Video Summarizer engine is not built. Run tools/videosummary/build.ps1.",
                "transcription_failed" =>
                    "Could not transcribe the media. Build the whisper-stt sidecar, or drop an existing transcript (.srt/.vtt).",
                _ => $"Summarization failed: {result.ErrorMessage ?? result.ErrorCode}",
            };
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Cancelling…";
        _cts?.Cancel();
    }

    private static string FormatExtension(string format) => format switch
    {
        "markdown" => "md",
        _ => "txt",
    };

    // ── Result actions ───────────────────────────────────────────────────────

    private void Copy_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(ResultBox.Text))
            return;
        var data = new DataPackage();
        data.SetText(ResultBox.Text);
        Clipboard.SetContent(data);
        StatusText.Text = "Summary copied to clipboard.";
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
            (_sourcePath is null ? "summary" : Path.GetFileNameWithoutExtension(_sourcePath) + "_summary");

        InitializeWithWindow(picker);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            await FileIO.WriteTextAsync(file, ResultBox.Text);
            StatusText.Text = $"Saved to {file.Name}.";
        }
    }

    private static void InitializeWithWindow(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }
}
