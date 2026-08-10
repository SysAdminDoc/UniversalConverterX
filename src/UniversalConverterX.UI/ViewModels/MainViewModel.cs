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
    private ObservableCollection<FileItemViewModel> _files = [];
    private ObservableCollection<string> _availableFormats = [];
    private string? _selectedFormat;
    private bool _isConverting;
    private double _overallProgress;
    private string? _currentFileName;
    private string? _statusMessage;
    private int _completedCount;
    private int _failedCount;

    public MainViewModel(IConversionOrchestrator orchestrator)
    {
        _orchestrator = orchestrator;
    }

    public ObservableCollection<FileItemViewModel> Files
    {
        get => _files;
        set => SetProperty(ref _files, value);
    }

    public ObservableCollection<string> AvailableFormats
    {
        get => _availableFormats;
        set => SetProperty(ref _availableFormats, value);
    }

    public string? SelectedFormat
    {
        get => _selectedFormat;
        set
        {
            if (SetProperty(ref _selectedFormat, value))
                OnPropertyChanged(nameof(CanConvert));
        }
    }

    public bool IsConverting
    {
        get => _isConverting;
        set
        {
            if (SetProperty(ref _isConverting, value))
                OnPropertyChanged(nameof(CanConvert));
        }
    }

    public double OverallProgress
    {
        get => _overallProgress;
        set => SetProperty(ref _overallProgress, value);
    }

    public string? CurrentFileName
    {
        get => _currentFileName;
        set => SetProperty(ref _currentFileName, value);
    }

    public string? StatusMessage
    {
        get => _statusMessage;
        set => SetProperty(ref _statusMessage, value);
    }

    public int CompletedCount
    {
        get => _completedCount;
        set => SetProperty(ref _completedCount, value);
    }

    public int FailedCount
    {
        get => _failedCount;
        set => SetProperty(ref _failedCount, value);
    }

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
                StatusMessage = AppLocalizer.Format($"Converting {CompletedCount + 1} of {jobs.Count}");

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
                ? AppLocalizer.Format($"Completed! {CompletedCount} files converted.")
                : AppLocalizer.Format($"Completed with {FailedCount} errors. {CompletedCount} succeeded.");
            
            OverallProgress = 100;
        }
        catch (OperationCanceledException)
        {
            StatusMessage = AppLocalizer.Format($"Cancelled. {CompletedCount} files completed.");
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
    private string _path = "";
    private string _fileName = "";
    private string _extension = "";
    private string _fileSize = "";
    private long _size;
    private ConversionStatus _status = ConversionStatus.Pending;
    private double _progress;
    private string? _errorMessage;

    public string Path
    {
        get => _path;
        set => SetProperty(ref _path, value);
    }

    public string FileName
    {
        get => _fileName;
        set => SetProperty(ref _fileName, value);
    }

    public string Extension
    {
        get => _extension;
        set => SetProperty(ref _extension, value);
    }

    public string FileSize
    {
        get => _fileSize;
        set => SetProperty(ref _fileSize, value);
    }

    public long Size
    {
        get => _size;
        set => SetProperty(ref _size, value);
    }

    public ConversionStatus Status
    {
        get => _status;
        set => SetProperty(ref _status, value);
    }

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public string? ErrorMessage
    {
        get => _errorMessage;
        set => SetProperty(ref _errorMessage, value);
    }
}
