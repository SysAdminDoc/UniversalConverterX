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
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AudioCompressorPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
        ".wma", ".alac", ".ape", ".wv", ".aif", ".aiff",
    ];

    // Video containers we accept too: the sidecar copies the video stream and
    // only re-encodes audio, so a podcast video gets DRC without a re-encode of
    // the picture.
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
    ];

    /// <summary>Same cap CompressorPage uses; long encodes can flood the log.</summary>
    private const int ProgressLogMaxChars = 64_000;
    private const int FolderAddCap = 500;

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<AudioCompressionFileItem> _files = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public AudioCompressorPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        UpdatePresetSummary();
        UpdateUi();
    }

    private bool IsCustomPreset =>
        (PresetCombo?.SelectedItem as ComboBoxItem)?.Tag as string == "__custom__";

    private string SelectedPresetTag()
    {
        if (PresetCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "medium";
    }

    private string SelectedEncodeTag()
    {
        if (EncodeCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return string.Empty;
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into compression queue");
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null)
            return;
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
        if (_files.Count == 0)
            BrowseFiles();
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
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
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
            0 => AppLocalizer.Get("No supported audio files were added from that folder."),
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

        _files.Add(new AudioCompressionFileItem
        {
            Path = path,
            FileName = info.Name,
            Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
            SourceSizeBytes = size,
            SourceSummary = $"{FormatSize(size)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PresetSummary = SelectedPresetLabel(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is AudioCompressionFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0) return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear compression queue?",
                $"Remove {_files.Count} queued audio file(s)?"))
        {
            return;
        }

        _files.Clear();
        UpdateUi();
    }

    private void Preset_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CustomCard is null) return;
        CustomCard.Visibility = IsCustomPreset ? Visibility.Visible : Visibility.Collapsed;
        UpdatePresetSummary();
        foreach (var file in _files) file.PresetSummary = SelectedPresetLabel();
        UpdateStatusText();
    }

    private void Encode_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null) return;
        UpdateStatusText();
    }

    private void Param_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (PresetSummary is null) return;
        UpdatePresetSummary();
    }

    private async void Compress_Click(object sender, RoutedEventArgs e)
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

        var presetTag = SelectedPresetTag();
        var encode = SelectedEncodeTag();
        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        CompressButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay(IsCustomPreset
            ? $"Compressing {jobs.Count} file(s) with custom params"
            : $"Compressing {jobs.Count} file(s) with preset '{presetTag}'");

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var args = BuildArgsFor(item.Path, presetTag, encode);

                item.StatusText = "Compressing";
                item.Progress = 0;
                ProgressTitle.Text = AppLocalizer.Format($"Compressing {item.FileName}");
                ProgressStage.Text = AppLocalizer.Format($"{completed + failed + 1} of {jobs.Count}");

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F0}%";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / jobs.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = AppLocalizer.Format($"{p.Percent:F1}% - {p.Stage}");
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

                var result = await _runner.RunAsync("audio-compressor", args, progress, log, _cts.Token);
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

    private List<string> BuildArgsFor(string inputPath, string presetTag, string encode)
    {
        var outDir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var args = new List<string>();
        if (presetTag == "__custom__")
        {
            args.AddRange(new[]
            {
                "compress",
                "--input", inputPath,
                "--output-dir", outDir,
                "--threshold", ThresholdSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
                "--ratio",     RatioSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
                "--attack",    AttackSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
                "--release",   ReleaseSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
                "--makeup",    MakeupSlider.Value.ToString("F2", CultureInfo.InvariantCulture),
            });
        }
        else
        {
            args.AddRange(new[]
            {
                "preset",
                "--name", presetTag,
                "--input", inputPath,
                "--output-dir", outDir,
            });
        }
        if (!string.IsNullOrEmpty(encode))
        {
            args.Add("--encode");
            args.Add(encode);
        }
        return args;
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
        CompressButton.IsEnabled = hasFiles && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        var output = _outputDirectory ?? "same folder as each source";
        var encode = SelectedEncodeTag();
        var encodeNote = string.IsNullOrEmpty(encode) ? "preserve codec" : $"encode to {encode.ToUpperInvariant()}";
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Add audio (or video) files to start a compression queue.")
            : AppLocalizer.Format($"Ready to compress {_files.Count} file(s) using {SelectedPresetLabel()} ({encodeNote}). Output: {output}.");
    }

    private void UpdatePresetSummary()
    {
        if (PresetSummary is null) return;
        if (IsCustomPreset)
        {
            PresetSummary.Text = string.Format(
                CultureInfo.InvariantCulture,
                AppLocalizer.Get("Threshold {0:F1} dB · Ratio {1:F1}:1 · Attack {2:F1} ms · Release {3:F1} ms · Makeup {4:F1} dB"),
                ThresholdSlider?.Value ?? -20,
                RatioSlider?.Value ?? 3,
                AttackSlider?.Value ?? 10,
                ReleaseSlider?.Value ?? 200,
                MakeupSlider?.Value ?? 4);
        }
        else
        {
            // Static blurb per preset; mirrors the sidecar's PRESETS table so users
            // know what they're picking before they hit Compress.
            PresetSummary.Text = SelectedPresetTag() switch
            {
                "light"     => AppLocalizer.Get("Threshold -18 dB · Ratio 2:1 · Attack 20 ms · Release 250 ms · Makeup +2 dB"),
                "medium"    => AppLocalizer.Get("Threshold -20 dB · Ratio 3:1 · Attack 10 ms · Release 200 ms · Makeup +4 dB"),
                "heavy"     => AppLocalizer.Get("Threshold -24 dB · Ratio 6:1 · Attack 5 ms · Release 150 ms · Makeup +6 dB"),
                "podcast"   => AppLocalizer.Get("Threshold -22 dB · Ratio 4:1 · Attack 8 ms · Release 180 ms · Makeup +5 dB"),
                "broadcast" => AppLocalizer.Get("Threshold -18 dB · Ratio 8:1 · Attack 3 ms · Release 120 ms · Makeup +4 dB"),
                _ => "",
            };
        }
    }

    private string SelectedPresetLabel() => SelectedPresetTag() switch
    {
        "__custom__" => "Custom",
        var s => char.ToUpperInvariant(s[0]) + s[1..],
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
}

public sealed class AudioCompressionFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _presetSummary = "";

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

    public string PresetSummary
    {
        get => _presetSummary;
        set => SetProperty(ref _presetSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value)) return;
        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
