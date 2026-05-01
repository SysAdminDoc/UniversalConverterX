using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.UI.Services;

namespace UniversalConverterX.UI.ViewModels;

public partial class ConversionViewModel : ObservableObject
{
    private readonly IConversionOrchestrator _orchestrator;
    private ConversionJob? _currentJob;
    private double _progress;
    private string? _statusMessage;
    private TimeSpan? _estimatedTimeRemaining;
    private bool _isConverting;
    private ConversionResult? _result;

    public ConversionViewModel(IConversionOrchestrator orchestrator)
    {
        _orchestrator = orchestrator;
    }

    public ConversionJob? CurrentJob
    {
        get => _currentJob;
        set => SetProperty(ref _currentJob, value);
    }

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public string? StatusMessage
    {
        get => _statusMessage;
        set => SetProperty(ref _statusMessage, value);
    }

    public TimeSpan? EstimatedTimeRemaining
    {
        get => _estimatedTimeRemaining;
        set => SetProperty(ref _estimatedTimeRemaining, value);
    }

    public bool IsConverting
    {
        get => _isConverting;
        set => SetProperty(ref _isConverting, value);
    }

    public ConversionResult? Result
    {
        get => _result;
        set => SetProperty(ref _result, value);
    }
}

public partial class SettingsViewModel : ObservableObject
{
    private readonly ISettingsService _settingsService;
    private readonly IToolManager _toolManager;
    private string _toolsPath = "";
    private int _maxParallelConversions = 4;
    private bool _enableHardwareAcceleration = true;
    private bool _preserveMetadata = true;
    private string _defaultQuality = "High";
    private bool _overwriteExisting;
    private string _outputDirectory = "";
    private bool _useCustomOutputDirectory;

    public SettingsViewModel(ISettingsService settingsService, IToolManager toolManager)
    {
        _settingsService = settingsService;
        _toolManager = toolManager;
        LoadSettings();
    }

    public string ToolsPath
    {
        get => _toolsPath;
        set => SetProperty(ref _toolsPath, value);
    }

    public int MaxParallelConversions
    {
        get => _maxParallelConversions;
        set => SetProperty(ref _maxParallelConversions, value);
    }

    public bool EnableHardwareAcceleration
    {
        get => _enableHardwareAcceleration;
        set => SetProperty(ref _enableHardwareAcceleration, value);
    }

    public bool PreserveMetadata
    {
        get => _preserveMetadata;
        set => SetProperty(ref _preserveMetadata, value);
    }

    public string DefaultQuality
    {
        get => _defaultQuality;
        set => SetProperty(ref _defaultQuality, value);
    }

    public bool OverwriteExisting
    {
        get => _overwriteExisting;
        set => SetProperty(ref _overwriteExisting, value);
    }

    public string OutputDirectory
    {
        get => _outputDirectory;
        set => SetProperty(ref _outputDirectory, value);
    }

    public bool UseCustomOutputDirectory
    {
        get => _useCustomOutputDirectory;
        set => SetProperty(ref _useCustomOutputDirectory, value);
    }

    public string[] QualityOptions { get; } = ["Lowest", "Low", "Medium", "High", "Highest", "Lossless"];

    private void LoadSettings()
    {
        ToolsPath = _settingsService.Get("ToolsPath", GetDefaultToolsPath()) ?? GetDefaultToolsPath();
        MaxParallelConversions = _settingsService.Get("MaxParallelConversions", 4);
        EnableHardwareAcceleration = _settingsService.Get("EnableHardwareAcceleration", true);
        PreserveMetadata = _settingsService.Get("PreserveMetadata", true);
        DefaultQuality = _settingsService.Get("DefaultQuality", "High") ?? "High";
        OverwriteExisting = _settingsService.Get("OverwriteExisting", false);
        OutputDirectory = _settingsService.Get("OutputDirectory", "") ?? "";
        UseCustomOutputDirectory = _settingsService.Get("UseCustomOutputDirectory", false);
    }

    [RelayCommand]
    public void Save()
    {
        _settingsService.Set("ToolsPath", ToolsPath);
        _settingsService.Set("MaxParallelConversions", MaxParallelConversions);
        _settingsService.Set("EnableHardwareAcceleration", EnableHardwareAcceleration);
        _settingsService.Set("PreserveMetadata", PreserveMetadata);
        _settingsService.Set("DefaultQuality", DefaultQuality);
        _settingsService.Set("OverwriteExisting", OverwriteExisting);
        _settingsService.Set("OutputDirectory", OutputDirectory);
        _settingsService.Set("UseCustomOutputDirectory", UseCustomOutputDirectory);
        _settingsService.Save();
    }

    [RelayCommand]
    public void Reset()
    {
        ToolsPath = GetDefaultToolsPath();
        MaxParallelConversions = 4;
        EnableHardwareAcceleration = true;
        PreserveMetadata = true;
        DefaultQuality = "High";
        OverwriteExisting = false;
        OutputDirectory = "";
        UseCustomOutputDirectory = false;
    }

    private static string GetDefaultToolsPath()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "tools");
    }
}

public partial class ProgressViewModel : ObservableObject
{
    private string _title = "Converting...";
    private string _fileName = "";
    private double _progress;
    private bool _isIndeterminate;
    private string _statusMessage = "";
    private string _details = "";
    private int _completedCount;
    private int _totalCount;
    private int _failedCount;
    private TimeSpan? _estimatedTimeRemaining;
    private bool _isComplete;
    private bool _isCancelled;

    public string Title
    {
        get => _title;
        set => SetProperty(ref _title, value);
    }

    public string FileName
    {
        get => _fileName;
        set => SetProperty(ref _fileName, value);
    }

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public bool IsIndeterminate
    {
        get => _isIndeterminate;
        set => SetProperty(ref _isIndeterminate, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        set => SetProperty(ref _statusMessage, value);
    }

    public string Details
    {
        get => _details;
        set => SetProperty(ref _details, value);
    }

    public int CompletedCount
    {
        get => _completedCount;
        set => SetProperty(ref _completedCount, value);
    }

    public int TotalCount
    {
        get => _totalCount;
        set => SetProperty(ref _totalCount, value);
    }

    public int FailedCount
    {
        get => _failedCount;
        set => SetProperty(ref _failedCount, value);
    }

    public TimeSpan? EstimatedTimeRemaining
    {
        get => _estimatedTimeRemaining;
        set => SetProperty(ref _estimatedTimeRemaining, value);
    }

    public bool IsComplete
    {
        get => _isComplete;
        set => SetProperty(ref _isComplete, value);
    }

    public bool IsCancelled
    {
        get => _isCancelled;
        set => SetProperty(ref _isCancelled, value);
    }

    public void UpdateProgress(ConversionProgress conversionProgress, int completed, int total)
    {
        CompletedCount = completed;
        TotalCount = total;

        if (conversionProgress.IsIndeterminate)
        {
            IsIndeterminate = true;
            StatusMessage = conversionProgress.StatusMessage ?? "Processing...";
        }
        else
        {
            IsIndeterminate = false;
            Progress = (completed * 100.0 + conversionProgress.Percent) / total;
            EstimatedTimeRemaining = conversionProgress.EstimatedTimeRemaining;
        }

        Details = $"{completed + 1} of {total}";
        if (EstimatedTimeRemaining.HasValue)
        {
            Details += $" • ETA: {EstimatedTimeRemaining.Value:mm\\:ss}";
        }
    }

    public void MarkComplete(int succeeded, int failed)
    {
        IsComplete = true;
        CompletedCount = succeeded;
        FailedCount = failed;
        Progress = 100;
        IsIndeterminate = false;

        Title = failed == 0 ? "Complete!" : "Completed with errors";
        StatusMessage = failed == 0
            ? $"{succeeded} file(s) converted successfully"
            : $"{succeeded} succeeded, {failed} failed";
    }

    public void MarkCancelled(int completed)
    {
        IsCancelled = true;
        CompletedCount = completed;
        Title = "Cancelled";
        StatusMessage = $"{completed} file(s) completed before cancellation";
    }
}
