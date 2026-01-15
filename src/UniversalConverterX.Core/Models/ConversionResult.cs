namespace UniversalConverterX.Core.Models;

/// <summary>
/// Result of a conversion operation
/// </summary>
public class ConversionResult
{
    /// <summary>
    /// Whether the conversion was successful
    /// </summary>
    public bool Success { get; init; }

    /// <summary>
    /// The conversion job
    /// </summary>
    public required ConversionJob Job { get; init; }

    /// <summary>
    /// Path to the output file (if successful)
    /// </summary>
    public string? OutputPath { get; init; }

    /// <summary>
    /// Output file size in bytes
    /// </summary>
    public long OutputSize { get; init; }

    /// <summary>
    /// Duration of the conversion
    /// </summary>
    public TimeSpan Duration { get; init; }

    /// <summary>
    /// Error message (if failed)
    /// </summary>
    public string? ErrorMessage { get; init; }

    /// <summary>
    /// Exit code from the converter process
    /// </summary>
    public int ExitCode { get; init; }

    /// <summary>
    /// Standard output from the converter
    /// </summary>
    public string? StandardOutput { get; init; }

    /// <summary>
    /// Standard error from the converter
    /// </summary>
    public string? StandardError { get; init; }

    /// <summary>
    /// Converter that was used
    /// </summary>
    public string? ConverterUsed { get; init; }

    /// <summary>
    /// Command line that was executed
    /// </summary>
    public string? CommandLine { get; init; }

    /// <summary>
    /// Warnings generated during conversion
    /// </summary>
    public IReadOnlyList<string> Warnings { get; init; } = [];

    /// <summary>
    /// Compression ratio (input size / output size)
    /// </summary>
    public double? CompressionRatio => Job.InputFileSize > 0 && OutputSize > 0 
        ? (double)Job.InputFileSize / OutputSize 
        : null;

    /// <summary>
    /// Size reduction percentage
    /// </summary>
    public double? SizeReductionPercent => Job.InputFileSize > 0 && OutputSize > 0
        ? (1 - (double)OutputSize / Job.InputFileSize) * 100
        : null;

    /// <summary>
    /// Processing speed (input bytes per second)
    /// </summary>
    public double? ProcessingSpeed => Duration.TotalSeconds > 0 
        ? Job.InputFileSize / Duration.TotalSeconds 
        : null;

    /// <summary>
    /// Create a successful result
    /// </summary>
    public static ConversionResult Succeeded(
        ConversionJob job, 
        string outputPath, 
        TimeSpan duration,
        string? converter = null,
        string? commandLine = null,
        IReadOnlyList<string>? warnings = null)
    {
        var outputSize = File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0;
        
        return new ConversionResult
        {
            Success = true,
            Job = job,
            OutputPath = outputPath,
            OutputSize = outputSize,
            Duration = duration,
            ExitCode = 0,
            ConverterUsed = converter,
            CommandLine = commandLine,
            Warnings = warnings ?? []
        };
    }

    /// <summary>
    /// Create a failed result
    /// </summary>
    public static ConversionResult Failed(
        ConversionJob job,
        string errorMessage,
        TimeSpan duration,
        int exitCode = -1,
        string? standardOutput = null,
        string? standardError = null,
        string? converter = null,
        string? commandLine = null)
    {
        return new ConversionResult
        {
            Success = false,
            Job = job,
            ErrorMessage = errorMessage,
            Duration = duration,
            ExitCode = exitCode,
            StandardOutput = standardOutput,
            StandardError = standardError,
            ConverterUsed = converter,
            CommandLine = commandLine
        };
    }

    /// <summary>
    /// Create a cancelled result
    /// </summary>
    public static ConversionResult Cancelled(ConversionJob job, TimeSpan duration)
    {
        return new ConversionResult
        {
            Success = false,
            Job = job,
            ErrorMessage = "Conversion was cancelled",
            Duration = duration,
            ExitCode = -1
        };
    }
}
