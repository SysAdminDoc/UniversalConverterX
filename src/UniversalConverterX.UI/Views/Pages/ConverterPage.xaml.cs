using System.Collections.ObjectModel;
using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Security;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class ConverterPage : Page
{
    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "MP4", "MKV", "MOV", "WEBM", "AVI", "WMV", "M4V", "FLV", "TS", "MTS"
    };

    private static readonly HashSet<string> AudioExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "MP3", "WAV", "FLAC", "AAC", "M4A", "OGG", "WMA"
    };

    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "PNG", "JPG", "JPEG", "WEBP", "AVIF", "GIF", "BMP", "TIFF", "HEIC"
    };

    private static readonly HashSet<string> DocumentExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        "PDF", "DOC", "DOCX", "ODT", "TXT", "RTF", "MD", "HTML", "EPUB"
    };

    /// <summary>Cap the in-session finished list so a long batch can't pile up
    /// indefinitely in memory across multiple conversions on the same page.</summary>
    private const int FinishedCap = 200;

    /// <summary>Soft limit when adding folders so a stray giant directory doesn't
    /// pin the UI thread building thousands of FileItem rows.</summary>
    private const int FolderAddCap = 500;
    private const string QueueKey = "converter";
    private const string QueuePageName = "Converter";

    private readonly IConversionOrchestrator _orchestrator;
    private readonly ConverterXOptions _appOptions;
    private readonly IBatchQueueStore _queueStore;
    private readonly IAppJobCoordinator _jobCoordinator;
    private readonly IHistoryService _history;
    private readonly IPostQueueActionService _postQueueActions;
    private readonly ISidecarRunner _sidecarRunner;
    private readonly ObservableCollection<FileItem> _files = [];
    private readonly ObservableCollection<FinishedFileItem> _finishedFiles = [];
    private readonly CancellationTokenSource _thumbnailCts = new();
    private readonly SemaphoreSlim _thumbnailGate = new(2, 2);
    private CancellationTokenSource? _cancellationTokenSource;
    private string? _selectedFormat;
    private string? _outputDirectory;
    private QualityPreset _qualityPreset = QualityPreset.High;
    private int? _outputWidth;
    private int? _outputHeight;
    private double? _outputFrameRate;
    private string _audioProfile = "aac-320-2";
    private bool _restoringQueue;
    private bool _updatingFfmpegCommand;
    private bool _updatingQueueSelection;
    private QueueSortColumn _queueSortColumn = QueueSortColumn.Manual;
    private bool _queueSortDescending;

    public ConverterPage()
    {
        InitializeComponent();
        _appOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>()
            .Value;
        _qualityPreset = _appOptions.DefaultQuality;
        _outputDirectory = string.IsNullOrWhiteSpace(_appOptions.DefaultOutputDirectory)
            ? null
            : _appOptions.DefaultOutputDirectory;
        OutputDirectoryBox.Text = _outputDirectory ?? "";
        SameAsSourceFolderCheckBox.IsChecked = _outputDirectory is null;
        HighSpeedToggle.IsOn = _appOptions.EnableHardwareAcceleration
            && _appOptions.DefaultHardwareAcceleration != HardwareAcceleration.None;
        // Resolve the singleton orchestrator from DI rather than newing up a
        // private one — every prior page navigation built a fresh registry of
        // 13 converter strategies for no reason.
        _orchestrator = App.Services.GetRequiredService<IConversionOrchestrator>();
        _queueStore = App.Services.GetRequiredService<IBatchQueueStore>();
        _jobCoordinator = App.Services.GetRequiredService<IAppJobCoordinator>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _postQueueActions = App.Services.GetRequiredService<IPostQueueActionService>();
        _sidecarRunner = App.Services.GetRequiredService<ISidecarRunner>();
        _ = RefreshHardwareCapabilitiesAsync();

        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finishedFiles;
        // Establish the mockup's MP4 default without clearing an interrupted
        // queue before RestorePersistedQueue has had a chance to read it.
        _restoringQueue = true;
        SelectFormat("mp4");
        SelectTaggedItem(QualityPresetSelector, _qualityPreset.ToString());
        _restoringQueue = false;
        RestorePersistedQueue();
        UpdateUI();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is ConversionRerunRequest request)
            ApplyRerunRequest(request);
        else if (e.Parameter is FileIntakeRequest intake)
            ApplyFileIntakeRequest(intake);
    }

    private async void ApplyLastUsed_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var request = await _history.GetLastUsedRerunAsync(surface: "converter");
            if (request is null)
            {
                StatusText.Text = AppLocalizer.Get("No saved Converter settings are available yet.");
                return;
            }

            ApplyRerunRequest(request);
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not restore the last Converter settings: {ex.Message}");
        }
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _thumbnailCts.Cancel();
        base.OnNavigatedFrom(e);
    }

    private void ApplyRerunRequest(ConversionRerunRequest request)
    {
        if (!PathSafety.TryNormalizeExtension(request.OutputFormat, out var outputFormat))
        {
            StatusText.Text = AppLocalizer.Get("The saved re-run output format is invalid.");
            return;
        }

        if (_files.Count > 0
            && ((string.IsNullOrWhiteSpace(_selectedFormat)
                 || !_selectedFormat.Equals(outputFormat, StringComparison.OrdinalIgnoreCase))
                || !PathsEqual(_outputDirectory, request.OutputDirectory)))
        {
            StatusText.Text = AppLocalizer.Get("The current queue uses different settings and was preserved. Finish or clear it before restoring this history row.");
            return;
        }

        if (!SelectFormat(outputFormat))
        {
            var supported = request.SourcePaths.All(path =>
                _orchestrator.CanConvert(
                    Path.GetExtension(path).TrimStart('.'),
                    outputFormat));
            if (!supported)
            {
                StatusText.Text = AppLocalizer.Format($"The Converter cannot restore the saved {outputFormat.ToUpperInvariant()} route.");
                return;
            }

            var restoredItem = new ComboBoxItem
            {
                Content = AppLocalizer.Format($"{outputFormat.ToUpperInvariant()} - Restored"),
                Tag = outputFormat,
            };
            FormatSelector.Items.Add(restoredItem);
            FormatSelector.SelectedItem = restoredItem;
        }

        _outputDirectory = request.OutputDirectory;
        OutputDirectoryBox.Text = request.OutputDirectory ?? "";
        if (!string.IsNullOrWhiteSpace(request.FfmpegCommandTemplate))
        {
            SetFfmpegCommandText(request.FfmpegCommandTemplate);
            AdvancedFfmpegExpander.IsExpanded = true;
            var advancedEnabled = App.Services
                .GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>()
                .Value.EnableFfmpegCommandEditing;
            if (advancedEnabled)
                EditFfmpegCommandToggle.IsOn = true;
        }

        var restored = 0;
        foreach (var sourcePath in request.SourcePaths)
        {
            if (!File.Exists(sourcePath))
                continue;

            AddFile(sourcePath, updateUi: false);
            var item = _files.First(file =>
                file.Path.Equals(sourcePath, StringComparison.OrdinalIgnoreCase));
            var perFileRequest = request with
            {
                SourcePaths = [sourcePath],
                OutputPath = request.SourcePaths.Count == 1 ? request.OutputPath : null,
            };
            item.RerunParameters = ConversionRerunRequestCodec.Serialize(perFileRequest);
            item.AudioTrackSelection = perFileRequest.Options.AudioTrackSelection is null
                ? null
                : [.. perFileRequest.Options.AudioTrackSelection];
            item.SubtitleTrackSelection = perFileRequest.Options.SubtitleTrackSelection is null
                ? null
                : [.. perFileRequest.Options.SubtitleTrackSelection];
            item.OutputPath = perFileRequest.OutputPath;
            item.StatusText = "Restored from history";
            restored++;
        }

        PersistQueue();
        UpdateUI();
        StatusText.Text = restored > 0
            ? AppLocalizer.Format($"Restored {restored} file(s) with the saved {outputFormat.ToUpperInvariant()} settings.")
            : AppLocalizer.Get("The saved source file is no longer available.");
    }

    private void ApplyFileIntakeRequest(FileIntakeRequest request)
    {
        var before = _files.Count;
        foreach (var path in request.Paths
                     .Where(path => !string.IsNullOrWhiteSpace(path))
                     .Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (File.Exists(path))
                AddFile(path, updateUi: false);
            else if (Directory.Exists(path))
                AddFolder(path);
        }

        var added = _files.Count - before;
        PersistQueue();
        UpdateUI();
        StatusText.Text = added switch
        {
            0 => AppLocalizer.Get("Those items were already queued or could not be read."),
            1 => AppLocalizer.Get("Added 1 item."),
            _ => AppLocalizer.Format($"Added {added} items."),
        };
    }

    private static bool PathsEqual(string? left, string? right)
    {
        if (string.IsNullOrWhiteSpace(left) && string.IsNullOrWhiteSpace(right))
            return true;
        if (string.IsNullOrWhiteSpace(left) || string.IsNullOrWhiteSpace(right))
            return false;
        try
        {
            return Path.GetFullPath(left).Equals(
                Path.GetFullPath(right),
                StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return left.Equals(right, StringComparison.OrdinalIgnoreCase);
        }
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into conversion queue");
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
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    private void BrowseButton_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private void AddFilesSplitButton_Click(SplitButton sender, SplitButtonClickEventArgs args) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");

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
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
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
        SameAsSourceFolderCheckBox.IsChecked = false;
        PersistQueue();
        UpdateFooterStatus();
    }

    private void SameAsSourceFolder_Changed(object sender, RoutedEventArgs e)
    {
        if (SameAsSourceFolderCheckBox.IsChecked != true)
            return;

        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        if (_queueStore is null)
            return;
        PersistQueue();
        UpdateFooterStatus();
    }

    private void OpenAdvancedSettings_Click(object sender, RoutedEventArgs e)
    {
        AdvancedFfmpegExpander.IsExpanded = true;
        AdvancedFfmpegExpander.Focus(FocusState.Programmatic);
    }

    private void OutputPreference_Changed(object sender, RoutedEventArgs e) => PersistQueue();

    private void OutputProfile_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (QualityPresetSelector?.SelectedItem is ComboBoxItem qualityItem
            && Enum.TryParse(qualityItem.Tag?.ToString(), true, out QualityPreset quality))
        {
            _qualityPreset = quality;
        }

        (_outputWidth, _outputHeight) = ParseResolution(
            (ResolutionSelector?.SelectedItem as ComboBoxItem)?.Tag?.ToString());

        var frameRateTag = (FrameRateSelector?.SelectedItem as ComboBoxItem)?.Tag?.ToString();
        _outputFrameRate = double.TryParse(frameRateTag, out var frameRate) ? frameRate : null;

        _audioProfile = (AudioSelector?.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "source";
        if (_queueStore is null)
            return;
        PersistQueue();
        UpdateFfmpegCommandPreview();
    }

    private static (int? Width, int? Height) ParseResolution(string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag) || tag.Equals("source", StringComparison.OrdinalIgnoreCase))
            return (null, null);

        var dimensions = tag.Split('x', 2, StringSplitOptions.TrimEntries);
        return dimensions.Length == 2
            && int.TryParse(dimensions[0], out var width)
            && int.TryParse(dimensions[1], out var height)
                ? (width, height)
                : (null, null);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = AppLocalizer.Format($"Folder not found: {path}");
            return;
        }

        IEnumerable<string> entries;
        try { entries = Directory.EnumerateFiles(path); }
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
        var examined = 0;
        var truncated = false;
        foreach (var file in entries)
        {
            examined++;
            if (added >= FolderAddCap) { truncated = true; break; }
            if (AddFile(file, updateUi: false))
                added++;
        }

        var addedWord = added == 1 ? "file" : "files";
        if (added == 0)
            StatusText.Text = AppLocalizer.Get("No new files were added from that folder.");
        else if (truncated)
            StatusText.Text = AppLocalizer.Format($"Added {added} {addedWord} from {path} (capped at {FolderAddCap} — pick a smaller folder for the rest).");
        else
            StatusText.Text = AppLocalizer.Format($"Added {added} {addedWord} from {path}.");
        PersistQueue();
        UpdateUI();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        // Case-insensitive on Windows so dropping the same file with a
        // different casing doesn't double-queue it. Compare full paths so a
        // user dragging both `clip.mp4` and `.\clip.mp4` resolves to one.
        if (_files.Any(f => string.Equals(f.Path, path, StringComparison.OrdinalIgnoreCase)))
            return false;

        FileInfo fileInfo;
        long size;
        try
        {
            fileInfo = new FileInfo(path);
            if (!fileInfo.Exists)
                return false;
            // Capture size in the same try so a delete-between-Exists-and-Length
            // race is downgraded from an exception to a skipped file.
            size = fileInfo.Length;
        }
        catch (Exception)
        {
            return false;
        }

        var queuedFile = CreateFileItem(fileInfo, size, "Queued");
        _files.Add(queuedFile);
        QueueThumbnail(queuedFile);

        if (updateUi)
        {
            PersistQueue();
            UpdateUI();
        }

        return true;
    }

    private FileItem CreateFileItem(FileInfo fileInfo, long size, string status)
    {
        var estimate = OutputSizeEstimator.ForLosslessCopy(size);
        var file = new FileItem
        {
            Path = fileInfo.FullName,
            FileName = fileInfo.Name,
            Extension = fileInfo.Extension.TrimStart('.').ToUpperInvariant(),
            FileSize = FormatSize(size),
            Size = size,
            FormatSummary = BuildFormatSummary(fileInfo.Extension),
            StatusText = status,
            Progress = 0,
            EstimatedSizeBytes = estimate.Bytes,
            EstimatedSizeLabel = $"≈ {estimate.DisplayLabel}",
            EstimatedSizeCaveat =
                "Planning estimate based on source size; codec settings determine the final output.",
            HasTrackControls = VideoExtensions.Contains(fileInfo.Extension.TrimStart('.')),
        };
        RefreshFileReview(file);
        return file;
    }

    private void RefreshFileReview(FileItem file)
    {
        var sourceExists = File.Exists(file.Path);
        bool? routeSupported = string.IsNullOrWhiteSpace(_selectedFormat)
            ? null
            : _orchestrator.CanConvert(file.Extension, _selectedFormat);
        var warnings = ConverterPreflightAnalyzer.Analyze(
            file.Extension,
            file.Size,
            sourceExists,
            _selectedFormat,
            routeSupported);

        file.WarningSummary = string.Join(" • ", warnings.Select(item => item.Message));
        file.WarningBadgeText = warnings.Count switch
        {
            0 => AppLocalizer.Get("Ready"),
            1 => warnings[0].Message,
            _ => AppLocalizer.Format($"{warnings.Count} warnings"),
        };
        file.WarningCount = warnings.Count;
        file.HasBlockingWarning = warnings.Any(item =>
            item.Severity == ConverterPreflightSeverity.Error);
    }

    private async void TrackSelection_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { DataContext: FileItem file })
            return;

        if (XamlRoot is null)
        {
            StatusText.Text = AppLocalizer.Get("Track controls are unavailable until the Converter page is loaded.");
            return;
        }

        var rows = new ObservableCollection<ConverterTrackRow>();
        var status = new TextBlock
        {
            Text = AppLocalizer.Get("Reading audio and subtitle streams..."),
            TextWrapping = TextWrapping.Wrap,
        };
        var list = new ItemsControl
        {
            ItemsSource = rows,
            ItemTemplate = Resources["TrackSelectionTemplate"] as DataTemplate,
        };
        var content = new StackPanel
        {
            Spacing = 10,
            MinWidth = 420,
        };
        content.Children.Add(status);
        content.Children.Add(new ScrollViewer
        {
            Content = list,
            MaxHeight = 440,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        });

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = AppLocalizer.Format($"Tracks · {file.FileName}"),
            Content = content,
            PrimaryButtonText = AppLocalizer.Get("Apply"),
            SecondaryButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Primary,
            IsPrimaryButtonEnabled = false,
        };

        var loadTask = LoadTrackRowsAsync(file, rows, status, dialog);
        ContentDialogResult result;
        try
        {
            result = await dialog.ShowAsync();
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not open track controls: {ex.Message}");
            return;
        }

        var loaded = await loadTask;
        if (result != ContentDialogResult.Primary || !loaded)
            return;

        file.AudioTrackSelection = CaptureTrackSelection(rows, audio: true);
        file.SubtitleTrackSelection = CaptureTrackSelection(rows, audio: false);
        PersistQueue();
        UpdateUI();
        StatusText.Text = file.HasTrackSelectionOverride
            ? AppLocalizer.Get("Custom audio and subtitle tracks will be used for this file.")
            : AppLocalizer.Get("All audio and subtitle tracks will be preserved for this file.");
    }

    private async Task<bool> LoadTrackRowsAsync(
        FileItem file,
        ObservableCollection<ConverterTrackRow> rows,
        TextBlock status,
        ContentDialog dialog)
    {
        var ffprobePath = FindFfprobePath();
        if (ffprobePath is null)
        {
            status.Text = AppLocalizer.Get("FFprobe is not available. Install it or set FFPROBE_PATH to inspect tracks.");
            return false;
        }

        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var result = await MediaFidelityProbe.ProbeAsync(ffprobePath, file.Path, timeout.Token);
            if (!result.Succeeded || result.Snapshot is null)
            {
                status.Text = AppLocalizer.Format(
                    $"Could not read tracks: {result.Diagnostic ?? "FFprobe returned no stream data."}");
                return false;
            }

            foreach (var row in BuildTrackRows(result.Snapshot, file))
                rows.Add(row);

            status.Text = rows.Any(row => row.IsSelectable)
                ? AppLocalizer.Get("Clear a track to drop it. Video streams are always preserved.")
                : AppLocalizer.Get("This file has no selectable audio or subtitle streams.");
            dialog.IsPrimaryButtonEnabled = true;
            return true;
        }
        catch (Exception ex)
        {
            status.Text = AppLocalizer.Format($"Could not inspect tracks: {ex.Message}");
            return false;
        }
    }

    private static IReadOnlyList<ConverterTrackRow> BuildTrackRows(
        MediaFidelitySnapshot snapshot,
        FileItem file)
    {
        var rows = new List<ConverterTrackRow>();
        var videoIndex = 0;
        var audioIndex = 0;
        var subtitleIndex = 0;

        foreach (var stream in snapshot.Streams)
        {
            var type = stream.Type.Trim().ToLowerInvariant();
            if (type is not ("video" or "audio" or "subtitle"))
                continue;

            var kindIndex = type switch
            {
                "video" => videoIndex++,
                "audio" => audioIndex++,
                _ => subtitleIndex++,
            };
            var tags = stream.Tags;
            var dimensions = TryGetStreamDimensions(stream.Properties);
            var channels = TryGetStreamInt(stream.Properties, "channels");
            var row = new ConverterTrackRow
            {
                StreamIndex = stream.Index ?? rows.Count,
                KindIndex = kindIndex,
                StreamType = type,
                Codec = string.IsNullOrWhiteSpace(stream.Codec) ? type : stream.Codec!,
                Language = tags.TryGetValue("language", out var language) ? language : null,
                Title = tags.TryGetValue("title", out var title) ? title : null,
                IsDefault = stream.Disposition.TryGetValue("default", out var isDefault) && isDefault == 1,
                Channels = channels,
                Dimensions = dimensions,
            };

            var selected = type == "audio"
                ? file.AudioTrackSelection
                : type == "subtitle"
                    ? file.SubtitleTrackSelection
                    : null;
            row.Keep = selected is null || selected.Contains(kindIndex);
            rows.Add(row);
        }

        return rows;
    }

    private static string? TryGetStreamDimensions(IReadOnlyDictionary<string, string> properties)
    {
        if (!properties.TryGetValue("width", out var width)
            || !properties.TryGetValue("height", out var height)
            || string.IsNullOrWhiteSpace(width)
            || string.IsNullOrWhiteSpace(height))
        {
            return null;
        }

        return $"{width}x{height}";
    }

    private static int? TryGetStreamInt(
        IReadOnlyDictionary<string, string> properties,
        string property)
    {
        return properties.TryGetValue(property, out var value)
            && int.TryParse(value, out var parsed)
                ? parsed
                : null;
    }

    private static List<int>? CaptureTrackSelection(
        IEnumerable<ConverterTrackRow> rows,
        bool audio)
    {
        var selectable = rows
            .Where(row => audio ? row.IsAudio : row.IsSubtitle)
            .OrderBy(row => row.KindIndex)
            .ToList();
        if (selectable.Count == 0 || selectable.All(row => row.Keep))
            return null;

        return selectable
            .Where(row => row.Keep)
            .Select(row => row.KindIndex)
            .ToList();
    }

    private string? FindFfprobePath()
    {
        var executable = OperatingSystem.IsWindows() ? "ffprobe.exe" : "ffprobe";
        var candidates = new List<string?>
        {
            Environment.GetEnvironmentVariable("FFPROBE_PATH"),
            Path.Combine(_appOptions.ToolsBasePath, "bin", executable),
            Path.Combine(_appOptions.ToolsBasePath, executable),
            Path.Combine(_appOptions.ToolsBasePath, "ffmpeg", executable),
            Path.Combine(_appOptions.ToolsBasePath, "_bin", executable),
            Path.Combine(_appOptions.ToolsBasePath, "videocrush", executable),
            Path.Combine(_appOptions.ToolsBasePath, "clipforge", executable),
            Path.Combine(AppContext.BaseDirectory, "tools", "bin", executable),
            Path.Combine(AppContext.BaseDirectory, "tools", "_bin", executable),
        };

        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            candidates.Add(Path.Combine(directory.FullName, "tools", "ffmpeg", executable));
            candidates.Add(Path.Combine(directory.FullName, "tools", "_bin", executable));
            candidates.Add(Path.Combine(directory.FullName, "tools", "videocrush", executable));
            candidates.Add(Path.Combine(directory.FullName, "tools", "clipforge", executable));
            directory = directory.Parent;
        }

        if (_appOptions.SearchSystemTools)
        {
            var path = Environment.GetEnvironmentVariable("PATH") ?? "";
            candidates.AddRange(path
                .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
                .Select(directory => Path.Combine(directory.Trim(), executable)));
        }

        return candidates.FirstOrDefault(path =>
            !string.IsNullOrWhiteSpace(path) && File.Exists(path));
    }

    private void QueueThumbnail(FileItem file) => _ = LoadThumbnailAsync(file, _thumbnailCts.Token);

    private async Task LoadThumbnailAsync(FileItem file, CancellationToken cancellationToken)
    {
        var cachePath = GetThumbnailCachePath(file);
        if (File.Exists(cachePath))
        {
            SetThumbnail(file, cachePath);
            return;
        }

        if (_sidecarRunner.Locate("mediathumb") is null)
            return;

        try
        {
            await _thumbnailGate.WaitAsync(cancellationToken);
            try
            {
                if (!File.Exists(cachePath))
                {
                    var outputDirectory = Path.GetDirectoryName(cachePath)!;
                    Directory.CreateDirectory(outputDirectory);
                    string? emittedPath = null;
                    var result = await _sidecarRunner.RunAsync(
                        "mediathumb",
                        [
                            "thumb",
                            "--input", file.Path,
                            "--output-dir", outputDirectory,
                            "--size", "96",
                        ],
                        ct: cancellationToken,
                        onRawEvent: (eventName, payload) =>
                        {
                            if (eventName == "thumb_doc"
                                && payload.TryGetProperty("output", out var output)
                                && output.ValueKind == System.Text.Json.JsonValueKind.String)
                            {
                                emittedPath = output.GetString();
                            }
                        });

                    if (!result.Success)
                        return;

                    if (!string.IsNullOrWhiteSpace(emittedPath) && File.Exists(emittedPath))
                        cachePath = emittedPath;
                }

                if (File.Exists(cachePath))
                    SetThumbnail(file, cachePath);
            }
            finally
            {
                _thumbnailGate.Release();
            }
        }
        catch (OperationCanceledException)
        {
            // Navigating away cancels thumbnail work without affecting the queue.
        }
        catch (Exception)
        {
            // A preview is optional; keep the file-type glyph when a codec or
            // cache location is unavailable rather than failing the queue.
        }
    }

    private static string GetThumbnailCachePath(FileItem file)
    {
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
            localAppData = Path.GetTempPath();

        long modifiedTicks;
        try { modifiedTicks = File.GetLastWriteTimeUtc(file.Path).Ticks; }
        catch { modifiedTicks = 0; }

        var fingerprint = $"{Path.GetFullPath(file.Path)}\n{file.Size}\n{modifiedTicks}";
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(fingerprint)))
            .ToLowerInvariant()[..20];
        return Path.Combine(
            localAppData,
            "UniversalConverterX",
            "cache",
            "queue-thumbnails",
            digest,
            $"{Path.GetFileNameWithoutExtension(file.Path)}.jpg");
    }

    private void SetThumbnail(FileItem file, string path)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            if (!_files.Contains(file) || !File.Exists(path))
                return;

            file.ThumbnailSource = new BitmapImage(new Uri(path))
            {
                DecodePixelWidth = 96,
                DecodePixelHeight = 96,
            };
        });
    }

    private void QueueSort_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string tag }
            || !Enum.TryParse<QueueSortColumn>(tag, ignoreCase: true, out var column))
        {
            return;
        }

        if (_queueSortColumn == column)
            _queueSortDescending = !_queueSortDescending;
        else
        {
            _queueSortColumn = column;
            _queueSortDescending = false;
        }

        ApplyQueueSort();
        UpdateQueueSortHeaders();
    }

    private void ApplyQueueSort()
    {
        if (_queueSortColumn == QueueSortColumn.Manual)
            return;

        IEnumerable<FileItem> ordered = _queueSortColumn switch
        {
            QueueSortColumn.Format => _files
                .OrderBy(file => file.FormatSummary, StringComparer.OrdinalIgnoreCase)
                .ThenBy(file => file.FileName, StringComparer.OrdinalIgnoreCase),
            QueueSortColumn.Size => _files
                .OrderBy(file => file.Size)
                .ThenBy(file => file.FileName, StringComparer.OrdinalIgnoreCase),
            QueueSortColumn.Estimate => _files
                .OrderBy(file => file.EstimatedSizeBytes ?? long.MaxValue)
                .ThenBy(file => file.FileName, StringComparer.OrdinalIgnoreCase),
            QueueSortColumn.Warnings => _files
                .OrderBy(file => file.WarningCount)
                .ThenBy(file => file.FileName, StringComparer.OrdinalIgnoreCase),
            _ => _files.OrderBy(file => file.FileName, StringComparer.OrdinalIgnoreCase),
        };
        if (_queueSortDescending)
            ordered = ordered.Reverse();

        var snapshot = ordered.ToList();
        for (var targetIndex = 0; targetIndex < snapshot.Count; targetIndex++)
        {
            var currentIndex = _files.IndexOf(snapshot[targetIndex]);
            if (currentIndex != targetIndex)
                _files.Move(currentIndex, targetIndex);
        }
    }

    private void UpdateQueueSortHeaders()
    {
        QueueSortFileButton.Content = SortHeader(AppLocalizer.Get("File"), QueueSortColumn.File);
        QueueSortFormatButton.Content = SortHeader(AppLocalizer.Get("Format"), QueueSortColumn.Format);
        QueueSortSizeButton.Content = SortHeader(AppLocalizer.Get("Size"), QueueSortColumn.Size);
        QueueSortWarningsButton.Content = SortHeader(AppLocalizer.Get("Status"), QueueSortColumn.Warnings);
    }

    private string SortHeader(string label, QueueSortColumn column) =>
        _queueSortColumn == column
            ? $"{label} {(_queueSortDescending ? "↓" : "↑")}"
            : label;

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is FileItem file)
        {
            _files.Remove(file);
            PersistQueue();
            UpdateUI();
        }
    }

    private void QueueItemSelection_Changed(object sender, RoutedEventArgs e)
    {
        if (!_updatingQueueSelection)
            UpdateQueueSelectionActions();
    }

    private void SelectAllQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_updatingQueueSelection)
            return;

        var selectAll = SelectAllQueueCheckBox.IsChecked == true;
        _updatingQueueSelection = true;
        try
        {
            foreach (var file in _files)
                file.IsSelected = selectAll;
        }
        finally
        {
            _updatingQueueSelection = false;
        }

        UpdateQueueSelectionActions();
    }

    private void MoveSelectedUp_Click(object sender, RoutedEventArgs e)
    {
        _queueSortColumn = QueueSortColumn.Manual;
        for (var index = 1; index < _files.Count; index++)
        {
            if (_files[index].IsSelected && !_files[index - 1].IsSelected)
                _files.Move(index, index - 1);
        }

        PersistQueue();
        UpdateUI();
    }

    private void MoveSelectedDown_Click(object sender, RoutedEventArgs e)
    {
        _queueSortColumn = QueueSortColumn.Manual;
        for (var index = _files.Count - 2; index >= 0; index--)
        {
            if (_files[index].IsSelected && !_files[index + 1].IsSelected)
                _files.Move(index, index + 1);
        }

        PersistQueue();
        UpdateUI();
    }

    private async void RemoveSelected_Click(object sender, RoutedEventArgs e)
    {
        var selected = _files.Where(file => file.IsSelected).ToList();
        if (selected.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Remove selected files?",
                $"Remove {selected.Count} selected file(s) from the conversion queue?"))
        {
            return;
        }

        foreach (var file in selected)
            _files.Remove(file);

        PersistQueue();
        UpdateUI();
    }

    private void UpdateQueueSelectionActions()
    {
        var selectedCount = _files.Count(file => file.IsSelected);
        _updatingQueueSelection = true;
        try
        {
            SelectAllQueueCheckBox.IsChecked = selectedCount switch
            {
                0 => false,
                _ when selectedCount == _files.Count => true,
                _ => null,
            };
        }
        finally
        {
            _updatingQueueSelection = false;
        }

        RemoveSelectedButton.IsEnabled = selectedCount > 0;
        MoveSelectedUpButton.IsEnabled = _files
            .Select((file, index) => (file, index))
            .Any(entry => entry.file.IsSelected
                && entry.index > 0
                && !_files[entry.index - 1].IsSelected);
        MoveSelectedDownButton.IsEnabled = _files
            .Select((file, index) => (file, index))
            .Any(entry => entry.file.IsSelected
                && entry.index < _files.Count - 1
                && !_files[entry.index + 1].IsSelected);
    }

    private async void ClearAll_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear conversion queue?",
                $"Remove {_files.Count} queued file(s)? Finished results stay available."))
        {
            return;
        }

        _files.Clear();
        PersistQueue();
        UpdateUI();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateUI();
    }

    private void FormatSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (FormatSelector.SelectedItem is ComboBoxItem item)
        {
            _selectedFormat = item.Tag?.ToString();
            foreach (var file in _files)
                file.FormatSummary = BuildFormatSummary(file.Extension);
            PersistQueue();
            UpdateUI();
        }
    }

    private void RestorePersistedQueue()
    {
        _restoringQueue = true;
        try
        {
            var queue = _queueStore.Load(QueueKey);
            if (queue is null || queue.Jobs.Count == 0)
                return;

            if (queue.Settings.TryGetValue("targetFormat", out var targetFormat)
                && !string.IsNullOrWhiteSpace(targetFormat))
            {
                SelectFormat(targetFormat);
            }

            if (queue.Settings.TryGetValue("outputDirectory", out var outputDirectory)
                && !string.IsNullOrWhiteSpace(outputDirectory))
            {
                _outputDirectory = outputDirectory;
                OutputDirectoryBox.Text = outputDirectory;
                SameAsSourceFolderCheckBox.IsChecked = false;
            }

            RestoreOutputProfile(queue.Settings);

            var restored = 0;
            foreach (var job in queue.Jobs)
            {
                if (string.IsNullOrWhiteSpace(job.SourcePath)
                    || !File.Exists(job.SourcePath)
                    || _files.Any(f => string.Equals(f.Path, job.SourcePath, StringComparison.OrdinalIgnoreCase)))
                    continue;

                var info = new FileInfo(job.SourcePath);
                var status = job.Status switch
                {
                    "Running" or "Converting" or "Cancelling" or "Interrupted" => "Interrupted - ready to retry",
                    "Failed" => "Failed - ready to retry",
                    "Cancelled" => "Cancelled - ready to retry",
                    "Skipped" => "Skipped",
                    _ => "Queued",
                };

                var restoredFile = CreateFileItem(info, info.Length, status);
                restoredFile.Id = string.IsNullOrWhiteSpace(job.Id)
                    ? Guid.NewGuid().ToString("N")
                    : job.Id;
                restoredFile.OutputPath = job.OutputPath;
                restoredFile.ErrorMessage = job.ErrorMessage;
                restoredFile.PersistedArgs = [.. job.Args];
                restoredFile.AudioTrackSelection = job.AudioTrackSelection is null
                    ? null
                    : [.. job.AudioTrackSelection];
                restoredFile.SubtitleTrackSelection = job.SubtitleTrackSelection is null
                    ? null
                    : [.. job.SubtitleTrackSelection];
                _files.Add(restoredFile);
                QueueThumbnail(restoredFile);
                restored++;
            }

            if (restored > 0)
                StatusText.Text = AppLocalizer.Format($"Restored {restored} queued conversion(s) from the previous session.");
        }
        finally
        {
            _restoringQueue = false;
        }

        PersistQueue();
    }

    private void PersistQueue()
    {
        if (_restoringQueue || _queueStore is null)
            return;

        var activeJobs = _files
            .Where(f => !f.StatusText.Equals("Done", StringComparison.OrdinalIgnoreCase))
            .Select(f => new PersistedBatchJob
            {
                Id = string.IsNullOrWhiteSpace(f.Id) ? Guid.NewGuid().ToString("N") : f.Id,
                SourcePath = f.Path,
                OutputPath = f.OutputPath,
                Engine = "converter",
                Action = "convert",
                Preset = _selectedFormat,
                Args = f.PersistedArgs,
                AudioTrackSelection = f.AudioTrackSelection is null
                    ? null
                    : [.. f.AudioTrackSelection],
                SubtitleTrackSelection = f.SubtitleTrackSelection is null
                    ? null
                    : [.. f.SubtitleTrackSelection],
                Status = NormalizePersistedStatus(f.StatusText),
                ErrorMessage = f.ErrorMessage,
            })
            .ToList();

        if (activeJobs.Count == 0)
        {
            _queueStore.Clear(QueueKey);
            _jobCoordinator.NotifyJobsChanged();
            return;
        }

        _queueStore.Save(new PersistedBatchQueue
        {
            QueueKey = QueueKey,
            PageName = QueuePageName,
            Settings = new Dictionary<string, string?>
            {
                ["targetFormat"] = _selectedFormat,
                ["outputDirectory"] = _outputDirectory,
                ["qualityPreset"] = _qualityPreset.ToString(),
                ["resolution"] = _outputWidth.HasValue && _outputHeight.HasValue
                    ? $"{_outputWidth}x{_outputHeight}"
                    : "source",
                ["frameRate"] = _outputFrameRate?.ToString(System.Globalization.CultureInfo.InvariantCulture) ?? "source",
                ["audioProfile"] = _audioProfile,
                ["openOutputAfterConversion"] = OpenOutputAfterConversionCheckBox.IsChecked == true ? "true" : "false",
            },
            Jobs = activeJobs,
        });
        _jobCoordinator.NotifyJobsChanged();
    }

    private static string NormalizePersistedStatus(string status)
    {
        if (status.StartsWith("Interrupted", StringComparison.OrdinalIgnoreCase))
            return "Interrupted";
        if (status.StartsWith("Failed", StringComparison.OrdinalIgnoreCase))
            return "Failed";
        if (status.StartsWith("Cancelled", StringComparison.OrdinalIgnoreCase))
            return "Cancelled";
        if (status.StartsWith("Skipped", StringComparison.OrdinalIgnoreCase))
            return "Skipped";
        if (status.Equals("Converting", StringComparison.OrdinalIgnoreCase)
            || status.EndsWith("%", StringComparison.Ordinal))
            return "Running";
        return "Queued";
    }

    private void SmartMatch_Click(object sender, RoutedEventArgs e)
    {
        var recommended = RecommendFormatTag();
        if (recommended is null)
            return;

        SelectFormat(recommended);
        StatusText.Text = AppLocalizer.Format($"Applied the recommended {recommended.ToUpperInvariant()} output profile.");
    }

    private void ProfileShortcut_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string format })
        {
            SelectFormat(format);
            StatusText.Text = AppLocalizer.Format($"Output profile set to {format.ToUpperInvariant()}.");
        }
    }

    private void UpdateUI()
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finishedFiles.Count > 0;
        foreach (var file in _files)
            RefreshFileReview(file);
        ApplyQueueSort();
        UpdateQueueSortHeaders();
        var blockingFiles = _files.Count(file => file.HasBlockingWarning);
        var warningFiles = _files.Count(file => file.WarningCount > 0);
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        QueueReviewTable.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        ConvertButton.IsEnabled = hasFiles
            && !string.IsNullOrEmpty(_selectedFormat)
            && blockingFiles == 0
            && _cancellationTokenSource is null;
        SmartMatchButton.IsEnabled = hasFiles && RecommendFormatTag() is not null;
        var fileWord = _files.Count == 1 ? "file" : "files";
        QueueSummaryText.Text = warningFiles > 0
            ? AppLocalizer.Format($"{_files.Count} {fileWord} / {warningFiles} {(warningFiles == 1 ? "needs" : "need")} review")
            : AppLocalizer.Format($"{_files.Count} {fileWord}");
        UpdateQueueSelectionActions();
        RecommendationText.Text = BuildRecommendationText();
        UpdateFooterStatus();
        if (EditFfmpegCommandToggle?.IsOn != true)
            UpdateFfmpegCommandPreview();
    }

    private void UpdateFooterStatus()
    {
        var output = _outputDirectory ?? "same folder as each source";
        FooterStatusText.Text = AppLocalizer.Format($"Output: {output}");

        if (_files.Count == 0)
            StatusText.Text = AppLocalizer.Get("Add files to start a conversion queue.");
        else if (string.IsNullOrEmpty(_selectedFormat))
            StatusText.Text = AppLocalizer.Get("Choose an output profile before starting.");
        else if (_files.Any(file => file.HasBlockingWarning))
            StatusText.Text = AppLocalizer.Get("Resolve the blocked file routes shown in the queue before converting.");
        else
            StatusText.Text = AppLocalizer.Format($"Ready to convert {_files.Count} files to {_selectedFormat.ToUpperInvariant()}.");
    }

    private string BuildRecommendationText()
    {
        if (_files.Count == 0)
            return "Add files to receive a local output recommendation.";

        var tag = RecommendFormatTag();
        return tag switch
        {
            "mp4" => "Recommended: MP4 for broad playback, sharing, browser upload, and device compatibility.",
            "mp3" => "Recommended: MP3 for compact audio extraction and broad player support.",
            "webp" => "Recommended: WebP for modern image sharing with smaller file sizes.",
            "pdf" => "Recommended: PDF for fixed-layout document delivery and sharing.",
            _ => "This mixed batch does not have a single safe default. Choose a profile that matches your output goal.",
        };
    }

    private string? RecommendFormatTag()
    {
        if (_files.Count == 0)
            return null;

        var categories = _files
            .Select(file => CategorizeExtension(file.Extension))
            .GroupBy(category => category)
            .OrderByDescending(group => group.Count())
            .ToList();

        var dominant = categories.FirstOrDefault();
        if (dominant is null || dominant.Key == FileCategory.Unknown)
            return null;

        if (dominant.Count() < Math.Ceiling(_files.Count * 0.6))
            return null;

        return dominant.Key switch
        {
            FileCategory.Video => "mp4",
            FileCategory.Audio => "mp3",
            FileCategory.Image => "webp",
            FileCategory.Document => "pdf",
            _ => null,
        };
    }

    private bool SelectFormat(string format)
    {
        foreach (var item in FormatSelector.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Tag?.ToString(), format, StringComparison.OrdinalIgnoreCase))
            {
                FormatSelector.SelectedItem = item;
                return true;
            }
        }

        return false;
    }

    private static FileCategory CategorizeExtension(string extension)
    {
        var normalized = extension.TrimStart('.').ToUpperInvariant();
        if (VideoExtensions.Contains(normalized))
            return FileCategory.Video;
        if (AudioExtensions.Contains(normalized))
            return FileCategory.Audio;
        if (ImageExtensions.Contains(normalized))
            return FileCategory.Image;
        if (DocumentExtensions.Contains(normalized))
            return FileCategory.Document;
        return FileCategory.Unknown;
    }

    private async void ConvertButton_Click(object sender, RoutedEventArgs e)
    {
        var selectedFormat = _selectedFormat;
        if (_files.Count == 0 || string.IsNullOrEmpty(selectedFormat))
            return;

        if (!TryValidateFfmpegOverrideForQueue(out var commandError))
        {
            AdvancedFfmpegExpander.IsExpanded = true;
            SetFfmpegCommandStatus(false, commandError!);
            StatusText.Text = commandError!;
            return;
        }

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                StatusText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
                return;
            }
        }

        _cancellationTokenSource = new CancellationTokenSource();
        ConvertButton.IsEnabled = false;
        ProgressOverlay.Visibility = Visibility.Visible;
        ProgressTitle.Text = AppLocalizer.Get("Converting...");
        ConversionProgress.Value = 0;
        ConversionProgress.IsIndeterminate = false;
        CancelButton.Content = AppLocalizer.Get("Cancel");

        var queuedJobs = _files
            .Where(f => !f.StatusText.Equals("Done", StringComparison.OrdinalIgnoreCase))
            .Select(f =>
            {
                var outputPath = string.IsNullOrWhiteSpace(f.OutputPath)
                    ? BuildOutputPath(f.Path, selectedFormat)
                    : f.OutputPath!;
                f.OutputPath = outputPath;
                f.PersistedArgs = BuildRetryArgs(selectedFormat, outputPath);
                f.ErrorMessage = null;
                if (!f.StatusText.StartsWith("Failed", StringComparison.OrdinalIgnoreCase)
                    && !f.StatusText.StartsWith("Cancelled", StringComparison.OrdinalIgnoreCase)
                    && !f.StatusText.StartsWith("Interrupted", StringComparison.OrdinalIgnoreCase))
                    f.StatusText = "Queued";
                var savedRequest = TryGetRerunRequest(f.RerunParameters);
                var commandTemplate = EditFfmpegCommandToggle.IsOn
                    ? FfmpegCommandBox.Text
                    : savedRequest?.FfmpegCommandTemplate;
                return new QueuedConversion(
                    f,
                    CreateJob(
                        f.Path,
                        selectedFormat,
                        outputPath,
                        savedRequest?.Options,
                        commandTemplate,
                        f),
                    selectedFormat,
                    _outputDirectory,
                    commandTemplate);
            })
            .ToList();
        PersistQueue();
        var completed = 0;
        var failed = 0;
        var cancelled = 0;
        var batchStartedAt = DateTime.UtcNow;
        var completionItems = new ConcurrentQueue<QueueCompletionItem>();
        var cancellation = _cancellationTokenSource
            ?? throw new InvalidOperationException("Conversion cancellation source was not initialized.");
        var registeredHandles = queuedJobs
            .Select(queued => new AppJobHandle(QueueKey, queued.File.Id))
            .ToList();
        foreach (var handle in registeredHandles)
            _jobCoordinator.RegisterCancellation(handle, cancellation.Cancel);

        // Get max parallel jobs from settings
        var options = App.Services.GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>().Value;
        var maxParallel = Math.Max(1, options.MaxParallelConversions);
        var semaphore = new SemaphoreSlim(maxParallel, maxParallel);

        try
        {
            var tasks = queuedJobs.Select(async queued =>
            {
                var enteredSemaphore = false;
                try
                {
                    await semaphore.WaitAsync(cancellation.Token);
                    enteredSemaphore = true;
                    cancellation.Token.ThrowIfCancellationRequested();

                    DispatcherQueue.TryEnqueue(() =>
                    {
                        queued.File.StatusText = "Converting";
                        queued.File.Progress = 0;
                        queued.File.ErrorMessage = null;
                        ProgressStatus.Text = AppLocalizer.Format($"Converting {queued.Job.InputFileName}...");
                        UpdateProgressDetails(queuedJobs.Count, completed + failed);
                        PersistQueue();
                    });

                    var progress = new Progress<ConversionProgress>(p =>
                    {
                        DispatcherQueue.TryEnqueue(() =>
                        {
                            if (p.IsIndeterminate)
                            {
                                ConversionProgress.IsIndeterminate = true;
                                queued.File.StatusText = p.StatusMessage ?? p.Stage.ToString();
                                return;
                            }

                            ConversionProgress.IsIndeterminate = false;
                            queued.File.Progress = p.Percent;
                            var overallProgress = ((completed + failed) * 100.0 + p.Percent) / queuedJobs.Count;
                            ConversionProgress.Value = overallProgress;
                            queued.File.StatusText = $"{p.Percent:F0}%";

                            if (p.EstimatedTimeRemaining.HasValue)
                                ProgressDetails.Text = AppLocalizer.Format($"{completed + failed + 1} of {queuedJobs.Count} - ETA {p.EstimatedTimeRemaining.Value:mm\\:ss}");
                        });
                    });

                    var result = await _orchestrator.ConvertAsync(queued.Job, progress, cancellation.Token);
                    await LogHistoryAsync(queued, result);
                    completionItems.Enqueue(BuildCompletionItem(queued.Job.InputPath, result));

                    if (result.Success || result.WasSkipped)
                    {
                        Interlocked.Increment(ref completed);
                        DispatcherQueue.TryEnqueue(() =>
                        {
                            AddFinishedItem(result);
                            queued.File.OutputPath = result.OutputPath ?? result.Job.OutputPath;
                            queued.File.Progress = 100;
                            queued.File.StatusText = "Done";
                            queued.File.ErrorMessage = null;
                            PersistQueue();
                        });
                    }
                    else if (result.WasCancelled || cancellation.IsCancellationRequested)
                    {
                        Interlocked.Increment(ref cancelled);
                        DispatcherQueue.TryEnqueue(() =>
                        {
                            AddFinishedItem(result);
                            queued.File.OutputPath = result.OutputPath ?? result.Job.OutputPath;
                            queued.File.StatusText = "Cancelled - ready to retry";
                            queued.File.ErrorMessage = result.ErrorMessage ?? "Conversion cancelled by user.";
                            PersistQueue();
                        });
                    }
                    else
                    {
                        Interlocked.Increment(ref failed);
                        DispatcherQueue.TryEnqueue(() =>
                        {
                            AddFinishedItem(result);
                            queued.File.OutputPath = result.OutputPath ?? result.Job.OutputPath;
                            queued.File.StatusText = "Failed - ready to retry";
                            queued.File.ErrorMessage = result.ErrorMessage;
                            PersistQueue();
                        });
                    }
                }
                catch (OperationCanceledException)
                {
                    Interlocked.Increment(ref cancelled);
                    var duration = queued.Job.StartedAt is DateTime started
                        ? DateTime.UtcNow - started
                        : TimeSpan.Zero;
                    await LogHistoryAsync(queued, ConversionResult.Cancelled(queued.Job, duration));
                    completionItems.Enqueue(new QueueCompletionItem
                    {
                        Source = queued.Job.InputPath,
                        Status = QueueCompletionItemStatus.Cancelled,
                        Message = AppLocalizer.Get("Conversion cancelled by user."),
                    });
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        queued.File.StatusText = "Cancelled - ready to retry";
                        queued.File.ErrorMessage = "Conversion cancelled by user.";
                        PersistQueue();
                    });
                }
                catch (Exception ex)
                {
                    Interlocked.Increment(ref failed);
                    var duration = queued.Job.StartedAt is DateTime started
                        ? DateTime.UtcNow - started
                        : TimeSpan.Zero;
                    await LogHistoryAsync(queued, ConversionResult.Failed(queued.Job, ex.Message, duration));
                    completionItems.Enqueue(new QueueCompletionItem
                    {
                        Source = queued.Job.InputPath,
                        Status = QueueCompletionItemStatus.Failed,
                        Message = ex.Message,
                    });
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        queued.File.StatusText = "Failed - ready to retry";
                        queued.File.ErrorMessage = ex.Message;
                        PersistQueue();
                    });
                }
                finally
                {
                    if (enteredSemaphore)
                        semaphore.Release();
                }
            });

            await Task.WhenAll(tasks);
            var outcome = new ConversionBatchOutcome(
                completed,
                failed,
                cancelled,
                cancellation.IsCancellationRequested);

            DispatcherQueue.TryEnqueue(() =>
            {
                ProgressTitle.Text = outcome.Title;
                ProgressStatus.Text = outcome.Status;
                if (!outcome.WasCancelled)
                    ConversionProgress.Value = 100;
                ConversionProgress.IsIndeterminate = false;
                CancelButton.Content = AppLocalizer.Get("Close");
                QueuePivot.SelectedIndex = _finishedFiles.Count > 0 ? 1 : 0;
                if (completed > 0 && OpenOutputAfterConversionCheckBox.IsChecked == true)
                {
                    var output = _outputDirectory
                        ?? _finishedFiles.LastOrDefault(f => f.Success && !string.IsNullOrWhiteSpace(f.OutputPath))?.OutputPath;
                    OpenContainingFolder(output);
                }
            });

            if (!completionItems.IsEmpty)
            {
                var actionResult = await _postQueueActions.ExecuteAsync(new QueueCompletionSummary
                {
                    Workflow = "Converter",
                    StartedUtc = batchStartedAt,
                    CompletedUtc = DateTime.UtcNow,
                    Items = completionItems.ToArray(),
                });
                if (actionResult.Action != QueueCompletionAction.None && !actionResult.Executed)
                    DispatcherQueue.TryEnqueue(() => StatusText.Text = actionResult.Message);
            }
        }
        finally
        {
            foreach (var handle in registeredHandles)
                _jobCoordinator.UnregisterCancellation(handle);
            semaphore?.Dispose();
            _cancellationTokenSource?.Dispose();
            _cancellationTokenSource = null;
            DispatcherQueue.TryEnqueue(() =>
            {
                ConvertButton.IsEnabled = true;
                PersistQueue();
            });
        }
    }

    private void UpdateProgressDetails(int total, int current)
    {
        ProgressDetails.Text = AppLocalizer.Format($"{current + 1} of {total}");
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_cancellationTokenSource != null)
        {
            _cancellationTokenSource.Cancel();
        }
        else
        {
            ProgressOverlay.Visibility = Visibility.Collapsed;
            CancelButton.Content = AppLocalizer.Get("Cancel");
        }
    }

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var path = _outputDirectory
            ?? _finishedFiles.LastOrDefault(f => f.Success && !string.IsNullOrWhiteSpace(f.OutputPath))?.OutputPath
            ?? _files.FirstOrDefault()?.Path;
        OpenContainingFolder(path);
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private void AddFinishedItem(ConversionResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var fileName = result.Success && !string.IsNullOrWhiteSpace(result.OutputPath)
            ? Path.GetFileName(result.OutputPath)
            : result.Job.InputFileName;
        var details = result.Success
            ? $"{FormatSize(result.OutputSize)} - {result.ConverterUsed ?? "Converted"} - {result.Duration:mm\\:ss}"
            : result.ErrorMessage ?? "Conversion failed";

        _finishedFiles.Insert(0, new FinishedFileItem
        {
            FileName = fileName,
            Details = details,
            OutputPath = result.OutputPath ?? "",
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });

        // Bound the in-session list. The full audit log lives in History; this
        // collection just powers the "Finished" tab on the page itself.
        while (_finishedFiles.Count > FinishedCap)
            _finishedFiles.RemoveAt(_finishedFiles.Count - 1);
    }

    private async Task LogHistoryAsync(QueuedConversion queued, ConversionResult result)
    {
        try
        {
            var rerun = new ConversionRerunRequest
            {
                SourcePaths = [queued.Job.InputPath],
                OutputFormat = queued.OutputFormat,
                OutputDirectory = queued.OutputDirectory,
                OutputPath = result.OutputPath ?? queued.Job.OutputPath,
                Options = queued.Job.Options,
                FfmpegCommandTemplate = queued.FfmpegCommandTemplate,
            };
            var errorCode = result switch
            {
                { WasCancelled: true } => "cancelled",
                { WasSkipped: true } => "skipped",
                { ExitCode: not 0 } => $"exit_{result.ExitCode}",
                _ => null,
            };

            await _history.LogAsync(new HistoryRecord
            {
                Timestamp = queued.Job.StartedAt ?? queued.Job.CreatedAt,
                Engine = result.ConverterUsed ?? queued.Job.Options.ForceConverter ?? "converter",
                Action = "convert",
                SourcePath = queued.Job.InputPath,
                OutputPath = result.Success ? result.OutputPath : null,
                SourceBytes = queued.Job.InputFileSize > 0
                    ? queued.Job.InputFileSize
                    : queued.File.Size,
                OutputBytes = result.Success ? result.OutputSize : null,
                DurationSeconds = result.Duration.TotalSeconds,
                Success = result.Success,
                ErrorCode = errorCode,
                ErrorMessage = result.ErrorMessage,
                Profile = queued.OutputFormat,
                RerunParameters = ConversionRerunRequestCodec.Serialize(rerun),
                Provenance = BuildConversionProvenance(queued.Job, result),
            });
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"History logging failed: {ex}");
        }
    }

    private string? BuildConversionProvenance(ConversionJob job, ConversionResult result)
    {
        if (!string.Equals(result.ConverterUsed, "ffmpeg", StringComparison.OrdinalIgnoreCase))
            return null;

        try
        {
            var converter = new FFmpegConverter(_appOptions.ToolsBasePath);
            var executablePath = converter.ResolveExecutablePath();
            var errorCode = result switch
            {
                { WasCancelled: true } => "cancelled",
                { WasSkipped: true } => "skipped",
                { ExitCode: not 0 } => $"exit_{result.ExitCode}",
                _ => null,
            };
            var provenance = new JobProvenance
            {
                StartedUtc = job.StartedAt ?? job.CreatedAt,
                DurationSeconds = result.Duration.TotalSeconds,
                Engine = "ffmpeg",
                RedactedArgs = result.CommandLine is null
                    ? []
                    : [ArgumentRedactor.RedactMessage(result.CommandLine)],
                Executable = ExecutableIdentity.Capture(
                    "ffmpeg",
                    executablePath,
                    typeof(FFmpegConverter).Assembly.GetName().Version?.ToString(3)),
                Input = FileIdentity.Capture(job.InputPath),
                Output = FileIdentity.Capture(result.OutputPath ?? job.OutputPath),
                Capability = result.Capability,
                ProductVersion = typeof(ConverterPage).Assembly.GetName().Version?.ToString(3),
                ExitCode = result.ExitCode,
                Succeeded = result.Success,
                ErrorCode = errorCode,
            };
            return JobProvenanceCodec.Serialize(provenance);
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"Conversion provenance capture failed: {ex}");
            return null;
        }
    }

    private static QueueCompletionItem BuildCompletionItem(
        string sourcePath,
        ConversionResult result) => new()
    {
        Source = sourcePath,
        Output = result.OutputPath,
        Status = result switch
        {
            { WasCancelled: true } => QueueCompletionItemStatus.Cancelled,
            { Success: true } or { WasSkipped: true } => QueueCompletionItemStatus.Succeeded,
            _ => QueueCompletionItemStatus.Failed,
        },
        Message = result.Warnings.Count > 0
            ? string.Join(" ", result.Warnings)
            : result.ErrorMessage,
    };

    private ConversionJob CreateJob(
        string inputPath,
        string outputFormat,
        string? outputPathOverride = null,
        ConversionOptions? optionsOverride = null,
        string? ffmpegCommandTemplate = null,
        FileItem? file = null)
    {
        var outputPath = string.IsNullOrWhiteSpace(outputPathOverride)
            ? BuildOutputPath(inputPath, outputFormat)
            : outputPathOverride;
        ConversionOptions conversionOptions;
        if (optionsOverride is not null)
        {
            conversionOptions = CloneOptions(optionsOverride);
        }
        else
        {
            conversionOptions = new ConversionOptions
            {
                PostConversionAction = _appOptions.PostConversionAction,
                PostConversionArchiveFolder = _appOptions.PostConversionArchiveFolder,
                DeleteSourceOnSuccess = _appOptions.DeleteSourceOnSuccess,
            };
        }

        ApplyVisibleOutputProfile(conversionOptions, file);

        ffmpegCommandTemplate ??= EditFfmpegCommandToggle.IsOn
            ? FfmpegCommandBox.Text
            : null;
        if (!string.IsNullOrWhiteSpace(ffmpegCommandTemplate))
        {
            if (!FfmpegCommandTemplate.TryMaterialize(
                    ffmpegCommandTemplate,
                    inputPath,
                    outputPath,
                    out var overrideArguments,
                    out var error))
            {
                throw new InvalidDataException(error);
            }
            conversionOptions.ForceConverter = "ffmpeg";
            conversionOptions.FfmpegArgumentOverride = [.. overrideArguments];
        }

        return ConversionJob.Create(inputPath, outputPath, conversionOptions);
    }

    private void ApplyVisibleOutputProfile(ConversionOptions options, FileItem? file = null)
    {
        options.Quality = _qualityPreset;
        options.UseHardwareAcceleration = HighSpeedToggle.IsOn
            && _appOptions.EnableHardwareAcceleration;
        options.HardwareAccel = _appOptions.DefaultHardwareAcceleration;
        options.AllowHardwareFallback = true;
        options.PreserveMetadata = _appOptions.PreserveMetadataByDefault;
        options.OutputDirectory = _outputDirectory;
        options.Video.Width = _outputWidth;
        options.Video.Height = _outputHeight;
        options.Video.Fps = _outputFrameRate;

        if (file?.HasTrackSelectionOverride == true)
        {
            options.AudioTrackSelection = file.AudioTrackSelection is null
                ? null
                : [.. file.AudioTrackSelection];
            options.SubtitleTrackSelection = file.SubtitleTrackSelection is null
                ? null
                : [.. file.SubtitleTrackSelection];
        }

        if (_audioProfile.Equals("source", StringComparison.OrdinalIgnoreCase))
        {
            options.Audio.Codec = null;
            options.Audio.Bitrate = null;
            options.Audio.Channels = null;
            return;
        }

        var parts = _audioProfile.Split('-', StringSplitOptions.RemoveEmptyEntries);
        options.Audio.Codec = parts.ElementAtOrDefault(0);
        options.Audio.Bitrate = int.TryParse(parts.ElementAtOrDefault(1), out var bitrate) ? bitrate : null;
        options.Audio.Channels = int.TryParse(parts.ElementAtOrDefault(2), out var channels) ? channels : null;
    }

    private async Task RefreshHardwareCapabilitiesAsync()
    {
        var ffmpeg = new FFmpegConverter(_appOptions.ToolsBasePath);
        var executablePath = ffmpeg.ResolveExecutablePath();
        IReadOnlySet<string> encoderNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (executablePath is not null)
        {
            try
            {
                encoderNames = await Task.Run(
                    () => FfmpegEncoderProbe.ProbeEncoderNames(executablePath));
            }
            catch
            {
                // Leave the toggle disabled when probing the configured tool fails.
            }
        }

        DispatcherQueue.TryEnqueue(() => ApplyHardwareCapabilities(executablePath, encoderNames));
    }

    private void ApplyHardwareCapabilities(
        string? executablePath,
        IReadOnlySet<string> encoderNames)
    {
        var requested = HardwareProbeTag(_appOptions.DefaultHardwareAcceleration);
        var supported = executablePath is not null
            && (_appOptions.DefaultHardwareAcceleration == HardwareAcceleration.Auto
                ? FfmpegEncoderProbe.SupportsAcceleration("auto", encoderNames)
                : requested is not null
                    && FfmpegEncoderProbe.SupportsAcceleration(requested, encoderNames));
        var enabled = _appOptions.EnableHardwareAcceleration
            && _appOptions.DefaultHardwareAcceleration != HardwareAcceleration.None
            && supported;

        HighSpeedToggle.IsEnabled = enabled;
        if (!enabled)
            HighSpeedToggle.IsOn = false;

        var explanation = !_appOptions.EnableHardwareAcceleration
            ? "Hardware acceleration is disabled in Settings. Software encoding remains available."
            : _appOptions.DefaultHardwareAcceleration == HardwareAcceleration.None
                ? "Software routing is selected in Settings."
                : executablePath is null
                    ? "Unavailable: the configured FFmpeg executable was not found. Install/download FFmpeg in Settings > Tools."
                    : !supported
                        ? FfmpegEncoderProbe.DescribeUnavailable(
                            requested ?? "auto", true, encoderNames)
                        : "A compatible FFmpeg encoder was probed. Runtime driver/VRAM failures fall back to CPU and are recorded in history.";
        ConverterHardwareCapabilityText.Text = explanation;
        ToolTipService.SetToolTip(HighSpeedToggle, explanation);
        AutomationProperties.SetHelpText(HighSpeedToggle, explanation);
    }

    private static string? HardwareProbeTag(HardwareAcceleration acceleration) => acceleration switch
    {
        HardwareAcceleration.Nvenc or HardwareAcceleration.Cuda => "nvenc",
        HardwareAcceleration.Amf => "amf",
        HardwareAcceleration.Qsv => "qsv",
        HardwareAcceleration.Vaapi => "vaapi",
        HardwareAcceleration.VideoToolbox => "videotoolbox",
        HardwareAcceleration.Vulkan => "vulkan",
        _ => null,
    };

    private void RestoreOutputProfile(IReadOnlyDictionary<string, string?> settings)
    {
        if (settings.TryGetValue("qualityPreset", out var quality))
            SelectTaggedItem(QualityPresetSelector, quality);
        if (settings.TryGetValue("resolution", out var resolution))
            SelectTaggedItem(ResolutionSelector, resolution);
        if (settings.TryGetValue("frameRate", out var frameRate))
            SelectTaggedItem(FrameRateSelector, frameRate);
        if (settings.TryGetValue("audioProfile", out var audio))
            SelectTaggedItem(AudioSelector, audio);
        if (settings.TryGetValue("openOutputAfterConversion", out var openOutput))
            OpenOutputAfterConversionCheckBox.IsChecked = bool.TryParse(openOutput, out var open) && open;
    }

    private static void SelectTaggedItem(ComboBox selector, string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag))
            return;

        var match = selector.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(item.Tag?.ToString(), tag, StringComparison.OrdinalIgnoreCase));
        if (match is not null)
            selector.SelectedItem = match;
    }

    private static ConversionOptions CloneOptions(ConversionOptions options)
    {
        var payload = new ConversionRerunRequest
        {
            SourcePaths = ["clone"],
            OutputFormat = "tmp",
            Options = options,
        };
        var json = ConversionRerunRequestCodec.Serialize(payload);
        return ConversionRerunRequestCodec.TryDeserialize(json, out var clone, out _)
            ? clone!.Options
            : throw new InvalidDataException("Saved conversion options could not be restored.");
    }

    private static ConversionRerunRequest? TryGetRerunRequest(string? json) =>
        ConversionRerunRequestCodec.TryDeserialize(json, out var request, out _)
            ? request
            : null;

    private void EditFfmpegCommandToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (FfmpegCommandBox is null)
            return;

        var appOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>()
            .Value;
        if (EditFfmpegCommandToggle.IsOn && !appOptions.EnableFfmpegCommandEditing)
        {
            EditFfmpegCommandToggle.IsOn = false;
            SetFfmpegCommandStatus(false, "Enable FFmpeg command editing in Settings > Advanced first.");
            return;
        }

        FfmpegCommandBox.IsReadOnly = !EditFfmpegCommandToggle.IsOn;
        if (EditFfmpegCommandToggle.IsOn)
            ValidateCurrentFfmpegCommand();
        else
            UpdateFfmpegCommandPreview();
    }

    private void FfmpegCommandBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (!_updatingFfmpegCommand && EditFfmpegCommandToggle?.IsOn == true)
            ValidateCurrentFfmpegCommand();
    }

    private void UpdateFfmpegCommandPreview()
    {
        if (FfmpegCommandBox is null || FfmpegCommandInfoBar is null)
            return;

        var appOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>()
            .Value;
        EditFfmpegCommandToggle.IsEnabled = appOptions.EnableFfmpegCommandEditing;

        if (_files.Count == 0 || string.IsNullOrWhiteSpace(_selectedFormat))
        {
            SetFfmpegCommandText("");
            SetFfmpegCommandStatus(true, "Add a media file and choose an FFmpeg-compatible output.");
            return;
        }

        var first = _files[0];
        var source = first.Extension.TrimStart('.');
        var ffmpeg = new FFmpegConverter(appOptions.ToolsBasePath);
        if (!ffmpeg.GetOutputFormatsFor(source).Contains(_selectedFormat, StringComparer.OrdinalIgnoreCase))
        {
            SetFfmpegCommandText("");
            EditFfmpegCommandToggle.IsEnabled = false;
            SetFfmpegCommandStatus(true, "The current source/output route does not use FFmpeg.");
            return;
        }

        var job = CreateJob(first.Path, _selectedFormat, BuildOutputPath(first.Path, _selectedFormat), file: first);
        var arguments = ffmpeg.BuildArguments(job, job.Options);
        SetFfmpegCommandText(FfmpegCommandTemplate.Create(arguments, job.InputPath, job.OutputPath));
        var editHint = appOptions.EnableFfmpegCommandEditing
            ? "Turn on Edit before run to customize this argument template."
            : "Preview only. Enable editing in Settings > Advanced.";
        SetFfmpegCommandStatus(true, editHint);
    }

    private void ValidateCurrentFfmpegCommand()
    {
        if (_files.Count == 0 || string.IsNullOrWhiteSpace(_selectedFormat))
        {
            SetFfmpegCommandStatus(false, "Add a media file and select an output before editing.");
            return;
        }

        var first = _files[0];
        var output = BuildOutputPath(first.Path, _selectedFormat);
        var valid = FfmpegCommandTemplate.TryMaterialize(
            FfmpegCommandBox.Text,
            first.Path,
            output,
            out _,
            out var error);
        SetFfmpegCommandStatus(valid, valid ? "Command template is valid and will be applied to every queued job." : error!);
    }

    private bool TryValidateFfmpegOverrideForQueue(out string? error)
    {
        error = null;
        var uiTemplate = EditFfmpegCommandToggle?.IsOn == true
            ? FfmpegCommandBox.Text
            : null;
        var hasSavedTemplate = _files.Any(file =>
            !string.IsNullOrWhiteSpace(TryGetRerunRequest(file.RerunParameters)?.FfmpegCommandTemplate));
        if (string.IsNullOrWhiteSpace(uiTemplate) && !hasSavedTemplate)
            return true;

        var appOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>()
            .Value;
        if (!appOptions.EnableFfmpegCommandEditing)
        {
            error = "FFmpeg command editing is disabled in Settings > Advanced.";
            return false;
        }

        var ffmpeg = new FFmpegConverter(appOptions.ToolsBasePath);
        foreach (var file in _files)
        {
            var template = uiTemplate
                ?? TryGetRerunRequest(file.RerunParameters)?.FfmpegCommandTemplate;
            if (string.IsNullOrWhiteSpace(template))
                continue;

            var source = file.Extension.TrimStart('.');
            if (!ffmpeg.GetOutputFormatsFor(source).Contains(_selectedFormat!, StringComparer.OrdinalIgnoreCase))
            {
                error = $"FFmpeg cannot apply this command to {file.FileName} ({source} -> {_selectedFormat}).";
                return false;
            }

            var output = string.IsNullOrWhiteSpace(file.OutputPath)
                ? BuildOutputPath(file.Path, _selectedFormat!)
                : file.OutputPath!;
            if (!FfmpegCommandTemplate.TryMaterialize(
                    template,
                    file.Path,
                    output,
                    out _,
                    out error))
            {
                return false;
            }
        }

        return true;
    }

    private void SetFfmpegCommandText(string value)
    {
        _updatingFfmpegCommand = true;
        FfmpegCommandBox.Text = value;
        _updatingFfmpegCommand = false;
    }

    private void SetFfmpegCommandStatus(bool valid, string message)
    {
        FfmpegCommandInfoBar.Severity = valid
            ? InfoBarSeverity.Informational
            : InfoBarSeverity.Error;
        FfmpegCommandInfoBar.Title = valid
            ? AppLocalizer.Get("Command preview")
            : AppLocalizer.Get("Command blocked");
        FfmpegCommandInfoBar.Message = message;
    }

    private string BuildOutputPath(string inputPath, string outputFormat)
    {
        var sourceDir = Path.GetDirectoryName(inputPath) ?? ".";
        var dir = _outputDirectory ?? sourceDir;
        var sourceExtension = Path.GetExtension(inputPath).TrimStart('.');
        var normalizedFormat = outputFormat.TrimStart('.');
        var name = Path.GetFileNameWithoutExtension(inputPath);
        if (sourceExtension.Equals(normalizedFormat, StringComparison.OrdinalIgnoreCase))
            name += "_converted";

        return EnsureUniquePath(Path.Combine(dir, $"{name}.{normalizedFormat}"));
    }

    private static List<string> BuildRetryArgs(string outputFormat, string outputPath) =>
    [
        "--format",
        outputFormat.TrimStart('.'),
        "--output",
        outputPath,
    ];

    private string BuildFormatSummary(string sourceExtension)
    {
        var source = sourceExtension.TrimStart('.').ToUpperInvariant();
        return string.IsNullOrEmpty(_selectedFormat)
            ? source
            : $"{source} -> {_selectedFormat.ToUpperInvariant()}";
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
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"")
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Explorer launch is a convenience action; conversion state should remain intact.
        }
    }

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double size = bytes;

        while (size >= 1024 && i < suffixes.Length - 1)
        {
            size /= 1024;
            i++;
        }

        return $"{size:F1} {suffixes[i]}";
    }

    private enum FileCategory
    {
        Unknown,
        Video,
        Audio,
        Image,
        Document,
    }

    private enum QueueSortColumn
    {
        Manual,
        File,
        Format,
        Size,
        Estimate,
        Warnings,
    }

    private sealed record QueuedConversion(
        FileItem File,
        ConversionJob Job,
        string OutputFormat,
        string? OutputDirectory,
        string? FfmpegCommandTemplate);
}

public class FileItem : INotifyPropertyChanged
{
    private bool _isSelected;
    private double _progress;
    private string _statusText = "";
    private string _formatSummary = "";
    private BitmapImage? _thumbnailSource;
    private string _warningSummary = "";
    private string _warningBadgeText = "Ready";
    private int _warningCount;
    private bool _hasBlockingWarning;
    private bool _hasTrackControls;
    private List<int>? _audioTrackSelection;
    private List<int>? _subtitleTrackSelection;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string FileSize { get; set; } = "";
    public long Size { get; set; }
    public bool IsSelected
    {
        get => _isSelected;
        set => SetProperty(ref _isSelected, value);
    }
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string? OutputPath { get; set; }
    public string? ErrorMessage { get; set; }
    public List<string> PersistedArgs { get; set; } = [];
    public string? RerunParameters { get; set; }

    public bool HasTrackControls
    {
        get => _hasTrackControls;
        set
        {
            if (!SetProperty(ref _hasTrackControls, value))
                return;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(TrackButtonVisibility)));
        }
    }

    public Microsoft.UI.Xaml.Visibility TrackButtonVisibility =>
        HasTrackControls
            ? Microsoft.UI.Xaml.Visibility.Visible
            : Microsoft.UI.Xaml.Visibility.Collapsed;

    /// <summary>
    /// Null means the preflight default: preserve every audio stream. A
    /// non-null list is an explicit zero-based per-kind selection, including
    /// an empty list to drop every audio stream.
    /// </summary>
    public List<int>? AudioTrackSelection
    {
        get => _audioTrackSelection;
        set
        {
            if (!SetProperty(ref _audioTrackSelection, value))
                return;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(TrackSelectionLabel)));
        }
    }

    /// <summary>Subtitle equivalent of <see cref="AudioTrackSelection"/>.</summary>
    public List<int>? SubtitleTrackSelection
    {
        get => _subtitleTrackSelection;
        set
        {
            if (!SetProperty(ref _subtitleTrackSelection, value))
                return;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(TrackSelectionLabel)));
        }
    }

    public bool HasTrackSelectionOverride =>
        AudioTrackSelection is not null || SubtitleTrackSelection is not null;

    public string TrackSelectionLabel => HasTrackSelectionOverride ? "Tracks *" : "Tracks";
    public long? EstimatedSizeBytes { get; set; }
    public string EstimatedSizeLabel { get; set; } = "";
    public string EstimatedSizeCaveat { get; set; } = "";
    public Microsoft.UI.Xaml.Visibility HasEstimatedSize =>
        string.IsNullOrEmpty(EstimatedSizeLabel)
            ? Microsoft.UI.Xaml.Visibility.Collapsed
            : Microsoft.UI.Xaml.Visibility.Visible;

    public BitmapImage? ThumbnailSource
    {
        get => _thumbnailSource;
        set
        {
            if (!SetProperty(ref _thumbnailSource, value))
                return;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ThumbnailVisibility)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ThumbnailPlaceholderVisibility)));
        }
    }

    public Microsoft.UI.Xaml.Visibility ThumbnailVisibility =>
        ThumbnailSource is null
            ? Microsoft.UI.Xaml.Visibility.Collapsed
            : Microsoft.UI.Xaml.Visibility.Visible;

    public Microsoft.UI.Xaml.Visibility ThumbnailPlaceholderVisibility =>
        ThumbnailSource is null
            ? Microsoft.UI.Xaml.Visibility.Visible
            : Microsoft.UI.Xaml.Visibility.Collapsed;

    public string WarningSummary
    {
        get => _warningSummary;
        set => SetProperty(ref _warningSummary, value);
    }

    public string WarningBadgeText
    {
        get => _warningBadgeText;
        set => SetProperty(ref _warningBadgeText, value);
    }

    public int WarningCount
    {
        get => _warningCount;
        set
        {
            if (!SetProperty(ref _warningCount, value))
                return;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(WarningVisibility)));
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ReadyVisibility)));
        }
    }

    public bool HasBlockingWarning
    {
        get => _hasBlockingWarning;
        set => SetProperty(ref _hasBlockingWarning, value);
    }

    public Microsoft.UI.Xaml.Visibility WarningVisibility =>
        WarningCount > 0
            ? Microsoft.UI.Xaml.Visibility.Visible
            : Microsoft.UI.Xaml.Visibility.Collapsed;

    public Microsoft.UI.Xaml.Visibility ReadyVisibility =>
        WarningCount == 0
            ? Microsoft.UI.Xaml.Visibility.Visible
            : Microsoft.UI.Xaml.Visibility.Collapsed;

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

    public string FormatSummary
    {
        get => _formatSummary;
        set => SetProperty(ref _formatSummary, value);
    }

    private bool SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return false;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        return true;
    }
}

public class FinishedFileItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
