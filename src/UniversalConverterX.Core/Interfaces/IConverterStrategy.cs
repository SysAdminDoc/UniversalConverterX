namespace UniversalConverterX.Core.Interfaces;

/// <summary>
/// Strategy interface for converter implementations.
/// Each CLI tool (FFmpeg, ImageMagick, etc.) implements this interface.
/// </summary>
public interface IConverterStrategy
{
    /// <summary>
    /// Unique identifier for this converter (e.g., "ffmpeg", "imagemagick")
    /// </summary>
    string Id { get; }

    /// <summary>
    /// Display name for the converter
    /// </summary>
    string Name { get; }

    /// <summary>
    /// Priority for format selection (higher = preferred)
    /// </summary>
    int Priority { get; }

    /// <summary>
    /// Executable name for the CLI tool
    /// </summary>
    string ExecutableName { get; }

    /// <summary>
    /// Check if this converter supports the given conversion
    /// </summary>
    bool CanConvert(FileFormat source, FileFormat target);

    /// <summary>
    /// Get all input formats supported by this converter
    /// </summary>
    IReadOnlyCollection<string> GetSupportedInputFormats();

    /// <summary>
    /// Get all output formats supported by this converter
    /// </summary>
    IReadOnlyCollection<string> GetSupportedOutputFormats();

    /// <summary>
    /// Get output formats available for a specific input format
    /// </summary>
    IReadOnlyCollection<string> GetOutputFormatsFor(string inputExtension);

    /// <summary>
    /// Execute the conversion
    /// </summary>
    Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Build command-line arguments for the conversion
    /// </summary>
    string[] BuildArguments(ConversionJob job, ConversionOptions options);

    /// <summary>
    /// Parse progress from CLI output
    /// </summary>
    ConversionProgress? ParseProgress(string outputLine, ConversionJob job);

    /// <summary>
    /// Validate the conversion job before execution
    /// </summary>
    ValidationResult ValidateJob(ConversionJob job);
}

/// <summary>
/// Represents a file format with metadata
/// </summary>
public record FileFormat(
    string Extension,
    string MimeType,
    FormatCategory Category,
    string? Description = null);

/// <summary>
/// Categories of file formats
/// </summary>
public enum FormatCategory
{
    Unknown,
    Video,
    Audio,
    Image,
    Document,
    Ebook,
    Vector,
    ThreeD,
    Archive,
    Data,
    Font,
    Subtitle
}

/// <summary>
/// Result of a validation check
/// </summary>
public record ValidationResult(bool IsValid, string? ErrorMessage = null)
{
    public static ValidationResult Success => new(true);
    public static ValidationResult Fail(string message) => new(false, message);
}
