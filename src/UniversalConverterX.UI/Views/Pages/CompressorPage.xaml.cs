using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class CompressorPage : Page
{
    private readonly ISidecarRunner _runner;
    private string? _inputPath;
    private long _inputSize;
    private CancellationTokenSource? _cts;

    public CompressorPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
    }

    // ─── Drop zone ──────────────────────────────────────────────────────────

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop to load";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            if (item is StorageFile f)
            {
                LoadFile(f.Path);
                return;
            }
        }
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (_inputPath is null) BrowseFiles();
    }

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in new[] { ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v" })
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is not null) LoadFile(file.Path);
    }

    private void LoadFile(string path)
    {
        var info = new FileInfo(path);
        if (!info.Exists) return;

        _inputPath = path;
        _inputSize = info.Length;

        FileNameText.Text = info.Name;
        FileMetaText.Text = $"{FormatSize(info.Length)} • {info.Extension.TrimStart('.').ToUpperInvariant()}";
        SourceSizeText.Text = FormatSize(info.Length);
        ResultSizeText.Text = "—";
        SavingsText.Text = "";
        StatusText.Text = "";

        EmptyState.Visibility = Visibility.Collapsed;
        FileState.Visibility = Visibility.Visible;
        CompressButton.IsEnabled = true;
        ClearButton.IsEnabled = true;
    }

    private void Clear_Click(object sender, RoutedEventArgs e) => Reset();

    private void Reset()
    {
        _inputPath = null;
        _inputSize = 0;
        EmptyState.Visibility = Visibility.Visible;
        FileState.Visibility = Visibility.Collapsed;
        CompressButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        SourceSizeText.Text = "—";
        ResultSizeText.Text = "—";
        SavingsText.Text = "";
        StatusText.Text = "";
    }

    // ─── Compress ───────────────────────────────────────────────────────────

    private async void Compress_Click(object sender, RoutedEventArgs e)
    {
        if (_inputPath is null) return;

        var preset = SelectedPresetTag();
        var inputDir = Path.GetDirectoryName(_inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(_inputPath);
        var outputPath = Path.Combine(inputDir, $"{name}_compressed.mp4");

        var args = new List<string>
        {
            "--input",  _inputPath,
            "--output", outputPath,
            "--preset", preset,
        };

        ShowOverlay($"Compressing {Path.GetFileName(_inputPath)} ({preset})…");
        ProgressLog.Text = "";

        _cts = new CancellationTokenSource();
        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            ProgressBar.Value = p.Percent;
            ProgressStage.Text = $"{p.Percent:F1}% — {p.Stage}";
            ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                ? $"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}"
                : "";
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            ProgressLog.Text += $"[{l.Level}] {l.Message}\n";
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("videocrush", args, progress, log, _cts.Token);
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        if (result.Success)
        {
            ProgressTitle.Text = "Done";
            ProgressBar.Value = 100;
            ProgressStage.Text = "Complete";
            ProgressEta.Text = "";
            CancelButton.Content = "Close";

            var outSize = result.SizeBytes ?? 0;
            ResultSizeText.Text = FormatSize(outSize);
            if (_inputSize > 0 && outSize > 0)
            {
                var ratio = (1.0 - (double)outSize / _inputSize) * 100.0;
                SavingsText.Text = ratio > 0
                    ? $"Saved {ratio:F1}% ({FormatSize(_inputSize - outSize)})"
                    : $"Output is larger than source by {-ratio:F1}%";
            }
            StatusText.Text = $"Wrote {result.OutputPath}";
        }
        else
        {
            ProgressTitle.Text = "Failed";
            ProgressStage.Text = result.ErrorMessage ?? $"Sidecar exited with code {result.ExitCode}";
            ProgressEta.Text = result.ErrorCode is null ? "" : $"({result.ErrorCode})";
            CancelButton.Content = "Close";
            StatusText.Text = result.ErrorMessage ?? "Compression failed.";
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            return;
        }
        ProgressOverlay.Visibility = Visibility.Collapsed;
        CancelButton.Content = "Cancel";
    }

    private void ShowOverlay(string title)
    {
        ProgressTitle.Text = title;
        ProgressStage.Text = "Starting…";
        ProgressEta.Text = "";
        ProgressBar.Value = 0;
        CancelButton.Content = "Cancel";
        ProgressOverlay.Visibility = Visibility.Visible;
    }

    private string SelectedPresetTag()
    {
        if (PresetEmail.IsChecked == true) return "email-10mb";
        if (PresetArchive.IsChecked == true) return "archive-av1";
        return "web-1080p";
    }

    private static string FormatSize(long bytes)
    {
        string[] s = ["B", "KB", "MB", "GB", "TB"];
        int i = 0;
        double v = bytes;
        while (v >= 1024 && i < s.Length - 1) { v /= 1024; i++; }
        return $"{v:F1} {s[i]}";
    }
}
