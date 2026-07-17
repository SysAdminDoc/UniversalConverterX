using CommunityToolkit.Mvvm.ComponentModel;

namespace UniversalConverterX.Core.ViewModels;

public sealed class ColorizeWorkflowViewModel : ObservableObject
{
    private static readonly HashSet<string> ImageExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff" };
    private static readonly HashSet<string> VideoExtensions =
        new(StringComparer.OrdinalIgnoreCase) { ".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".ts" };

    private string? _sourcePath;
    private string? _outputPath;
    private bool _modelReady;
    private bool _isBusy;

    public string? SourcePath
    {
        get => _sourcePath;
        private set
        {
            if (SetProperty(ref _sourcePath, value))
                OnPropertyChanged(nameof(CanColorize));
        }
    }
    public string? OutputPath { get => _outputPath; set => SetProperty(ref _outputPath, value); }
    public bool IsVideo { get; private set; }
    public bool ModelReady
    {
        get => _modelReady;
        set
        {
            if (SetProperty(ref _modelReady, value))
                OnPropertyChanged(nameof(CanColorize));
        }
    }
    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            if (SetProperty(ref _isBusy, value))
                OnPropertyChanged(nameof(CanColorize));
        }
    }
    public bool CanColorize => !IsBusy && ModelReady && SourcePath is not null;

    public bool TryLoadSource(string path)
    {
        var extension = Path.GetExtension(path);
        if (!ImageExtensions.Contains(extension) && !VideoExtensions.Contains(extension))
            return false;
        SourcePath = path;
        OutputPath = null;
        IsVideo = VideoExtensions.Contains(extension);
        OnPropertyChanged(nameof(IsVideo));
        OnPropertyChanged(nameof(SourceStatus));
        return true;
    }

    public string SourceStatus => SourcePath is null ? "Choose a source." : IsVideo
        ? $"{Path.GetFileName(SourcePath)} · video — colourises frame-by-frame on the CPU (slow for long clips)."
        : $"{Path.GetFileName(SourcePath)} · image.";

    public string DefaultOutputPath()
    {
        if (SourcePath is null)
            throw new InvalidOperationException("A supported source must be loaded first.");
        var directory = Path.GetDirectoryName(SourcePath) ?? Path.GetTempPath();
        var stem = Path.GetFileNameWithoutExtension(SourcePath);
        return Path.Combine(directory, $"{stem}_color{(IsVideo ? ".mp4" : ".png")}");
    }

    public WorkflowInvocation BuildInvocation()
    {
        if (SourcePath is null || !ModelReady)
            throw new InvalidOperationException("A source and verified model are required.");
        var output = OutputPath ?? DefaultOutputPath();
        return new WorkflowInvocation(
            "colorize",
            [IsVideo ? "video" : "image", "--input", SourcePath, "--output", output],
            output);
    }

    public static string MapError(string? errorCode, string? errorMessage) =>
        errorCode == "cancelled"
            ? "Colourisation cancelled."
            : $"Colourisation failed: {errorMessage ?? errorCode}";
}
