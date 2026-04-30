using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
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

public sealed partial class SpeechToTextPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"
    ];

    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<SttFileItem> _files = [];
    private readonly ObservableCollection<SttFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputFolder;

    public SpeechToTextPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
    }

    // -------------------------------------------------------------------------
    // Drop zone
    // -------------------------------------------------------------------------

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop audio or video into queue";
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
        if (e.Pointer.PointerDeviceType == Microsoft.UI.Input.PointerDeviceType.Mouse &&
            !e.GetCurrentPoint(null).Properties.IsLeftButtonPressed)
            return;
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    // -------------------------------------------------------------------------
    // Browse
    // -------------------------------------------------------------------------

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var ext in AudioExtensions.Concat(VideoExtensions))
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
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
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;

        _outputFolder = folder.Path;
        OutputFolderBox.Text = _outputFolder;
    }

    // -------------------------------------------------------------------------
    // File management
    // -------------------------------------------------------------------------

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;

        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => supported.Contains(Path.GetExtension(f)))
                     .Take(200))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusLabel.Text = added == 0
            ? "No supported files found in that folder."
            : $"Added {added} files from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;

        var info = new FileInfo(path);
        if (!info.Exists) return false;

        var ext = info.Extension;
        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!supported.Contains(ext)) return false;

        _files.Add(new SttFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {ext.TrimStart('.').ToUpperInvariant()}",
            SettingsSummary = BuildSettingsSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is SttFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private void ClearAll_Click(object sender, RoutedEventArgs e)
    {
        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    // -------------------------------------------------------------------------
    // Settings change
    // -------------------------------------------------------------------------

    private void Settings_Changed(object sender, object e)
    {
        if (TranscribeButton is null) return;
        var summary = BuildSettingsSummary();
        foreach (var f in _files)
            f.SettingsSummary = summary;
    }

    // -------------------------------------------------------------------------
    // Transcribe
    // -------------------------------------------------------------------------

    private async void Transcribe_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;

        var model = SelectedComboTag(ModelCombo) ?? "base";
        var language = SelectedComboTag(LanguageCombo) ?? "auto";
        var format = SelectedComboTag(FormatCombo) ?? "srt";
        var wordTs = WordTimestampsToggle.IsOn;

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        TranscribeButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var outputPath = BuildOutputPath(item.Path, format);
                var args = new List<string>
                {
                    "--input",    item.Path,
                    "--output",   outputPath,
                    "--model",    model,
                    "--language", language,
                    "--format",   format,
                };
                if (wordTs) args.Add("--word-timestamps");

                item.Progress = 0;
                item.StatusText = "Transcribing";
                StatusLabel.Text = $"Transcribing {item.FileName}... ({completed + failed + 1}/{jobs.Count})";

                var progressHandler = new Progress<SidecarProgress>(p =>
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        item.Progress = p.Percent;
                        item.StatusText = $"{p.Percent:F0}%";
                        if (!string.IsNullOrEmpty(p.Stage))
                            item.StatusText = p.Stage;
                    }));

                var logHandler = new Progress<SidecarLog>(_ => { });

                var result = await _runner.RunAsync(
                    "whisper-stt", args, progressHandler, logHandler, _cts.Token);

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                    var fi = new FileInfo(outputPath);
                    _finished.Add(new SttFinishedItem
                    {
                        FileName = item.FileName,
                        Details = $"Transcribed using {model} — {(fi.Exists ? FormatSize(fi.Length) : "?")}",
                        OutputPath = outputPath,
                        Glyph = "\uE73E",
                        AccentBrush = (SolidColorBrush)Application.Current.Resources["AccentGreenBrush"],
                        CanOpenFile = fi.Exists,
                    });
                }
                else
                {
                    failed++;
                    item.Progress = 0;
                    item.StatusText = result.ErrorMessage?.Length > 40
                        ? result.ErrorMessage[..40] + "..."
                        : result.ErrorMessage ?? "Error";
                    _finished.Add(new SttFinishedItem
                    {
                        FileName = item.FileName,
                        Details = $"Failed: {result.ErrorMessage ?? "Unknown error"}",
                        OutputPath = string.Empty,
                        Glyph = "\uE783",
                        AccentBrush = (SolidColorBrush)Application.Current.Resources["AccentRedBrush"],
                        CanOpenFile = false,
                    });
                }
            }

            var msg = _cts.IsCancellationRequested
                ? $"Cancelled — {completed} completed, {failed} failed."
                : $"Done — {completed} transcribed, {failed} failed.";
            StatusLabel.Text = msg;

            if (_finished.Count > 0)
            {
                FinishedList.Visibility = Visibility.Visible;
                FinishedEmptyState.Visibility = Visibility.Collapsed;
                QueuePivot.SelectedIndex = 1;
            }

            // Remove successful files from queue
            foreach (var item in jobs.Where(j => j.Progress >= 100).ToList())
                _files.Remove(item);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            UpdateUi();
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StatusLabel.Text = "Cancelling...";
        CancelButton.IsEnabled = false;
    }

    // -------------------------------------------------------------------------
    // Output finished items
    // -------------------------------------------------------------------------

    private void OpenFinishedFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string path && File.Exists(path))
            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string path)
        {
            var dir = File.Exists(path) ? Path.GetDirectoryName(path) : path;
            if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir))
                Process.Start(new ProcessStartInfo("explorer.exe", $"\"{dir}\"") { UseShellExecute = true });
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private string BuildOutputPath(string inputPath, string format)
    {
        var stem = Path.GetFileNameWithoutExtension(inputPath);
        var ext = $".{format}";
        var dir = string.IsNullOrEmpty(_outputFolder)
            ? Path.GetDirectoryName(inputPath) ?? Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
            : _outputFolder;
        return Path.Combine(dir, stem + "_transcript" + ext);
    }

    private string BuildSettingsSummary()
    {
        var model = SelectedComboTag(ModelCombo) ?? "base";
        var format = SelectedComboTag(FormatCombo) ?? "srt";
        return $"{model} / .{format}";
    }

    private static string? SelectedComboTag(ComboBox combo)
    {
        return (combo.SelectedItem as ComboBoxItem)?.Tag as string;
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };

    private void UpdateUi()
    {
        if (EmptyState is null) return;

        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;

        var hasFinished = _finished.Count > 0;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        TranscribeButton.IsEnabled = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;

        if (!hasFiles)
            StatusLabel.Text = "Add audio or video files to transcribe.";
    }
}

// -------------------------------------------------------------------------
// Data models
// -------------------------------------------------------------------------

internal sealed class SttFileItem : INotifyPropertyChanged
{
    public string Path { get; init; } = string.Empty;
    public string FileName { get; init; } = string.Empty;
    public string SourceSummary { get; init; } = string.Empty;

    private string _settingsSummary = string.Empty;
    public string SettingsSummary
    {
        get => _settingsSummary;
        set { _settingsSummary = value; OnPropertyChanged(); }
    }

    private double _progress;
    public double Progress
    {
        get => _progress;
        set { _progress = value; OnPropertyChanged(); }
    }

    private string _statusText = string.Empty;
    public string StatusText
    {
        get => _statusText;
        set { _statusText = value; OnPropertyChanged(); }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

internal sealed class SttFinishedItem
{
    public string FileName { get; init; } = string.Empty;
    public string Details { get; init; } = string.Empty;
    public string OutputPath { get; init; } = string.Empty;
    public string Glyph { get; init; } = "\uE73E";
    public SolidColorBrush? AccentBrush { get; init; }
    public bool CanOpenFile { get; init; }
}
