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

public sealed partial class BackgroundRemoverPage : Page
{
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private static readonly string[] ImageExtensions =
    [
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"
    ];

    private static readonly string[] AllExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<BgRemoveFileItem> _files = [];
    private readonly ObservableCollection<BgRemoveFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public BackgroundRemoverPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        QualitySlider.ValueChanged += (_, e) =>
            QualityValueText.Text = ((int)e.NewValue).ToString();
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into background removal queue";
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
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in AllExtensions)
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
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateStatusText();
    }

    private async void BrowseBgImage_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.Thumbnail,
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
        };
        foreach (var ext in ImageExtensions)
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is not null)
            BgImagePathBox.Text = file.Path;
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateStatusText();
    }

    private void BgType_Checked(object sender, RoutedEventArgs e)
    {
        if (BgColorPanel is null) return;
        BgColorPanel.Visibility = BgSolid.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        BgImagePanel.Visibility = BgImage.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
    }

    private void ModelCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateModelSummaries();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => AllExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(500))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added == 0
            ? "No supported files were added from that folder."
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

        if (!AllExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase))
            return false;

        _files.Add(new BgRemoveFileItem
        {
            Path = path,
            FileName = info.Name,
            Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
            SourceSizeBytes = info.Length,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            ModelSummary = SelectedModelLabel(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi)
            UpdateUi();

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is BgRemoveFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0)
            return;

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

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                StatusText.Text = $"Output folder unavailable: {ex.Message}";
                return;
            }
        }

        var modelTag = SelectedModelTag();
        var formatTag = SelectedFormatTag();
        var quality = (int)QualitySlider.Value;
        var edge = (int)EdgeSlider.Value;
        var invertMask = InvertMaskToggle.IsOn;
        var keepAudio = KeepAudioToggle.IsOn;
        var bgColor = BgSolid.IsChecked == true ? BgColorBox.Text.Trim() : null;
        var bgImagePath = BgImage.IsChecked == true ? BgImagePathBox.Text.Trim() : null;

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay($"Processing {jobs.Count} file(s) with {SelectedModelLabel()}");

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested)
                    break;

                var outputPath = BuildOutputPath(item.Path, formatTag);
                var args = new List<string>
                {
                    "--input", item.Path,
                    "--output", outputPath,
                    "--model", modelTag,
                    "--format", formatTag,
                    "--quality", quality.ToString(),
                };

                if (edge > 0)
                {
                    args.Add("--edge");
                    args.Add(edge.ToString());
                }

                if (invertMask)
                    args.Add("--invert");

                if (!keepAudio)
                    args.Add("--no-audio");

                if (!string.IsNullOrWhiteSpace(bgColor))
                {
                    args.Add("--bg-color");
                    args.Add(bgColor);
                }

                if (!string.IsNullOrWhiteSpace(bgImagePath) && File.Exists(bgImagePath))
                {
                    args.Add("--bg-image");
                    args.Add(bgImagePath);
                }

                item.StatusText = "Processing";
                item.Progress = 0;
                ProgressTitle.Text = $"Processing {item.FileName}";
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

                var result = await _runner.RunAsync("alphacut", args, progress, log, _cts.Token);
                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                    item.ResultSizeBytes = result.SizeBytes ?? 0;
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

    private void AddFinishedItem(BgRemoveFileItem item, SidecarResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var details = result.Success
            ? $"{item.SourceSummary} -> {FormatSize(result.SizeBytes ?? 0)}"
            : result.ErrorMessage ?? "Background removal failed";

        _finished.Insert(0, new BgRemoveFinishedItem
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
            ? "Add video or image files to start a background removal queue."
            : $"Ready to process {_files.Count} file(s) using {SelectedModelLabel()}. Output: {output}.";
    }

    private void UpdateModelSummaries()
    {
        var label = SelectedModelLabel();
        foreach (var file in _files)
            file.ModelSummary = label;
    }

    private string SelectedModelTag()
    {
        if (ModelCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "u2net_human_seg";
    }

    private string SelectedModelLabel()
    {
        if (ModelCombo.SelectedItem is ComboBoxItem item)
            return item.Content?.ToString()?.Split('(')[0].Trim() ?? "Human Seg";
        return "Human Seg";
    }

    private string SelectedFormatTag()
    {
        if (FormatCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "mp4";
    }

    private string BuildOutputPath(string inputPath, string format)
    {
        var dir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var ext = format == "png_sequence" ? ".png" : $".{format}";
        var suffix = format == "png_sequence" ? "_nobg_%04d" : "_nobg";
        return EnsureUniquePath(Path.Combine(dir, $"{name}{suffix}{ext}"));
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
            // Convenience action only; keep state intact if Explorer fails.
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

public sealed class BgRemoveFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _modelSummary = "";
    private long _resultSizeBytes;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public long SourceSizeBytes { get; set; }

    public long ResultSizeBytes
    {
        get => _resultSizeBytes;
        set => SetProperty(ref _resultSizeBytes, value);
    }

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

    public string ModelSummary
    {
        get => _modelSummary;
        set => SetProperty(ref _modelSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class BgRemoveFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
