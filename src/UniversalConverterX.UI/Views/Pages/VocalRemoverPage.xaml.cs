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

public sealed partial class VocalRemoverPage : Page
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
    private readonly ObservableCollection<VrFileItem> _files = [];
    private readonly ObservableCollection<VrFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public VocalRemoverPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
    }

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

    private void Settings_Changed(object sender, object e)
    {
        if (RunButton is null) return;
        var summary = BuildSettingsSummary();
        foreach (var f in _files)
            f.SettingsSummary = summary;
        UpdateStatusText();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

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

        StatusText.Text = added == 0
            ? "No supported files found in that folder."
            : $"Added {added} files from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path))
            return false;

        var info = new FileInfo(path);
        if (!info.Exists)
            return false;

        var ext = info.Extension;
        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!supported.Contains(ext))
            return false;

        _files.Add(new VrFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {ext.TrimStart('.').ToUpperInvariant()}",
            SettingsSummary = BuildSettingsSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi)
            UpdateUi();

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is VrFileItem file)
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
                "Clear queue?",
                $"Remove {_files.Count} queued file(s)? Finished results stay available."))
        {
            return;
        }

        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null)
            return;

        var model = SelectedComboTag(ModelCombo) ?? "htdemucs_ft";
        var stems = SelectedComboTag(StemCombo) ?? "2stem";
        // 6-stem requires the htdemucs_6s model — silently override the model
        // so users don't get a confusing "no guitar/piano" output if they left
        // the default htdemucs_ft selected.
        if (stems == "6stem" && !model.Contains("6s", StringComparison.OrdinalIgnoreCase))
            model = "htdemucs_6s";
        var format = SelectedComboTag(FormatCombo) ?? "wav";
        var shifts = ShiftsToggle.IsOn ? 1 : 0;

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay($"Separating {jobs.Count} file(s) — {model}");

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested)
                    break;

                var outputDir = BuildOutputDir(item.Path);
                Directory.CreateDirectory(outputDir);

                var args = new List<string>
                {
                    "--input", item.Path,
                    "--output-dir", outputDir,
                    "--model", model,
                    "--stems", stems,
                    "--format", format,
                    "--shifts", shifts.ToString(),
                };

                item.Progress = 0;
                item.StatusText = "Separating";
                ProgressTitle.Text = $"Separating {item.FileName}";
                ProgressStage.Text = $"{completed + failed + 1} of {jobs.Count}";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F0}%";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / jobs.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = $"{p.Percent:F1}% - {p.Stage}";
                    ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                        ? $"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}"
                        : "";
                }));
                var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
                {
                    var combined = ProgressLog.Text + $"[{l.Level}] {l.Message}\n";
                    if (combined.Length > 64_000)
                    {
                        var nl = combined.IndexOf('\n', combined.Length - 64_000);
                        combined = nl >= 0 ? combined[(nl + 1)..] : combined[(combined.Length - 64_000)..];
                    }
                    ProgressLog.Text = combined;
                }));

                var result = await _runner.RunAsync("demucs", args, progress, log, _cts.Token);

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

                AddFinishedItem(item, result, outputDir);

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
        UpdateUi();
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
            ?? _finished.LastOrDefault(f => f.Success && !string.IsNullOrWhiteSpace(f.OutputDir))?.OutputDir
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

    private void AddFinishedItem(VrFileItem item, SidecarResult result, string outputDir)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];

        string details;
        if (result.Success)
        {
            var stemCount = Directory.Exists(outputDir)
                ? Directory.GetFiles(outputDir, "*", SearchOption.AllDirectories).Length
                : 0;
            details = stemCount > 0
                ? $"{item.SourceSummary} → {stemCount} stem file(s)"
                : item.SourceSummary;
        }
        else
        {
            details = result.ErrorMessage ?? "Separation failed";
        }

        _finished.Insert(0, new VrFinishedItem
        {
            FileName = item.FileName,
            Details = details,
            OutputDir = outputDir,
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi()
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        RunButton.IsEnabled = hasFiles && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        var output = _outputDirectory ?? "same folder as each source";
        StatusText.Text = _files.Count == 0
            ? "Add audio or video files to separate vocals and instrumentals."
            : $"Ready to separate {_files.Count} file(s) with {BuildSettingsSummary()}. Output: {output}.";
    }

    private string BuildSettingsSummary()
    {
        var stems = SelectedComboTag(StemCombo) switch
        {
            "vocals" => "vocals",
            "accompaniment" => "instrumental",
            "4stem" => "4-stem",
            _ => "2-stem",
        };
        var model = SelectedComboTag(ModelCombo) ?? "htdemucs_ft";
        var fmt = SelectedComboTag(FormatCombo)?.ToUpperInvariant() ?? "WAV";
        return $"{stems} / {model} / {fmt}";
    }

    private string BuildOutputDir(string inputPath)
    {
        var dir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var candidate = Path.Combine(dir, $"{name}_stems");
        // Ensure unique
        if (!Directory.Exists(candidate))
            return candidate;
        for (var i = 2; i < 1000; i++)
        {
            var alt = Path.Combine(dir, $"{name}_stems ({i})");
            if (!Directory.Exists(alt))
                return alt;
        }
        return Path.Combine(dir, $"{name}_stems_{Guid.NewGuid():N}");
    }

    private static string? SelectedComboTag(ComboBox? combo)
    {
        if (combo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return null;
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;

        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return;

        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"") { UseShellExecute = true });
        }
        catch { /* convenience only */ }
    }

    private static string FormatSize(long bytes)
    {
        string[] s = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double v = bytes;
        while (v >= 1024 && i < s.Length - 1) { v /= 1024; i++; }
        return $"{v:F1} {s[i]}";
    }
}

public sealed class VrFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _settingsSummary = "";

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

    public string SettingsSummary
    {
        get => _settingsSummary;
        set => Set(ref _settingsSummary, value);
    }

    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class VrFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputDir { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputDir);
}

