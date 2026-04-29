using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.Options;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
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

    private readonly IConversionOrchestrator _orchestrator;
    private readonly ObservableCollection<FileItem> _files = [];
    private readonly ObservableCollection<FinishedFileItem> _finishedFiles = [];
    private CancellationTokenSource? _cancellationTokenSource;
    private string? _selectedFormat;
    private string? _outputDirectory;

    public ConverterPage()
    {
        InitializeComponent();

        var toolsPath = GetDefaultToolsPath();
        var options = Options.Create(new ConverterXOptions { ToolsBasePath = toolsPath });
        _orchestrator = new ConversionOrchestrator(options);

        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finishedFiles;
        UpdateUI();
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
        UpdateFooterStatus();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateFooterStatus();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path).Take(500))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added == 0
            ? "No new files were added from that folder."
            : $"Added {added} files from {path}.";
        UpdateUI();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path))
            return false;

        var fileInfo = new FileInfo(path);
        if (!fileInfo.Exists)
            return false;

        _files.Add(new FileItem
        {
            Path = path,
            FileName = fileInfo.Name,
            Extension = fileInfo.Extension.TrimStart('.').ToUpperInvariant(),
            FileSize = FormatSize(fileInfo.Length),
            Size = fileInfo.Length,
            FormatSummary = BuildFormatSummary(fileInfo.Extension),
            StatusText = "Queued",
            Progress = 0,
        });

        if (updateUi)
            UpdateUI();

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is FileItem file)
        {
            _files.Remove(file);
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
            UpdateUI();
        }
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

    private void SelectFormat(string format)
    {
        foreach (var item in FormatSelector.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Tag?.ToString(), format, StringComparison.OrdinalIgnoreCase))
            {
                FormatSelector.SelectedItem = item;
                return;
            }
        }
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
        if (_files.Count == 0 || string.IsNullOrEmpty(_selectedFormat))
            return;

        if (_outputDirectory is not null)
            Directory.CreateDirectory(_outputDirectory);

        _cancellationTokenSource = new CancellationTokenSource();
        ConvertButton.IsEnabled = false;
        ProgressOverlay.Visibility = Visibility.Visible;
        ProgressTitle.Text = "Converting...";
        ConversionProgress.Value = 0;
        ConversionProgress.IsIndeterminate = false;
        CancelButton.Content = "Cancel";

        var queuedJobs = _files
            .Select(f => new QueuedConversion(f, CreateJob(f.Path, _selectedFormat)))
            .ToList();
        var completed = 0;
        var failed = 0;
        var cancelled = false;

        try
        {
            foreach (var queued in queuedJobs)
            {
                if (_cancellationTokenSource.Token.IsCancellationRequested)
                {
                    cancelled = true;
                    break;
                }

                queued.File.StatusText = "Converting";
                queued.File.Progress = 0;
                ProgressStatus.Text = $"Converting {queued.Job.InputFileName}...";
                ProgressDetails.Text = $"{completed + failed + 1} of {queuedJobs.Count}";

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

                var result = await _orchestrator.ConvertAsync(queued.Job, progress, _cancellationTokenSource.Token);
                AddFinishedItem(result);

                if (result.Success)
                {
                    completed++;
                    queued.File.Progress = 100;
                    queued.File.StatusText = "Done";
                }
                else
                {
                    failed++;
                    queued.File.StatusText = "Failed";
                }
            }

            ProgressTitle.Text = cancelled
                ? "Cancelled"
                : failed == 0 ? "Complete" : "Completed with errors";
            ProgressStatus.Text = $"{completed} succeeded, {failed} failed";
            ConversionProgress.Value = cancelled ? ConversionProgress.Value : 100;
            ConversionProgress.IsIndeterminate = false;
            CancelButton.Content = "Close";
            QueuePivot.SelectedIndex = _finishedFiles.Count > 0 ? 1 : 0;
        }
        catch (OperationCanceledException)
        {
            ProgressTitle.Text = "Cancelled";
            ProgressStatus.Text = $"{completed} completed before cancellation";
            CancelButton.Content = "Close";
        }
        finally
        {
            _cancellationTokenSource?.Dispose();
            _cancellationTokenSource = null;
            UpdateUI();
        }
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
    }

    private ConversionJob CreateJob(string inputPath, string outputFormat)
    {
        var sourceDir = Path.GetDirectoryName(inputPath) ?? ".";
        var dir = _outputDirectory ?? sourceDir;
        var sourceExtension = Path.GetExtension(inputPath).TrimStart('.');
        var normalizedFormat = outputFormat.TrimStart('.');
        var name = Path.GetFileNameWithoutExtension(inputPath);
        if (sourceExtension.Equals(normalizedFormat, StringComparison.OrdinalIgnoreCase))
            name += "_converted";

        var outputPath = EnsureUniquePath(Path.Combine(dir, $"{name}.{normalizedFormat}"));
        return ConversionJob.Create(inputPath, outputPath);
    }

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
            Process.Start(new ProcessStartInfo("explorer.exe", folder)
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

    private static string GetDefaultToolsPath()
    {
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX", "tools"),
        };

        foreach (var loc in locations)
        {
            if (Directory.Exists(loc))
                return loc;
        }

        return locations[0];
    }

    private enum FileCategory
    {
        Unknown,
        Video,
        Audio,
        Image,
        Document,
    }

    private sealed record QueuedConversion(FileItem File, ConversionJob Job);
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
