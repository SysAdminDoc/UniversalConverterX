namespace UniversalConverterX.Core.Interfaces;

/// <summary>
/// Manages CLI tool binaries and their availability
/// </summary>
public interface IToolManager
{
    /// <summary>
    /// Base path where tools are stored
    /// </summary>
    string ToolsBasePath { get; }

    /// <summary>
    /// Get the full path to a tool executable
    /// </summary>
    string GetToolPath(string toolName);

    /// <summary>
    /// Check if a tool is available
    /// </summary>
    bool IsToolAvailable(string toolName);

    /// <summary>
    /// Get the version of a tool
    /// </summary>
    Task<string?> GetToolVersionAsync(string toolName, CancellationToken cancellationToken = default);

    /// <summary>
    /// Download/update a tool to the latest version
    /// </summary>
    Task<ToolDownloadResult> DownloadToolAsync(
        string toolName,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Get all available tools
    /// </summary>
    IReadOnlyCollection<ToolInfo> GetAvailableTools();

    /// <summary>
    /// Verify tool integrity (checksum validation)
    /// </summary>
    Task<bool> VerifyToolIntegrityAsync(string toolName, CancellationToken cancellationToken = default);
}

/// <summary>
/// Information about a CLI tool
/// </summary>
public record ToolInfo(
    string Id,
    string Name,
    string? Version,
    string ExecutableName,
    bool IsInstalled,
    long? SizeBytes,
    string? Description);

/// <summary>
/// Result of a tool download operation
/// </summary>
public record ToolDownloadResult(
    bool Success,
    string ToolName,
    string? Version,
    string? ErrorMessage);

/// <summary>
/// Download progress information
/// </summary>
public record DownloadProgress(
    long BytesDownloaded,
    long TotalBytes,
    double SpeedBytesPerSecond)
{
    public double Percent => TotalBytes > 0 ? (double)BytesDownloaded / TotalBytes * 100 : 0;
}
