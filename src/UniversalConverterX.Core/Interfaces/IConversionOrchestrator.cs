namespace UniversalConverterX.Core.Interfaces;

/// <summary>
/// Main orchestrator for routing conversions to appropriate strategies
/// </summary>
public interface IConversionOrchestrator
{
    /// <summary>
    /// Convert a single file
    /// </summary>
    Task<ConversionResult> ConvertAsync(
        string inputPath,
        string outputPath,
        ConversionOptions? options = null,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Convert a single file using a specific job
    /// </summary>
    Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Convert multiple files in batch
    /// </summary>
    Task<BatchConversionResult> ConvertBatchAsync(
        IEnumerable<ConversionJob> jobs,
        int maxParallelism = 4,
        IProgress<BatchProgress>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Get available output formats for an input file
    /// </summary>
    IReadOnlyCollection<string> GetOutputFormatsFor(string inputPath);

    /// <summary>
    /// Get the best converter for a specific conversion
    /// </summary>
    IConverterStrategy? GetBestConverter(string inputExtension, string outputExtension);

    /// <summary>
    /// Get all registered converters
    /// </summary>
    IReadOnlyCollection<IConverterStrategy> GetConverters();

    /// <summary>
    /// Check if a conversion path exists
    /// </summary>
    bool CanConvert(string inputExtension, string outputExtension);

    /// <summary>
    /// Detect the format of a file
    /// </summary>
    Task<FileFormat> DetectFormatAsync(string filePath, CancellationToken cancellationToken = default);
}

/// <summary>
/// Progress for batch conversions
/// </summary>
public record BatchProgress(
    int CompletedJobs,
    int TotalJobs,
    int FailedJobs,
    ConversionJob? CurrentJob,
    ConversionProgress? CurrentJobProgress)
{
    public double OverallPercent => TotalJobs > 0 ? (double)CompletedJobs / TotalJobs * 100 : 0;
}

/// <summary>
/// Result of a batch conversion
/// </summary>
public record BatchConversionResult(
    IReadOnlyList<ConversionResult> Results,
    TimeSpan TotalDuration)
{
    public int SuccessCount => Results.Count(r => r.Success);
    public int FailureCount => Results.Count(r => !r.Success);
    public bool AllSucceeded => Results.All(r => r.Success);
}
