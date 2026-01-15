using System.Collections.ObjectModel;
using System.Diagnostics;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.Extensions.DependencyInjection;
using WinRT.Interop;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.UI.Views;

public sealed partial class ProgressWindow : Window
{
    private readonly IServiceProvider _serviceProvider;
    private readonly IConversionOrchestrator _orchestrator;
    private readonly ObservableCollection<ConversionItemViewModel> _items = [];
    private readonly List<string> _inputFiles;
    private readonly string _targetFormat;
    private readonly string? _outputDirectory;
    
    private CancellationTokenSource? _cts;
    private bool _isPaused;
    private bool _isCompleted;
    private int _completedCount;
    private int _failedCount;
    private DateTime _startTime;

    public ProgressWindow(
        IServiceProvider serviceProvider,
        IEnumerable<string> inputFiles,
        string targetFormat,
        string? outputDirectory = null)
    {
        _serviceProvider = serviceProvider;
        _orchestrator = serviceProvider.GetRequiredService<IConversionOrchestrator>();
        _inputFiles = inputFiles.ToList();
        _targetFormat = targetFormat;
        _outputDirectory = outputDirectory;

        InitializeComponent();

        // Set window size
        var hwnd = WindowNative.GetWindowHandle(this);
        var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(600, 500));
        appWindow.Title = "Converting - UniversalConverter X";

        FileListView.ItemsSource = _items;

        // Initialize items
        foreach (var file in _inputFiles)
        {
            _items.Add(new ConversionItemViewModel
            {
                FilePath = file,
                FileName = Path.GetFileName(file),
                Status = ConversionItemStatus.Pending,
                StatusIcon = "\uE768", // Clock
                StatusColor = new SolidColorBrush(Colors.Gray),
                StatusMessage = "Waiting...",
                ShowProgress = Visibility.Collapsed,
                ShowStatus = Visibility.Visible
            });
        }

        UpdateOverallProgress();
    }

    public async Task StartConversionAsync()
    {
        _cts = new CancellationTokenSource();
        _startTime = DateTime.Now;
        _isCompleted = false;

        TitleText.Text = $"Converting to {_targetFormat.ToUpperInvariant()}";
        StatusText.Text = "Starting conversions...";

        try
        {
            for (int i = 0; i < _items.Count; i++)
            {
                if (_cts.Token.IsCancellationRequested)
                    break;

                // Handle pause
                while (_isPaused && !_cts.Token.IsCancellationRequested)
                {
                    await Task.Delay(100);
                }

                if (_cts.Token.IsCancellationRequested)
                    break;

                var item = _items[i];
                await ConvertFileAsync(item, _cts.Token);

                UpdateOverallProgress();
            }
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Conversion cancelled";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"Error: {ex.Message}";
        }
        finally
        {
            OnConversionComplete();
        }
    }

    private async Task ConvertFileAsync(ConversionItemViewModel item, CancellationToken cancellationToken)
    {
        item.Status = ConversionItemStatus.Converting;
        item.StatusIcon = "\uE896"; // Sync
        item.StatusColor = new SolidColorBrush(Colors.DodgerBlue);
        item.StatusMessage = "Converting...";
        item.ShowProgress = Visibility.Visible;
        item.IsIndeterminate = true;

        // Determine output path
        var outputDir = _outputDirectory ?? Path.GetDirectoryName(item.FilePath) ?? "";
        var outputName = Path.GetFileNameWithoutExtension(item.FilePath) + "." + _targetFormat;
        var outputPath = Path.Combine(outputDir, outputName);

        // Handle existing files
        var counter = 1;
        while (File.Exists(outputPath))
        {
            outputName = $"{Path.GetFileNameWithoutExtension(item.FilePath)}_{counter}.{_targetFormat}";
            outputPath = Path.Combine(outputDir, outputName);
            counter++;
        }

        var job = new ConversionJob
        {
            InputPath = item.FilePath,
            OutputPath = outputPath,
            Options = new ConversionOptions()
        };

        var startTime = DateTime.Now;

        var progress = new Progress<ConversionProgress>(p =>
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                item.IsIndeterminate = p.Percent <= 0;
                item.Progress = p.Percent;
                item.StatusMessage = p.StatusMessage ?? $"{p.Percent:F0}%";

                if (p.EstimatedTimeRemaining.HasValue)
                {
                    item.TimeInfo = $"ETA: {FormatTimeSpan(p.EstimatedTimeRemaining.Value)}";
                }
            });
        });

        try
        {
            var result = await _orchestrator.ConvertAsync(job, progress, cancellationToken);

            var elapsed = DateTime.Now - startTime;

            if (result.Success)
            {
                item.Status = ConversionItemStatus.Completed;
                item.StatusIcon = "\uE73E"; // Checkmark
                item.StatusColor = new SolidColorBrush(Colors.Green);
                item.StatusMessage = "Completed";
                item.Progress = 100;
                item.TimeInfo = FormatTimeSpan(elapsed);
                
                if (File.Exists(outputPath))
                {
                    var size = new FileInfo(outputPath).Length;
                    item.SizeInfo = FormatFileSize(size);
                }

                _completedCount++;
            }
            else
            {
                item.Status = ConversionItemStatus.Failed;
                item.StatusIcon = "\uE711"; // Error
                item.StatusColor = new SolidColorBrush(Colors.Red);
                item.StatusMessage = result.ErrorMessage ?? "Failed";
                item.ShowProgress = Visibility.Collapsed;

                _failedCount++;
            }
        }
        catch (OperationCanceledException)
        {
            item.Status = ConversionItemStatus.Cancelled;
            item.StatusIcon = "\uE711"; // Error
            item.StatusColor = new SolidColorBrush(Colors.Orange);
            item.StatusMessage = "Cancelled";
            item.ShowProgress = Visibility.Collapsed;
            throw;
        }
        catch (Exception ex)
        {
            item.Status = ConversionItemStatus.Failed;
            item.StatusIcon = "\uE711"; // Error
            item.StatusColor = new SolidColorBrush(Colors.Red);
            item.StatusMessage = ex.Message;
            item.ShowProgress = Visibility.Collapsed;

            _failedCount++;
        }
    }

    private void UpdateOverallProgress()
    {
        var total = _items.Count;
        var processed = _completedCount + _failedCount;
        var percent = total > 0 ? (double)processed / total * 100 : 0;

        OverallProgressText.Text = $"{processed} of {total} files";
        OverallProgressBar.Value = percent;

        if (processed > 0 && processed < total)
        {
            var elapsed = DateTime.Now - _startTime;
            var avgTime = elapsed.TotalSeconds / processed;
            var remaining = TimeSpan.FromSeconds(avgTime * (total - processed));
            EtaText.Text = $"~{FormatTimeSpan(remaining)} remaining";
        }
        else
        {
            EtaText.Text = "";
        }
    }

    private void OnConversionComplete()
    {
        _isCompleted = true;

        var elapsed = DateTime.Now - _startTime;
        
        if (_failedCount == 0)
        {
            TitleText.Text = "Conversion Complete";
            StatusText.Text = $"Successfully converted {_completedCount} file(s) in {FormatTimeSpan(elapsed)}";
        }
        else if (_completedCount == 0)
        {
            TitleText.Text = "Conversion Failed";
            StatusText.Text = $"Failed to convert {_failedCount} file(s)";
        }
        else
        {
            TitleText.Text = "Conversion Complete";
            StatusText.Text = $"Converted {_completedCount} file(s), {_failedCount} failed in {FormatTimeSpan(elapsed)}";
        }

        // Update buttons
        PauseButton.Visibility = Visibility.Collapsed;
        CancelButton.Visibility = Visibility.Collapsed;
        OpenFolderButton.Visibility = Visibility.Visible;
        CloseButton.Visibility = Visibility.Visible;

        OverallProgressBar.Value = 100;
        EtaText.Text = "";

        // Play completion sound
        PlayCompletionSound();

        // Show notification
        ShowCompletionNotification();
    }

    private void Pause_Click(object sender, RoutedEventArgs e)
    {
        _isPaused = !_isPaused;
        PauseButton.Content = _isPaused ? "Resume" : "Pause";
        StatusText.Text = _isPaused ? "Paused" : "Converting...";
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StatusText.Text = "Cancelling...";
    }

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        var outputDir = _outputDirectory ?? 
            (_items.Count > 0 ? Path.GetDirectoryName(_items[0].FilePath) : null);

        if (!string.IsNullOrEmpty(outputDir) && Directory.Exists(outputDir))
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = outputDir,
                UseShellExecute = true
            });
        }
    }

    private void Close_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    private static string FormatTimeSpan(TimeSpan ts)
    {
        if (ts.TotalHours >= 1)
            return $"{(int)ts.TotalHours}:{ts.Minutes:D2}:{ts.Seconds:D2}";
        if (ts.TotalMinutes >= 1)
            return $"{(int)ts.TotalMinutes}:{ts.Seconds:D2}";
        return $"{ts.Seconds}s";
    }

    private static string FormatFileSize(long bytes)
    {
        string[] sizes = ["B", "KB", "MB", "GB", "TB"];
        double len = bytes;
        int order = 0;
        while (len >= 1024 && order < sizes.Length - 1)
        {
            order++;
            len /= 1024;
        }
        return $"{len:0.##} {sizes[order]}";
    }

    private void PlayCompletionSound()
    {
        try
        {
            // Play Windows notification sound
            System.Media.SystemSounds.Asterisk.Play();
        }
        catch { }
    }

    private void ShowCompletionNotification()
    {
        try
        {
            // Show Windows toast notification
            var builder = new Microsoft.Windows.AppNotifications.Builder.AppNotificationBuilder()
                .AddText("Conversion Complete")
                .AddText($"Converted {_completedCount} file(s) to {_targetFormat.ToUpperInvariant()}");

            var notification = builder.BuildNotification();
            Microsoft.Windows.AppNotifications.AppNotificationManager.Default.Show(notification);
        }
        catch { }
    }
}

public enum ConversionItemStatus
{
    Pending,
    Converting,
    Completed,
    Failed,
    Cancelled
}

public class ConversionItemViewModel : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    private string _filePath = "";
    private string _fileName = "";
    private ConversionItemStatus _status;
    private string _statusIcon = "";
    private SolidColorBrush _statusColor = new(Colors.Gray);
    private string _statusMessage = "";
    private double _progress;
    private bool _isIndeterminate;
    private Visibility _showProgress = Visibility.Collapsed;
    private Visibility _showStatus = Visibility.Visible;
    private string _sizeInfo = "";
    private string _timeInfo = "";

    public string FilePath { get => _filePath; set => SetProperty(ref _filePath, value); }
    public string FileName { get => _fileName; set => SetProperty(ref _fileName, value); }
    public ConversionItemStatus Status { get => _status; set => SetProperty(ref _status, value); }
    public string StatusIcon { get => _statusIcon; set => SetProperty(ref _statusIcon, value); }
    public SolidColorBrush StatusColor { get => _statusColor; set => SetProperty(ref _statusColor, value); }
    public string StatusMessage { get => _statusMessage; set => SetProperty(ref _statusMessage, value); }
    public double Progress { get => _progress; set => SetProperty(ref _progress, value); }
    public bool IsIndeterminate { get => _isIndeterminate; set => SetProperty(ref _isIndeterminate, value); }
    public Visibility ShowProgress { get => _showProgress; set => SetProperty(ref _showProgress, value); }
    public Visibility ShowStatus { get => _showStatus; set => SetProperty(ref _showStatus, value); }
    public string SizeInfo { get => _sizeInfo; set => SetProperty(ref _sizeInfo, value); }
    public string TimeInfo { get => _timeInfo; set => SetProperty(ref _timeInfo, value); }
}
