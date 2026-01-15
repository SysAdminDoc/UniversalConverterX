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

    public ConversionViewModel(IConversionOrchestrator orchestrator)
    {
        _orchestrator = orchestrator;
    }

    [ObservableProperty]
    private ConversionJob? _currentJob;

    [ObservableProperty]
    private double _progress;

    [ObservableProperty]
    private string? _statusMessage;

    [ObservableProperty]
    private TimeSpan? _estimatedTimeRemaining;

    [ObservableProperty]
    private bool _isConverting;

    [ObservableProperty]
    private ConversionResult? _result;
}

public partial class SettingsViewModel : ObservableObject
{
    private readonly ISettingsService _settingsService;
    private readonly IToolManager _toolManager;

    public SettingsViewModel(ISettingsService settingsService, IToolManager toolManager)
    {
        _settingsService = settingsService;
        _toolManager = toolManager;
        LoadSettings();
    }

    [ObservableProperty]
    private string _toolsPath = "";

    [ObservableProperty]
    private int _maxParallelConversions = 4;

    [ObservableProperty]
    private bool _enableHardwareAcceleration = true;

    [ObservableProperty]
    private bool _preserveMetadata = true;

    [ObservableProperty]
    private string _defaultQuality = "High";

    [ObservableProperty]
    private bool _overwriteExisting;

    [ObservableProperty]
    private string _outputDirectory = "";

    [ObservableProperty]
    private bool _useCustomOutputDirectory;

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
    [ObservableProperty]
    private string _title = "Converting...";

    [ObservableProperty]
    private string _fileName = "";

    [ObservableProperty]
    private double _progress;

    [ObservableProperty]
    private bool _isIndeterminate;

    [ObservableProperty]
    private string _statusMessage = "";

    [ObservableProperty]
    private string _details = "";

    [ObservableProperty]
    private int _completedCount;

    [ObservableProperty]
    private int _totalCount;

    [ObservableProperty]
    private int _failedCount;

    [ObservableProperty]
    private TimeSpan? _estimatedTimeRemaining;

    [ObservableProperty]
    private bool _isComplete;

    [ObservableProperty]
    private bool _isCancelled;

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
