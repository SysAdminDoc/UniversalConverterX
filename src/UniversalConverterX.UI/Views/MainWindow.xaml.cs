using System.Collections.ObjectModel;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views;

public sealed partial class MainWindow : Window
{
    private readonly IConversionOrchestrator _orchestrator;
    private readonly ObservableCollection<FileItem> _files = [];
    private CancellationTokenSource? _cancellationTokenSource;
    private string? _selectedFormat;

    public MainWindow()
    {
        InitializeComponent();
        
        // Initialize orchestrator
        var toolsPath = GetDefaultToolsPath();
        var options = Options.Create(new ConverterXOptions { ToolsBasePath = toolsPath });
        _orchestrator = new ConversionOrchestrator(options);

        FileList.ItemsSource = _files;
        
        // Set window size
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(900, 700));
        
        // Center window
        var displayArea = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(windowId, 
            Microsoft.UI.Windowing.DisplayAreaFallback.Primary);
        var centerX = (displayArea.WorkArea.Width - 900) / 2;
        var centerY = (displayArea.WorkArea.Height - 700) / 2;
        appWindow.Move(new Windows.Graphics.PointInt32(centerX, centerY));
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop to convert";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            var items = await e.DataView.GetStorageItemsAsync();
            foreach (var item in items)
            {
                if (item is StorageFile file)
                {
                    AddFile(file.Path);
                }
            }
        }
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (_files.Count == 0)
        {
            BrowseFiles();
        }
    }

    private void BrowseButton_Click(object sender, RoutedEventArgs e)
    {
        BrowseFiles();
    }

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker();
        picker.ViewMode = PickerViewMode.List;
        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files != null)
        {
            foreach (var file in files)
            {
                AddFile(file.Path);
            }
        }
    }

    private void AddFile(string path)
    {
        if (_files.Any(f => f.Path == path))
            return;

        var fileInfo = new FileInfo(path);
        _files.Add(new FileItem
        {
            Path = path,
            FileName = fileInfo.Name,
            Extension = fileInfo.Extension.TrimStart('.').ToUpperInvariant(),
            FileSize = FormatSize(fileInfo.Length),
            Size = fileInfo.Length
        });

        UpdateUI();
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is FileItem file)
        {
            _files.Remove(file);
            UpdateUI();
        }
    }

    private void ClearAll_Click(object sender, RoutedEventArgs e)
    {
        _files.Clear();
        UpdateUI();
    }

    private void FormatSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (FormatSelector.SelectedItem is ComboBoxItem item)
        {
            _selectedFormat = item.Tag?.ToString();
            UpdateUI();
        }
    }

    private void UpdateUI()
    {
        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        ConvertButton.IsEnabled = hasFiles && !string.IsNullOrEmpty(_selectedFormat);
    }

    private async void ConvertButton_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || string.IsNullOrEmpty(_selectedFormat))
            return;

        _cancellationTokenSource = new CancellationTokenSource();
        ProgressOverlay.Visibility = Visibility.Visible;
        ProgressTitle.Text = "Converting...";
        ConversionProgress.Value = 0;
        ConversionProgress.IsIndeterminate = false;

        var jobs = _files.Select(f => CreateJob(f.Path, _selectedFormat)).ToList();
        var completed = 0;
        var failed = 0;

        try
        {
            foreach (var job in jobs)
            {
                if (_cancellationTokenSource.Token.IsCancellationRequested)
                    break;

                ProgressStatus.Text = $"Converting {job.InputFileName}...";
                ProgressDetails.Text = $"{completed + 1} of {jobs.Count}";

                var progress = new Progress<ConversionProgress>(p =>
                {
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        if (p.IsIndeterminate)
                        {
                            ConversionProgress.IsIndeterminate = true;
                        }
                        else
                        {
                            ConversionProgress.IsIndeterminate = false;
                            var overallProgress = (completed * 100.0 + p.Percent) / jobs.Count;
                            ConversionProgress.Value = overallProgress;
                        }

                        if (p.EstimatedTimeRemaining.HasValue)
                        {
                            ProgressDetails.Text = $"{completed + 1} of {jobs.Count} • ETA: {p.EstimatedTimeRemaining.Value:mm\\:ss}";
                        }
                    });
                });

                var result = await _orchestrator.ConvertAsync(job, progress, _cancellationTokenSource.Token);

                if (result.Success)
                    completed++;
                else
                    failed++;
            }

            // Show completion
            ProgressTitle.Text = failed == 0 ? "Complete!" : "Completed with errors";
            ProgressStatus.Text = $"{completed} succeeded, {failed} failed";
            ConversionProgress.Value = 100;
            ConversionProgress.IsIndeterminate = false;
            CancelButton.Content = "Close";
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

    private void SettingsButton_Click(object sender, RoutedEventArgs e)
    {
        // TODO: Open settings window
    }

    private ConversionJob CreateJob(string inputPath, string outputFormat)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? ".";
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var outputPath = Path.Combine(dir, $"{name}.{outputFormat}");

        return ConversionJob.Create(inputPath, outputPath);
    }

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        int i = 0;
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
}

public class FileItem
{
    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string FileSize { get; set; } = "";
    public long Size { get; set; }
}
