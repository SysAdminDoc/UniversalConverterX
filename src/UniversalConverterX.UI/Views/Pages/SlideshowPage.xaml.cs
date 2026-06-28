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

public sealed partial class SlideshowPage : Page
{
    private static readonly string[] ImageExtensions =
    [
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif",
    ];

    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
    ];

    private const int FolderAddCap = 1000;
    private const int ProgressLogMaxChars = 64_000;

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<SlideImageItem> _slides = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;
    private string? _musicPath;
    private string? _lastOutputPath;

    public SlideshowPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        SlideList.ItemsSource = _slides;
        RefreshPlanSummaries();
        UpdateUi();
    }

    private string SelectedTransition() => SelectedTag(TransitionCombo, "fade");
    private string SelectedMotion() => SelectedTag(MotionCombo, "kenburns");
    private string SelectedResolution() => SelectedTag(ResolutionCombo, "1920x1080");
    private string SelectedFormat() => SelectedTag(FormatCombo, "mp4");
    private string SelectedFit() => SelectedTag(FitCombo, "cover");

    private static string SelectedTag(ComboBox combo, string fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return fallback;
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into slideshow";
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
                    AddImage(file.Path);
                    break;
                case StorageFolder folder:
                    AddFolder(folder.Path);
                    break;
            }
        }
    }

    private void BrowseImages_Click(object sender, RoutedEventArgs e) => BrowseImages();

    private async void BrowseImages()
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

        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;

        foreach (var file in files)
            AddImage(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
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
        if (folder is null) return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateStatusText();
    }

    private void SameAsImages_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateStatusText();
    }

    private async void BrowseMusic_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var ext in AudioExtensions)
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is null) return;

        _musicPath = file.Path;
        MusicPathBox.Text = _musicPath;
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private void ClearMusic_Click(object sender, RoutedEventArgs e)
    {
        _musicPath = null;
        MusicPathBox.Text = "";
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = $"Folder not found: {path}";
            return;
        }

        IEnumerable<string> entries;
        try
        {
            entries = Directory.EnumerateFiles(path)
                .Where(f => ImageExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                .OrderBy(NaturalFileNameKey, StringComparer.OrdinalIgnoreCase);
        }
        catch (UnauthorizedAccessException)
        {
            StatusText.Text = "Permission denied for that folder.";
            return;
        }
        catch (Exception ex)
        {
            StatusText.Text = $"Could not read folder: {ex.Message}";
            return;
        }

        var added = 0;
        var truncated = false;
        foreach (var file in entries)
        {
            if (added >= FolderAddCap) { truncated = true; break; }
            if (AddImage(file, updateUi: false))
                added++;
        }

        StatusText.Text = added switch
        {
            0 => "No supported images were added from that folder.",
            _ when truncated => $"Added {added} images from {path} (capped at {FolderAddCap}).",
            _ => $"Added {added} images from {path}.",
        };
        RefreshPlanSummaries();
        UpdateUi(updateStatus: false);
    }

    private bool AddImage(string path, bool updateUi = true)
    {
        if (_slides.Any(f => string.Equals(f.Path, path, StringComparison.OrdinalIgnoreCase)))
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

        if (!ImageExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase))
            return false;

        _slides.Add(new SlideImageItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(size)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PlanSummary = BuildPlanSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveSlide_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        if (sender is Button button && button.Tag is SlideImageItem item)
        {
            _slides.Remove(item);
            UpdateUi();
        }
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        _slides.Clear();
        _lastOutputPath = null;
        UpdateUi();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (CreateButton is null) return;
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private void Settings_Text_Changed(object sender, TextChangedEventArgs e)
    {
        if (CreateButton is null) return;
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private void Settings_Number_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (CreateButton is null) return;
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private void Settings_Slider_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (CreateButton is null) return;
        RefreshPlanSummaries();
        UpdateStatusText();
    }

    private async void Create_Click(object sender, RoutedEventArgs e)
    {
        if (_slides.Count == 0 || _cts is not null) return;

        var outDir = ResolveOutputDirectory();
        try { Directory.CreateDirectory(outDir); }
        catch (Exception ex)
        {
            StatusText.Text = $"Output folder unavailable: {ex.Message}";
            return;
        }

        var jobs = _slides.ToList();
        _cts = new CancellationTokenSource();
        CreateButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        ProgressLog.Text = "";
        foreach (var slide in jobs)
        {
            slide.Progress = 0;
            slide.StatusText = "Queued";
        }
        ShowOverlay($"Creating video from {jobs.Count} image(s)");

        var args = BuildArgs(outDir, jobs);
        SidecarResult result;
        try
        {
            var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
            {
                var percent = Math.Clamp(p.Percent, 0, 100);
                ProgressBar.Value = percent;
                ProgressStage.Text = string.IsNullOrWhiteSpace(p.Stage)
                    ? $"{percent:F1}%"
                    : $"{percent:F1}% - {p.Stage}";
                ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                    ? $"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}"
                    : "";
                foreach (var slide in jobs)
                {
                    slide.Progress = percent;
                    slide.StatusText = $"{percent:F0}%";
                }
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

            result = await _runner.RunAsync("slideshow", args, progress, log, _cts.Token);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
        }

        if (result.Success)
        {
            _lastOutputPath = result.OutputPath;
            foreach (var slide in jobs)
            {
                slide.Progress = 100;
                slide.StatusText = "Done";
            }
            ProgressTitle.Text = "Slideshow created";
            ProgressBar.Value = 100;
            ProgressStage.Text = result.OutputPath is null
                ? "Video saved"
                : $"Saved {Path.GetFileName(result.OutputPath)}";
        }
        else
        {
            foreach (var slide in jobs)
                slide.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
            ProgressTitle.Text = result.ErrorCode == "cancelled" ? "Cancelled" : "Render failed";
            ProgressStage.Text = result.ErrorMessage ?? "The slideshow sidecar failed.";
        }

        ProgressEta.Text = "";
        CancelButton.Content = "Close";
        UpdateUi();
    }

    private List<string> BuildArgs(string outDir, IReadOnlyList<SlideImageItem> jobs)
    {
        var args = new List<string>
        {
            "create",
            "--output-dir", outDir,
            "--name", "slideshow",
            "--format", SelectedFormat(),
            "--duration", ReadNumber(DurationBox, 3.0).ToString("F3", CultureInfo.InvariantCulture),
            "--transition", SelectedTransition(),
            "--motion", SelectedMotion(),
            "--resolution", SelectedResolution(),
            "--fps", ((int)Math.Round(ReadNumber(FpsBox, 30))).ToString(CultureInfo.InvariantCulture),
            "--fit", SelectedFit(),
            "--music-volume", (MusicVolumeSlider.Value / 100.0).ToString("F3", CultureInfo.InvariantCulture),
        };

        var overlay = OverlayTextBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(overlay))
            args.AddRange(["--overlay-text", overlay]);

        if (!string.IsNullOrWhiteSpace(_musicPath))
            args.AddRange(["--music", _musicPath]);

        args.Add("--input");
        foreach (var slide in jobs)
            args.Add(slide.Path);

        return args;
    }

    private string ResolveOutputDirectory()
    {
        if (!string.IsNullOrWhiteSpace(_outputDirectory))
            return _outputDirectory;
        var first = _slides.FirstOrDefault()?.Path;
        return Path.GetDirectoryName(first) ?? Environment.CurrentDirectory;
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
        OpenContainingFolder(_lastOutputPath ?? _outputDirectory ?? _slides.FirstOrDefault()?.Path);
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

    private void RefreshPlanSummaries()
    {
        var summary = BuildPlanSummary();
        foreach (var slide in _slides)
            slide.PlanSummary = summary;
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasSlides = _slides.Count > 0;
        EmptyState.Visibility = hasSlides ? Visibility.Collapsed : Visibility.Visible;
        SlideList.Visibility = hasSlides ? Visibility.Visible : Visibility.Collapsed;
        CreateButton.IsEnabled = hasSlides && _cts is null;
        ClearButton.IsEnabled = hasSlides && _cts is null;
        if (updateStatus) UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        if (StatusText is null) return;
        if (_slides.Count == 0)
        {
            StatusText.Text = "Add images to create a slideshow video.";
            return;
        }

        var music = string.IsNullOrWhiteSpace(_musicPath) ? "no music" : "music";
        StatusText.Text = $"Ready to create one {SelectedFormat().ToUpperInvariant()} from {_slides.Count} image(s). {BuildPlanSummary()} - {music}.";
    }

    private string BuildPlanSummary()
    {
        if (DurationBox is null) return "";
        var seconds = ReadNumber(DurationBox, 3.0);
        var fps = (int)Math.Round(ReadNumber(FpsBox, 30));
        return $"{seconds:g}s - {TransitionLabel()} - {MotionLabel()} - {SelectedResolution()} @ {fps}fps";
    }

    private string TransitionLabel() => SelectedTransition() switch
    {
        "fade" => "fade",
        "wipe" => "wipe",
        "zoom" => "zoom",
        "cut" => "cut",
        var value => value,
    };

    private string MotionLabel() => SelectedMotion() switch
    {
        "kenburns" => "Ken Burns",
        "zoom-in" => "zoom in",
        "zoom-out" => "zoom out",
        "none" => "still",
        var value => value,
    };

    private static double ReadNumber(NumberBox box, double fallback)
    {
        return double.IsNaN(box.Value) || double.IsInfinity(box.Value)
            ? fallback
            : box.Value;
    }

    private static string NaturalFileNameKey(string path)
    {
        var name = Path.GetFileName(path);
        return RegexDigits().Replace(name, m => m.Value.PadLeft(12, '0'));
    }

    [System.Text.RegularExpressions.GeneratedRegex(@"\d+")]
    private static partial System.Text.RegularExpressions.Regex RegexDigits();

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", folder) { UseShellExecute = true });
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

public sealed class SlideImageItem : INotifyPropertyChanged
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
        set => SetProperty(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => SetProperty(ref _statusText, value);
    }

    public string PlanSummary
    {
        get => _planSummary;
        set => SetProperty(ref _planSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value)) return;
        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
