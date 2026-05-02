using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Models;

/// <summary>
/// Represents a file conversion job
/// </summary>
public class ConversionJob
{
    /// <summary>
    /// Unique identifier for this job
    /// </summary>
    public string Id { get; init; } = Guid.NewGuid().ToString("N")[..8];

    /// <summary>
    /// Path to the input file
    /// </summary>
    public required string InputPath { get; init; }

    /// <summary>
    /// Path for the output file. Construction-required; the orchestrator may
    /// rewrite this in-place before dispatching to a converter when collision
    /// protection auto-renames "stem.ext" to "stem (N).ext". Callers that
    /// display the path before calling ConvertAsync should re-read it from
    /// the returned <see cref="ConversionResult.OutputPath"/> afterwards
    /// rather than relying on the original value.
    /// </summary>
    public required string OutputPath { get; set; }

    /// <summary>
    /// Source format (detected or specified)
    /// </summary>
    public FileFormat? SourceFormat { get; set; }

    /// <summary>
    /// Target format
    /// </summary>
    public FileFormat? TargetFormat { get; set; }

    /// <summary>
    /// Conversion options
    /// </summary>
    public ConversionOptions Options { get; init; } = new();

    /// <summary>
    /// Current status of the job
    /// </summary>
    public ConversionStatus Status { get; set; } = ConversionStatus.Pending;

    /// <summary>
    /// When the job was created
    /// </summary>
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;

    /// <summary>
    /// When the job started processing
    /// </summary>
    public DateTime? StartedAt { get; set; }

    /// <summary>
    /// When the job completed
    /// </summary>
    public DateTime? CompletedAt { get; set; }

    /// <summary>
    /// Input file size in bytes
    /// </summary>
    public long InputFileSize { get; set; }

    /// <summary>
    /// Output file size in bytes (after completion)
    /// </summary>
    public long OutputFileSize { get; set; }

    /// <summary>
    /// Converter that handled this job
    /// </summary>
    public string? ConverterUsed { get; set; }

    /// <summary>
    /// Input file extension (lowercase, without dot)
    /// </summary>
    public string InputExtension => Path.GetExtension(InputPath).TrimStart('.').ToLowerInvariant();

    /// <summary>
    /// Output file extension (lowercase, without dot)
    /// </summary>
    public string OutputExtension => Path.GetExtension(OutputPath).TrimStart('.').ToLowerInvariant();

    /// <summary>
    /// Input filename without path
    /// </summary>
    public string InputFileName => Path.GetFileName(InputPath);

    /// <summary>
    /// Output filename without path
    /// </summary>
    public string OutputFileName => Path.GetFileName(OutputPath);

    /// <summary>
    /// Duration of the conversion
    /// </summary>
    public TimeSpan? Duration => StartedAt.HasValue && CompletedAt.HasValue 
        ? CompletedAt.Value - StartedAt.Value 
        : null;

    /// <summary>
    /// Create a job from input/output paths
    /// </summary>
    public static ConversionJob Create(string inputPath, string outputPath, ConversionOptions? options = null)
    {
        return new ConversionJob
        {
            InputPath = NormalizePath(inputPath),
            OutputPath = NormalizePath(outputPath),
            Options = options ?? new ConversionOptions()
        };
    }

    /// <summary>
    /// Create a job with auto-generated output path from a target extension.
    /// </summary>
    public static ConversionJob CreateForExtension(string inputPath, string outputExtension, ConversionOptions? options = null)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? ".";
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var ext = PathSafety.NormalizeExtensionOrThrow(outputExtension, nameof(outputExtension));
        var outputPath = Path.Combine(dir, $"{name}.{ext}");
        
        return Create(inputPath, outputPath, options);
    }

    private static string NormalizePath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return path ?? string.Empty;

        try { return Path.GetFullPath(path); }
        catch { return path; }
    }
}

/// <summary>
/// Status of a conversion job
/// </summary>
public enum ConversionStatus
{
    Pending,
    Queued,
    Running,
    Completed,
    Failed,
    Cancelled,
    Skipped
}
