using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class VoiceChangerPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
        ".wma", ".alac", ".ape", ".wv", ".aif", ".aiff",
    ];

    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
    ];

    private const int FolderAddCap = 500;
    private const int ProgressLogMaxChars = 64_000;

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<VoiceChangeFileItem> _files = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public VoiceChangerPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        UpdateStyleSummary();
        UpdateUi();
    }

    private string SelectedStyle()
    {
        if (StyleCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "neutral";
    }

    private string SelectedFormat()
    {
        if (FormatCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "wav";
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into voice transform queue");
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

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var ext in AudioExtensions) picker.FileTypeFilter.Add(ext);
        foreach (var ext in VideoExtensions) picker.FileTypeFilter.Add(ext);

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
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateStatusText();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateStatusText();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = AppLocalizer.Format($"Folder not found: {path}");
            return;
        }

        IEnumerable<string> entries;
        try
        {
            var allowed = AudioExtensions.Concat(VideoExtensions).ToHashSet(StringComparer.OrdinalIgnoreCase);
            entries = Directory.EnumerateFiles(path)
                .Where(f => allowed.Contains(Path.GetExtension(f)));
        }
        catch (UnauthorizedAccessException)
        {
            StatusText.Text = AppLocalizer.Get("Permission denied for that folder.");
            return;
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not read folder: {ex.Message}");
            return;
        }

        var added = 0;
        var truncated = false;
        foreach (var file in entries)
        {
            if (added >= FolderAddCap) { truncated = true; break; }
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added switch
        {
            0 => AppLocalizer.Get("No supported audio or video files were added from that folder."),
            _ when truncated => AppLocalizer.Format($"Added {added} files from {path} (capped at {FolderAddCap})."),
            _ => AppLocalizer.Format($"Added {added} files from {path}."),
        };
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => string.Equals(f.Path, path, StringComparison.OrdinalIgnoreCase)))
            return false;

        FileInfo info;
        long size;
        try
        {
            info = new FileInfo(path);
            if (!info.Exists) return false;
            size = info.Length;
        }
        catch
        {
            return false;
        }

        var allowed = AudioExtensions.Concat(VideoExtensions);
        if (!allowed.Contains(info.Extension, StringComparer.OrdinalIgnoreCase))
            return false;

        _files.Add(new VoiceChangeFileItem
        {
            Path = path,
            FileName = info.Name,
            Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
            SourceSizeBytes = size,
            SourceSummary = $"{FormatSize(size)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            StyleSummary = SelectedStyleLabel(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is VoiceChangeFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        _files.Clear();
        UpdateUi();
    }

    private void VoiceCombo_Changed(object sender, SelectionChangedEventArgs e) => RefreshVoiceParams();

    private void VoiceSlider_Changed(object sender, RangeBaseValueChangedEventArgs e) => RefreshVoiceParams();

    private void RefreshVoiceParams()
    {
        UpdateStyleSummary();
        foreach (var file in _files)
            file.StyleSummary = SelectedStyleLabel();
        if (StatusText is null) return;
        UpdateStatusText();
    }

    private async void Transform_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                StatusText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
                return;
            }
        }

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        TransformButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay($"Transforming {jobs.Count} file(s) as {SelectedStyleLabel()}");

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var args = BuildArgsFor(item.Path);

                item.StatusText = "Transforming";
                item.Progress = 0;
                ProgressTitle.Text = AppLocalizer.Format($"Transforming {item.FileName}");
                ProgressStage.Text = AppLocalizer.Format($"{completed + failed + 1} of {jobs.Count}");

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F0}%";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / jobs.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = string.IsNullOrWhiteSpace(p.Stage)
                        ? AppLocalizer.Format($"{p.Percent:F1}%")
                        : AppLocalizer.Format($"{p.Percent:F1}% - {p.Stage}");
                    ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                        ? AppLocalizer.Format($"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}")
                        : "";
                }));
                var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
                {
                    var line = $"[{l.Level}] {l.Message}\n";
                    var combined = ProgressLog.Text + line;
                    if (combined.Length > ProgressLogMaxChars)
                    {
                        var trimmed = combined.Length - ProgressLogMaxChars;
                        var nl = combined.IndexOf('\n', trimmed);
                        combined = nl >= 0 ? combined[(nl + 1)..] : combined[trimmed..];
                    }
                    ProgressLog.Text = combined;
                }));

                var result = await _runner.RunAsync("voice-changer", args, progress, log, _cts.Token);
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

                if (result.ErrorCode == "cancelled") break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        ProgressTitle.Text = failed == 0
            ? AppLocalizer.Get("Done")
            : AppLocalizer.Get("Completed with errors");
        ProgressBar.Value = failed == 0 ? 100 : ProgressBar.Value;
        ProgressStage.Text = AppLocalizer.Format($"{completed} succeeded, {failed} failed");
        ProgressEta.Text = "";
        CancelButton.Content = AppLocalizer.Get("Close");
        UpdateUi();
    }

    private List<string> BuildArgsFor(string inputPath)
    {
        var outDir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        return
        [
            "transform",
            "--input", inputPath,
            "--output-dir", outDir,
            "--style", SelectedStyle(),
            "--pitch-semitones", PitchSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
            "--intensity", IntensitySlider.Value.ToString("F0", CultureInfo.InvariantCulture),
            "--format", SelectedFormat(),
        ];
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            return;
        }

        ProgressOverlay.Visibility = Visibility.Collapsed;
        CancelButton.Content = AppLocalizer.Get("Cancel");
    }

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var path = _outputDirectory ?? _files.FirstOrDefault()?.Path;
        OpenContainingFolder(path);
    }

    private void ShowOverlay(string title)
    {
        ProgressTitle.Text = title;
        ProgressStage.Text = AppLocalizer.Get("Starting...");
        ProgressEta.Text = "";
        ProgressBar.Value = 0;
        CancelButton.Content = AppLocalizer.Get("Cancel");
        ProgressOverlay.Visibility = Visibility.Visible;
    }

    private void UpdateUi()
    {
        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        TransformButton.IsEnabled = hasFiles && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        if (StatusText is null) return;
        var output = _outputDirectory ?? "same folder as each source";
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Add audio or video files to transform voice tone.")
            : AppLocalizer.Format($"Ready to transform {_files.Count} file(s) as {SelectedStyleLabel()} ({SelectedFormatLabel()}). Output: {output}.");
    }

    private void UpdateStyleSummary()
    {
        if (StyleSummary is null) return;
        StyleSummary.Text = SelectedStyle() switch
        {
            "neutral" => AppLocalizer.Get("Cleans rumble/noise and levels speech without a character shift."),
            "lower" => AppLocalizer.Get("Adds a deeper contour with low-mid weight and pitch-safe duration recovery."),
            "higher" => AppLocalizer.Get("Brightens speech and lifts the pitch contour while keeping timing stable."),
            "robotic" => AppLocalizer.Get("Adds modulation, short echo, and bit-depth texture for synthetic narration."),
            "whisper" => AppLocalizer.Get("Narrows bandwidth and compresses dynamics for a soft whispered voice bed."),
            _ => "",
        };
    }

    private string SelectedStyleLabel() => SelectedStyle() switch
    {
        "neutral" => "Neutral",
        "lower" => "Lower",
        "higher" => "Higher",
        "robotic" => "Robotic",
        "whisper" => "Whisper",
        var value => value,
    };

    private string SelectedFormatLabel() => SelectedFormat() switch
    {
        "wav" => "WAV",
        "mp3" => "MP3",
        "m4a" => "AAC",
        "flac" => "FLAC",
        "opus" => "Opus",
        "video" => "keep video",
        var value => value.ToUpperInvariant(),
    };

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"") { UseShellExecute = true });
        }
        catch
        {
            // Convenience action only.
        }
    }

    private static string FormatSize(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double value = bytes;
        while (value >= 1024 && i < units.Length - 1)
        {
            value /= 1024;
            i++;
        }
        return $"{value:F1} {units[i]}";
    }
}

public sealed class VoiceChangeFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _styleSummary = "";

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

    public string StyleSummary
    {
        get => _styleSummary;
        set => SetProperty(ref _styleSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value)) return;
        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
