using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class GifMakerPage : Page
{
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<GfFileItem> _files = [];
    private readonly ObservableCollection<GfFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;

    public GifMakerPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
    }

    // ── Drop zone ────────────────────────────────────────────────────────────

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into GIF queue";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;

        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            switch (item)
            {
                case StorageFile file:
                    AddFile(file.Path);
                    break;
                case StorageFolder folder:
                    AddFolder(folder.Path);
                    break;
            }
        }
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (e.Pointer.PointerDeviceType == Microsoft.UI.Input.PointerDeviceType.Mouse &&
            !e.GetCurrentPoint(null).Properties.IsLeftButtonPressed)
            return;
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    // ── Browse ───────────────────────────────────────────────────────────────

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in VideoExtensions)
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => VideoExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(200))
        {
            if (AddFile(file, updateUi: false)) added++;
        }
        StatusText.Text = added == 0
            ? "No supported videos found in that folder."
            : $"Added {added} files from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;

        var info = new FileInfo(path);
        if (!info.Exists) return false;
        if (!VideoExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase)) return false;

        _files.Add(new GfFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PlanSummary = BuildPlanSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        if (sender is Button button && button.Tag is GfFileItem item)
        {
            _files.Remove(item);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _files.Count == 0) return;

        if (!await PageDialogService.ConfirmClearAsync(
                this, "Clear queue?",
                $"Remove {_files.Count} queued file(s)? Finished GIFs stay available."))
            return;

        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (RunButton is null) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    private void Settings_Text_Changed(object sender, TextChangedEventArgs e)
    {
        if (RunButton is null) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    // ── Run ──────────────────────────────────────────────────────────────────

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;

        var width = SelectedInt(WidthCombo, 480);
        var fps   = SelectedInt(FpsCombo, 15);
        var loop  = SelectedInt(LoopCombo, 0);
        var startSec    = TryParseSeconds(StartBox.Text, 0);
        double? duration = null;
        if (!string.IsNullOrWhiteSpace(DurationBox.Text))
        {
            var parsed = TryParseSeconds(DurationBox.Text, double.NaN);
            if (!double.IsNaN(parsed) && parsed > 0) duration = parsed;
        }

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var outputPath = BuildOutputPath(item.Path);
                var args = new List<string>
                {
                    "make",
                    "--input",  item.Path,
                    "--output", outputPath,
                    "--width",  width.ToString(CultureInfo.InvariantCulture),
                    "--fps",    fps.ToString(CultureInfo.InvariantCulture),
                    "--loop",   loop.ToString(CultureInfo.InvariantCulture),
                    "--start",  startSec.ToString("F3", CultureInfo.InvariantCulture),
                };
                if (duration is double d)
                    args.AddRange(["--duration", d.ToString("F3", CultureInfo.InvariantCulture)]);

                item.Progress = 0;
                item.StatusText = "Rendering";
                StatusText.Text = $"Rendering {item.FileName}... ({completed + failed + 1}/{jobs.Count})";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage)
                        ? $"{p.Percent:F0}%"
                        : $"{p.Percent:F0}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    result = await _runner.RunAsync("gifstudio", args, progress, log, _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
                }

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

                AddFinishedItem(item, result, outputPath);

                if (result.ErrorCode == "cancelled") break;
            }

            StatusText.Text = _cts.IsCancellationRequested
                ? $"Cancelled — {completed} rendered, {failed} failed."
                : $"Done — {completed} rendered, {failed} failed.";

            if (_finished.Count > 0)
                QueuePivot.SelectedIndex = 1;
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            UpdateUi(updateStatus: false);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            CancelButton.IsEnabled = false;
            StatusText.Text = "Cancelling...";
        }
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private void AddFinishedItem(GfFileItem item, SidecarResult result, string outputPath)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush   = (Brush)Application.Current.Resources["AccentRedBrush"];

        string details;
        if (result.Success)
        {
            var size = result.SizeBytes ?? (File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0);
            details = $"{item.PlanSummary} — {(size > 0 ? FormatSize(size) : "saved")}";
        }
        else
        {
            details = result.ErrorMessage ?? "GIF render failed";
        }

        _finished.Insert(0, new GfFinishedItem
        {
            FileName    = result.Success ? Path.GetFileName(outputPath) : item.FileName,
            Details     = details,
            OutputPath  = result.OutputPath ?? outputPath,
            Success     = result.Success,
            Glyph       = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles    = _files.Count > 0;
        var hasFinished = _finished.Count > 0;

        EmptyState.Visibility         = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility           = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility       = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        RunButton.IsEnabled    = hasFiles && _cts is null;
        ClearButton.IsEnabled  = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;

        QueueSummaryText.Text = $"{_files.Count} queued / {_finished.Count} finished";
        CurrentSetupText.Text = BuildPlanSummary();

        if (updateStatus && _cts is null)
            UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        StatusText.Text = _files.Count == 0
            ? "Drop video files to start a GIF render queue."
            : $"Ready to render {_files.Count} GIF(s). {BuildPlanSummary()}";
    }

    private string BuildPlanSummary()
    {
        if (WidthCombo is null) return "";
        var width = SelectedInt(WidthCombo, 480);
        var fps   = SelectedInt(FpsCombo, 15);
        var loop  = SelectedInt(LoopCombo, 0);
        var start = string.IsNullOrWhiteSpace(StartBox?.Text) ? null : StartBox.Text.Trim();
        var dur   = string.IsNullOrWhiteSpace(DurationBox?.Text) ? null : DurationBox.Text.Trim();

        var loopText = loop switch
        {
            0  => "loop ∞",
            -1 => "play once",
            _  => $"loop {loop}×",
        };

        var trim = (start, dur) switch
        {
            (null, null) => "full",
            (string s, null) => $"from {s}s",
            (null, string d) => $"{d}s clip",
            (string s, string d) => $"{s}s + {d}s",
        };

        return $"{width}px @ {fps}fps · {loopText} · {trim}";
    }

    private string BuildOutputPath(string inputPath)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        return EnsureUniquePath(Path.Combine(dir, $"{name}.gif"));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path)) return path;
        var directory = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(directory, $"{name} ({i}){ext}");
            if (!File.Exists(candidate)) return candidate;
        }
        return Path.Combine(directory, $"{name}-{Guid.NewGuid():N}{ext}");
    }

    private static int SelectedInt(ComboBox combo, int fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
            return v;
        return fallback;
    }

    private static double TryParseSeconds(string? text, double fallback)
    {
        if (string.IsNullOrWhiteSpace(text)) return fallback;
        return double.TryParse(text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
            ? v : fallback;
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", folder) { UseShellExecute = true });
        }
        catch { /* convenience only */ }
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576     => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024         => $"{bytes / 1_024.0:F1} KB",
        _                => $"{bytes} B",
    };
}

public sealed class GfFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";

    public double Progress
    {
        get => _progress;
        set => Set(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => Set(ref _statusText, value);
    }

    public string PlanSummary
    {
        get => _planSummary;
        set => Set(ref _planSummary, value);
    }

    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class GfFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
}
