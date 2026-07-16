using System.Collections.ObjectModel;
using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
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
    private readonly IBatchQueueStore _queueStore;
    private readonly IHistoryService _history;
    private readonly IPostQueueActionService _postQueueActions;
    private readonly ObservableCollection<FileItem> _files = [];
    private readonly ObservableCollection<FinishedFileItem> _finishedFiles = [];
    private CancellationTokenSource? _cancellationTokenSource;
    private string? _selectedFormat;
    private string? _outputDirectory;
    private bool _restoringQueue;
    private bool _updatingFfmpegCommand;

    public ConverterPage()
    {
        InitializeComponent();
        // Resolve the singleton orchestrator from DI rather than newing up a
        // private one — every prior page navigation built a fresh registry of
        // 13 converter strategies for no reason.
        _orchestrator = App.Services.GetRequiredService<IConversionOrchestrator>();
        _queueStore = App.Services.GetRequiredService<IBatchQueueStore>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _postQueueActions = App.Services.GetRequiredService<IPostQueueActionService>();

        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finishedFiles;
        RestorePersistedQueue();
        UpdateUI();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is ConversionRerunRequest request)
            ApplyRerunRequest(request);
    }

    private void ApplyRerunRequest(ConversionRerunRequest request)
    {
        if (!PathSafety.TryNormalizeExtension(request.OutputFormat, out var outputFormat))
        {
            StatusText.Text = "The saved re-run output format is invalid.";
            return;
        }

        if (_files.Count > 0
            && ((string.IsNullOrWhiteSpace(_selectedFormat)
                 || !_selectedFormat.Equals(outputFormat, StringComparison.OrdinalIgnoreCase))
                || !PathsEqual(_outputDirectory, request.OutputDirectory)))
        {
            StatusText.Text = "The current queue uses different settings and was preserved. Finish or clear it before restoring this history row.";
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
                StatusText.Text = $"The Converter cannot restore the saved {outputFormat.ToUpperInvariant()} route.";
                return;
            }

            var restoredItem = new ComboBoxItem
            {
                Content = $"{outputFormat.ToUpperInvariant()} - Restored",
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
            item.OutputPath = perFileRequest.OutputPath;
            item.StatusText = "Restored from history";
            restored++;
        }

        PersistQueue();
        UpdateUI();
        StatusText.Text = restored > 0
            ? $"Restored {restored} file(s) with the saved {outputFormat.ToUpperInvariant()} settings."
            : "The saved source file is no longer available.";
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
        e.DragUIOverride.Caption = "Drop into conversion queue";
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

    private void BrowseButton_Click(object sender, RoutedEventArgs e) => BrowseFiles();

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
        PersistQueue();
        UpdateFooterStatus();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        PersistQueue();
        UpdateFooterStatus();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = $"Folder not found: {path}";
            return;
        }

        IEnumerable<string> entries;
        try { entries = Directory.EnumerateFiles(path); }
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
        var examined = 0;
        var truncated = false;
        foreach (var file in entries)
        {
            examined++;
            if (added >= FolderAddCap) { truncated = true; break; }
            if (AddFile(file, updateUi: false))
                added++;
        }

        if (added == 0)
            StatusText.Text = "No new files were added from that folder.";
        else if (truncated)
            StatusText.Text = $"Added {added} files from {path} (capped at {FolderAddCap} — pick a smaller folder for the rest).";
        else
            StatusText.Text = $"Added {added} files from {path}.";
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

        var estimate = OutputSizeEstimator.ForLosslessCopy(size);
        _files.Add(new FileItem
        {
            Path = path,
            FileName = fileInfo.Name,
            Extension = fileInfo.Extension.TrimStart('.').ToUpperInvariant(),
            FileSize = FormatSize(size),
            Size = size,
            FormatSummary = BuildFormatSummary(fileInfo.Extension),
            StatusText = "Queued",
            Progress = 0,
            EstimatedSizeLabel = $"→ {estimate.DisplayLabel}",
            EstimatedSizeCaveat = estimate.Caveat ?? "Based on lossless copy estimate",
        });

        if (updateUi)
        {
            PersistQueue();
            UpdateUI();
        }

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is FileItem file)
        {
            _files.Remove(file);
            PersistQueue();
            UpdateUI();
        }
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
            }

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
                    "Running" or "Converting" => "Interrupted - ready to retry",
                    "Failed" => "Failed - ready to retry",
                    "Cancelled" => "Cancelled - ready to retry",
                    _ => "Queued",
                };

                _files.Add(new FileItem
                {
                    Id = string.IsNullOrWhiteSpace(job.Id) ? Guid.NewGuid().ToString("N") : job.Id,
                    Path = job.SourcePath,
                    FileName = info.Name,
                    Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
                    FileSize = FormatSize(info.Length),
                    Size = info.Length,
                    FormatSummary = BuildFormatSummary(info.Extension),
                    StatusText = status,
                    Progress = 0,
                    OutputPath = job.OutputPath,
                    ErrorMessage = job.ErrorMessage,
                    PersistedArgs = [.. job.Args],
                });
                restored++;
            }

            if (restored > 0)
                StatusText.Text = $"Restored {restored} queued conversion(s) from the previous session.";
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
                Status = NormalizePersistedStatus(f.StatusText),
                ErrorMessage = f.ErrorMessage,
            })
            .ToList();

        if (activeJobs.Count == 0)
        {
            _queueStore.Clear(QueueKey);
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
            },
            Jobs = activeJobs,
        });
    }

    private static string NormalizePersistedStatus(string status)
    {
        if (status.StartsWith("Interrupted", StringComparison.OrdinalIgnoreCase))
            return "Interrupted";
        if (status.StartsWith("Failed", StringComparison.OrdinalIgnoreCase))
            return "Failed";
        if (status.StartsWith("Cancelled", StringComparison.OrdinalIgnoreCase))
            return "Cancelled";
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
        StatusText.Text = $"Applied the recommended {recommended.ToUpperInvariant()} output profile.";
    }

    private void ProfileShortcut_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string format })
        {
            SelectFormat(format);
            StatusText.Text = $"Output profile set to {format.ToUpperInvariant()}.";
        }
    }

    private void UpdateUI()
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finishedFiles.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        ConvertButton.IsEnabled = hasFiles && !string.IsNullOrEmpty(_selectedFormat) && _cancellationTokenSource is null;
        SmartMatchButton.IsEnabled = hasFiles && RecommendFormatTag() is not null;
        QueueSummaryText.Text = $"{_files.Count} queued / {_finishedFiles.Count} finished";
        RecommendationText.Text = BuildRecommendationText();
        UpdateFooterStatus();
        if (EditFfmpegCommandToggle?.IsOn != true)
            UpdateFfmpegCommandPreview();
    }

    private void UpdateFooterStatus()
    {
        var output = _outputDirectory ?? "same folder as each source";
        FooterStatusText.Text = $"Output: {output}";

        if (_files.Count == 0)
            StatusText.Text = "Add files to start a conversion queue.";
        else if (string.IsNullOrEmpty(_selectedFormat))
            StatusText.Text = "Choose an output profile before starting.";
        else
            StatusText.Text = $"Ready to convert {_files.Count} files to {_selectedFormat.ToUpperInvariant()}.";
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
                StatusText.Text = $"Output folder unavailable: {ex.Message}";
                return;
            }
        }

        _cancellationTokenSource = new CancellationTokenSource();
        ConvertButton.IsEnabled = false;
        ProgressOverlay.Visibility = Visibility.Visible;
        ProgressTitle.Text = "Converting...";
        ConversionProgress.Value = 0;
        ConversionProgress.IsIndeterminate = false;
        CancelButton.Content = "Cancel";

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
                        commandTemplate),
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
                        ProgressStatus.Text = $"Converting {queued.Job.InputFileName}...";
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
                                ProgressDetails.Text = $"{completed + failed + 1} of {queuedJobs.Count} - ETA {p.EstimatedTimeRemaining.Value:mm\\:ss}";
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
                        Message = "Conversion cancelled by user.",
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
                CancelButton.Content = "Close";
                QueuePivot.SelectedIndex = _finishedFiles.Count > 0 ? 1 : 0;
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
        ProgressDetails.Text = $"{current + 1} of {total}";
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
            CancelButton.Content = "Cancel";
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
            });
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"History logging failed: {ex}");
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
        string? ffmpegCommandTemplate = null)
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
            var appOptions = App.Services
                .GetRequiredService<Microsoft.Extensions.Options.IOptions<UniversalConverterX.Core.Configuration.ConverterXOptions>>()
                .Value;
            conversionOptions = new ConversionOptions
            {
                PostConversionAction = appOptions.PostConversionAction,
                PostConversionArchiveFolder = appOptions.PostConversionArchiveFolder,
                DeleteSourceOnSuccess = appOptions.DeleteSourceOnSuccess,
            };
        }

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

        var job = CreateJob(first.Path, _selectedFormat, BuildOutputPath(first.Path, _selectedFormat));
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
        FfmpegCommandInfoBar.Title = valid ? "Command preview" : "Command blocked";
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

    private sealed record QueuedConversion(
        FileItem File,
        ConversionJob Job,
        string OutputFormat,
        string? OutputDirectory,
        string? FfmpegCommandTemplate);
}

public class FileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _formatSummary = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string FileSize { get; set; } = "";
    public long Size { get; set; }
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string? OutputPath { get; set; }
    public string? ErrorMessage { get; set; }
    public List<string> PersistedArgs { get; set; } = [];
    public string? RerunParameters { get; set; }
    public string EstimatedSizeLabel { get; set; } = "";
    public string EstimatedSizeCaveat { get; set; } = "";
    public Microsoft.UI.Xaml.Visibility HasEstimatedSize =>
        string.IsNullOrEmpty(EstimatedSizeLabel)
            ? Microsoft.UI.Xaml.Visibility.Collapsed
            : Microsoft.UI.Xaml.Visibility.Visible;

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

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
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
