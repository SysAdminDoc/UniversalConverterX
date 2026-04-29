using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class EditorPage : Page
{
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<EditFileItem> _files = [];
    private readonly ObservableCollection<EditFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public EditorPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateCrfLabel(18);
        UpdateOperationSummaries();
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into editing queue";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;

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
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

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
        if (files is null)
            return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
            AddFolder(folder.Path);
    }

    private async void BrowseOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateUi();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateUi();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => VideoExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(500))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added == 0
            ? "No supported video files were added from that folder."
            : $"Added {added} videos from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path))
            return false;

        var info = new FileInfo(path);
        if (!info.Exists)
            return false;

        if (!VideoExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase))
            return false;

        _files.Add(new EditFileItem
        {
            Path = path,
            FileName = info.Name,
            Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
            SourceSizeBytes = info.Length,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            OperationSummary = BuildOperationSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi)
            UpdateUi();

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (sender is Button button && button.Tag is EditFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (_files.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear editing queue?",
                $"Remove {_files.Count} queued clip(s)? Finished exports stay available."))
        {
            return;
        }

        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateUi();

    private void TrimOption_Changed(object sender, RoutedEventArgs e)
    {
        UpdateOperationSummaries();
        UpdateUi();
    }

    private void TrimText_Changed(object sender, TextChangedEventArgs e)
    {
        UpdateOperationSummaries();
        UpdateUi();
    }

    private void CrfSlider_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        UpdateCrfLabel((int)e.NewValue);
        UpdateOperationSummaries();
        UpdateUi();
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null)
            return;

        if (!TryBuildTrimOptions(out var options))
        {
            return;
        }

        if (_outputDirectory is not null)
            Directory.CreateDirectory(_outputDirectory);

        var pending = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        ExportButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay($"Exporting {pending.Count} clips");

        try
        {
            foreach (var item in pending)
            {
                if (_cts.IsCancellationRequested)
                    break;

                var outputPath = BuildOutputPath(item.Path);
                var args = BuildArgs(item.Path, outputPath, options);

                item.Progress = 0;
                item.StatusText = "Exporting";
                ProgressTitle.Text = $"Exporting {item.FileName}";
                ProgressStage.Text = $"{completed + failed + 1} of {pending.Count}";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F1}% - {p.Stage}";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / pending.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = $"{p.Percent:F1}% - {p.Stage}";
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
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(
                        Success: false,
                        ExitCode: 130,
                        OutputPath: null,
                        SizeBytes: null,
                        ErrorCode: "cancelled",
                        ErrorMessage: "Cancelled by user");
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

                AddFinishedItem(item, result);

                if (result.ErrorCode == "cancelled")
                    break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        ProgressTitle.Text = failed == 0 ? "Done" : "Completed with errors";
        ProgressBar.Value = failed == 0 ? 100 : ProgressBar.Value;
        ProgressStage.Text = $"{completed} succeeded, {failed} failed";
        ProgressEta.Text = "";
        CancelButton.Content = "Close";
        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        StatusText.Text = $"{completed} edits exported, {failed} failed.";
        UpdateUi(updateStatus: false);
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

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var path = _outputDirectory
            ?? _finished.LastOrDefault(f => f.Success && !string.IsNullOrWhiteSpace(f.OutputPath))?.OutputPath
            ?? _files.FirstOrDefault()?.Path;
        OpenContainingFolder(path);
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private void ShowOverlay(string title)
    {
        ProgressTitle.Text = title;
        ProgressStage.Text = "Starting...";
        ProgressEta.Text = "";
        ProgressBar.Value = 0;
        CancelButton.Content = "Cancel";
        ProgressOverlay.Visibility = Visibility.Visible;
    }

    private bool TryBuildTrimOptions(out TrimOptions options)
    {
        if (!TryParseSeconds(StartBox.Text, out var startSec))
            startSec = 0;

        var endText = (EndBox.Text ?? "").Trim();
        double? endSec = null;
        if (!string.IsNullOrWhiteSpace(endText))
        {
            if (!TryParseSeconds(endText, out var parsedEnd))
            {
                StatusText.Text = "Invalid end time. Enter seconds, for example 12.5.";
                options = default;
                return false;
            }
            endSec = parsedEnd;
        }

        if (endSec is double end && end <= startSec)
        {
            StatusText.Text = "End time must be greater than start.";
            options = default;
            return false;
        }

        options = new TrimOptions(
            StartSeconds: Math.Max(0, startSec),
            EndSeconds: endSec,
            Lossless: LosslessCheck.IsChecked == true,
            Crf: (int)CrfSlider.Value);
        return true;
    }

    private List<string> BuildArgs(string inputPath, string outputPath, TrimOptions options)
    {
        var args = new List<string>
        {
            "trim",
            "--input", inputPath,
            "--output", outputPath,
            "--start", options.StartSeconds.ToString("F3", CultureInfo.InvariantCulture),
        };

        if (options.EndSeconds.HasValue)
            args.AddRange(["--end", options.EndSeconds.Value.ToString("F3", CultureInfo.InvariantCulture)]);

        if (options.Lossless)
        {
            args.Add("--lossless");
        }
        else
        {
            args.AddRange([
                "--crf", options.Crf.ToString(CultureInfo.InvariantCulture),
                "--preset", "medium",
            ]);
        }

        return args;
    }

    private void AddFinishedItem(EditFileItem item, SidecarResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var details = result.Success
            ? $"{item.OperationSummary} - {(result.SizeBytes is long sz ? FormatSize(sz) : "saved")}"
            : result.ErrorMessage ?? "Edit export failed";

        _finished.Insert(0, new EditFinishedItem
        {
            FileName = result.Success && !string.IsNullOrWhiteSpace(result.OutputPath)
                ? Path.GetFileName(result.OutputPath)
                : item.FileName,
            Details = details,
            OutputPath = result.OutputPath ?? "",
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        ExportButton.IsEnabled = hasFiles && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;

        QueueCountText.Text = $"{_files.Count} clips queued";
        OperationText.Text = BuildOperationSummary();
        OutputText.Text = $"Output: {(_outputDirectory ?? "same as source")}";

        if (updateStatus && _cts is null)
        {
            var output = _outputDirectory ?? "same folder as each source";
            StatusText.Text = hasFiles
                ? $"Ready to export {_files.Count} clips. {BuildOperationSummary()} Output: {output}."
                : "Add videos to build an edit queue.";
        }
    }

    private void UpdateOperationSummaries()
    {
        var summary = BuildOperationSummary(shortLabel: true);
        foreach (var file in _files)
            file.OperationSummary = summary;
    }

    private string BuildOperationSummary(bool shortLabel = false)
    {
        var startText = string.IsNullOrWhiteSpace(StartBox?.Text) ? "0" : StartBox.Text.Trim();
        var endText = string.IsNullOrWhiteSpace(EndBox?.Text) ? "end" : EndBox.Text.Trim();
        var mode = LosslessCheck?.IsChecked == true ? "lossless" : $"CRF {(int)(CrfSlider?.Value ?? 18)}";

        return shortLabel
            ? $"{startText}s to {endText}, {mode}"
            : $"Trim from {startText}s to {endText} ({mode})";
    }

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

    private string BuildOutputPath(string inputPath)
    {
        var dir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var ext = Path.GetExtension(inputPath);
        return EnsureUniquePath(Path.Combine(dir, $"{name}_trimmed{ext}"));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path))
            return path;

        var directory = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var extension = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(directory, $"{name} ({i}){extension}");
            if (!File.Exists(candidate))
                return candidate;
        }

        return Path.Combine(directory, $"{name}-{Guid.NewGuid():N}{extension}");
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;

        var folder = Directory.Exists(path)
            ? path
            : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return;

        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", folder)
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Convenience action only; keep edit state intact if Explorer fails.
        }
    }

    private static bool TryParseSeconds(string? text, out double seconds)
    {
        seconds = 0;
        if (string.IsNullOrWhiteSpace(text))
            return false;
        return double.TryParse(text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out seconds);
    }

    private static string FormatSize(long bytes)
    {
        string[] s = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double v = bytes;
        while (v >= 1024 && i < s.Length - 1)
        {
            v /= 1024;
            i++;
        }

        return $"{v:F1} {s[i]}";
    }

    private readonly record struct TrimOptions(double StartSeconds, double? EndSeconds, bool Lossless, int Crf);
}

public sealed class EditFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _operationSummary = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public long SourceSizeBytes { get; set; }

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => SetProperty(ref _statusText, value);
    }

    public string OperationSummary
    {
        get => _operationSummary;
        set => SetProperty(ref _operationSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class EditFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
