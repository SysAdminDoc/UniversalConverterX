using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class EditorPage : Page
{
    private readonly ISidecarRunner _runner;
    private string? _inputPath;
    private CancellationTokenSource? _cts;

    public EditorPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        UpdateCrfLabel(18);
    }

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
            if (item is StorageFile f) { LoadFile(f.Path); return; }
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
        FileNameText.Text = info.Name;
        FileMetaText.Text = $"{FormatSize(info.Length)} • {info.Extension.TrimStart('.').ToUpperInvariant()}";
        EmptyState.Visibility = Visibility.Collapsed;
        FileState.Visibility = Visibility.Visible;
        ExportButton.IsEnabled = true;
        ClearButton.IsEnabled = true;
        StatusText.Text = "";
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        _inputPath = null;
        EmptyState.Visibility = Visibility.Visible;
        FileState.Visibility = Visibility.Collapsed;
        ExportButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        StartBox.Text = "";
        EndBox.Text = "";
        StatusText.Text = "";
    }

    private void CrfSlider_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
        => UpdateCrfLabel((int)e.NewValue);

    private void UpdateCrfLabel(int crf)
    {
        var hint = crf switch
        {
            <= 17 => "visually lossless",
            <= 23 => "high quality",
            <= 28 => "standard",
            <= 35 => "compressed",
            _ => "very compressed",
        };
        CrfLabel.Text = $"CRF {crf} ({hint})";
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_inputPath is null) return;

        // Parse trim times
        if (!TryParseSeconds(StartBox.Text, out var startSec)) startSec = 0;
        var endText = (EndBox.Text ?? "").Trim();
        double? endSec = null;
        if (!string.IsNullOrEmpty(endText))
        {
            if (!TryParseSeconds(endText, out var v))
            {
                StatusText.Text = "Invalid end time. Enter a number of seconds (e.g. 12.5).";
                return;
            }
            endSec = v;
        }
        if (endSec is double e2 && e2 <= startSec)
        {
            StatusText.Text = "End time must be greater than start.";
            return;
        }

        var inputDir = Path.GetDirectoryName(_inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(_inputPath);
        var ext = Path.GetExtension(_inputPath);
        var outputPath = Path.Combine(inputDir, $"{name}_trimmed{ext}");

        var args = new List<string>
        {
            "trim",
            "--input", _inputPath,
            "--output", outputPath,
            "--start", startSec.ToString("F3", CultureInfo.InvariantCulture),
        };
        if (endSec.HasValue)
            args.AddRange(new[] { "--end", endSec.Value.ToString("F3", CultureInfo.InvariantCulture) });
        if (LosslessCheck.IsChecked == true)
            args.Add("--lossless");
        else
            args.AddRange(new[] { "--crf", ((int)CrfSlider.Value).ToString(CultureInfo.InvariantCulture) });

        ShowOverlay(LosslessCheck.IsChecked == true ? "Trimming (lossless)…" : "Trimming (re-encode)…");
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
            result = await _runner.RunAsync("clipforge", args, progress, log, _cts.Token);
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
            ProgressEta.Text = result.SizeBytes is long sz ? $"Output {FormatSize(sz)}" : "";
            CancelButton.Content = "Close";
            StatusText.Text = $"Wrote {result.OutputPath}";
        }
        else
        {
            ProgressTitle.Text = "Failed";
            ProgressStage.Text = result.ErrorMessage ?? $"Sidecar exited with code {result.ExitCode}";
            ProgressEta.Text = result.ErrorCode is null ? "" : $"({result.ErrorCode})";
            CancelButton.Content = "Close";
            StatusText.Text = result.ErrorMessage ?? "Trim failed.";
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false }) { _cts.Cancel(); return; }
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

    private static bool TryParseSeconds(string? text, out double seconds)
    {
        seconds = 0;
        if (string.IsNullOrWhiteSpace(text)) return false;
        return double.TryParse(text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out seconds);
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
