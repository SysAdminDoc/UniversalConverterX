using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.UI.ViewModels;

public partial class MainViewModel : ObservableObject
{
    private readonly IConversionOrchestrator _orchestrator;
    private CancellationTokenSource? _cancellationTokenSource;

    public MainViewModel(IConversionOrchestrator orchestrator)
    {
        _orchestrator = orchestrator;
        Files = [];
        AvailableFormats = [];
    }

    [ObservableProperty]
    private ObservableCollection<FileItemViewModel> _files;

    [ObservableProperty]
    private ObservableCollection<string> _availableFormats;

    [ObservableProperty]
    private string? _selectedFormat;

    [ObservableProperty]
    private bool _isConverting;

    [ObservableProperty]
    private double _overallProgress;

    [ObservableProperty]
    private string? _currentFileName;

    [ObservableProperty]
    private string? _statusMessage;

    [ObservableProperty]
    private int _completedCount;

    [ObservableProperty]
    private int _failedCount;

    public bool CanConvert => Files.Count > 0 && !string.IsNullOrEmpty(SelectedFormat) && !IsConverting;

    [RelayCommand]
    public void AddFiles(IEnumerable<string> paths)
    {
        foreach (var path in paths)
        {
            if (Files.Any(f => f.Path == path))
                continue;

            var fileInfo = new FileInfo(path);
            Files.Add(new FileItemViewModel
            {
                Path = path,
                FileName = fileInfo.Name,
                Extension = fileInfo.Extension.TrimStart('.').ToUpperInvariant(),
                FileSize = FormatSize(fileInfo.Length),
                Size = fileInfo.Length
            });
        }

        UpdateAvailableFormats();
        OnPropertyChanged(nameof(CanConvert));
    }

    [RelayCommand]
    public void RemoveFile(FileItemViewModel file)
    {
        Files.Remove(file);
        UpdateAvailableFormats();
        OnPropertyChanged(nameof(CanConvert));
    }

    [RelayCommand]
    public void ClearFiles()
    {
        Files.Clear();
        AvailableFormats.Clear();
        SelectedFormat = null;
        OnPropertyChanged(nameof(CanConvert));
    }

    [RelayCommand]
    public async Task ConvertAsync()
    {
        if (Files.Count == 0 || string.IsNullOrEmpty(SelectedFormat))
            return;

        IsConverting = true;
        CompletedCount = 0;
        FailedCount = 0;
        OverallProgress = 0;
        _cancellationTokenSource = new CancellationTokenSource();

        try
        {
            var jobs = Files.Select(f => CreateJob(f.Path, SelectedFormat)).ToList();

            foreach (var job in jobs)
            {
                if (_cancellationTokenSource.Token.IsCancellationRequested)
                    break;

                CurrentFileName = job.InputFileName;
                StatusMessage = $"Converting {CompletedCount + 1} of {jobs.Count}";

                var progress = new Progress<ConversionProgress>(p =>
                {
                    var itemProgress = p.IsIndeterminate ? 50 : p.Percent;
                    OverallProgress = (CompletedCount * 100.0 + itemProgress) / jobs.Count;
                });

                var result = await _orchestrator.ConvertAsync(job, progress, _cancellationTokenSource.Token);

                if (result.Success)
                    CompletedCount++;
                else
                    FailedCount++;
            }

            StatusMessage = FailedCount == 0
                ? $"Completed! {CompletedCount} files converted."
                : $"Completed with {FailedCount} errors. {CompletedCount} succeeded.";
            
            OverallProgress = 100;
        }
        catch (OperationCanceledException)
        {
            StatusMessage = $"Cancelled. {CompletedCount} files completed.";
        }
        finally
        {
            IsConverting = false;
            CurrentFileName = null;
            _cancellationTokenSource?.Dispose();
            _cancellationTokenSource = null;
            OnPropertyChanged(nameof(CanConvert));
        }
    }

    [RelayCommand]
    public void CancelConversion()
    {
        _cancellationTokenSource?.Cancel();
    }

    partial void OnSelectedFormatChanged(string? value)
    {
        OnPropertyChanged(nameof(CanConvert));
    }

    private void UpdateAvailableFormats()
    {
        AvailableFormats.Clear();

        if (Files.Count == 0)
            return;

        // Get common formats for all files
        HashSet<string>? commonFormats = null;

        foreach (var file in Files)
        {
            var formats = _orchestrator.GetOutputFormatsFor(file.Path);
            
            if (commonFormats == null)
                commonFormats = new HashSet<string>(formats);
            else
                commonFormats.IntersectWith(formats);
        }

        if (commonFormats != null)
        {
            foreach (var format in commonFormats.OrderBy(f => f))
            {
                AvailableFormats.Add(format);
            }
        }
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
}

public partial class FileItemViewModel : ObservableObject
{
    [ObservableProperty]
    private string _path = "";

    [ObservableProperty]
    private string _fileName = "";

    [ObservableProperty]
    private string _extension = "";

    [ObservableProperty]
    private string _fileSize = "";

    [ObservableProperty]
    private long _size;

    [ObservableProperty]
    private ConversionStatus _status = ConversionStatus.Pending;

    [ObservableProperty]
    private double _progress;

    [ObservableProperty]
    private string? _errorMessage;
}
