using System.Collections.Concurrent;
using System.Reflection;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Severity levels for <see cref="IStructuredLogger"/> entries. The
/// <see cref="ConverterXOptions.VerboseLogging"/> toggle gates Debug+Info
/// writes; Warning and above always reach disk so post-mortem evidence is
/// available when something goes wrong.
/// </summary>
public enum LogLevel
{
    Debug,
    Info,
    Warning,
    Error,
    Crash,
}

/// <summary>
/// Single structured log entry. Persisted as one JSON object per line
/// (NDJSON) so the file streams cleanly into any log viewer (Catppuccin
/// console panel inside the app, plain text editors, jq, &amp;c.) without
/// requiring a parser to hold the entire file.
/// </summary>
public sealed record LogEntry(
    DateTime TimestampUtc,
    LogLevel Level,
    string Category,
    string Message,
    string? ExceptionType = null,
    string? ExceptionMessage = null,
    string? StackTrace = null);

/// <summary>
/// In-process structured logger backing <see cref="App"/> diagnostics.
/// Writes daily-rotated NDJSON files under
/// <c>%LocalAppData%/UniversalConverterX/logs/</c>, retaining the last 30
/// days and keeping the most-recent 500 entries in a memory ring buffer
/// for crash-bundle population.
/// </summary>
public interface IStructuredLogger
{
    /// <summary>Append an entry. No-op if the level is below the verbosity gate.</summary>
    void Log(LogLevel level, string category, string message, Exception? exception = null);

    void Debug(string category, string message) => Log(LogLevel.Debug, category, message);
    void Info(string category, string message) => Log(LogLevel.Info, category, message);
    void Warn(string category, string message, Exception? ex = null) => Log(LogLevel.Warning, category, message, ex);
    void Error(string category, string message, Exception? ex = null) => Log(LogLevel.Error, category, message, ex);

    /// <summary>Snapshot the in-memory ring buffer (newest-last).</summary>
    IReadOnlyList<LogEntry> Snapshot();

    /// <summary>Directory where rotated NDJSON files live.</summary>
    string LogDirectory { get; }

    /// <summary>Directory where crash bundles are written.</summary>
    string CrashDirectory { get; }
}

/// <inheritdoc cref="IStructuredLogger"/>
public sealed class StructuredLogger : IStructuredLogger
{
    private const int RingBufferCapacity = 500;
    private const int RetentionDays = 30;

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = false,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private readonly ConverterXOptions _options;
    private readonly object _writeGate = new();
    private readonly ConcurrentQueue<LogEntry> _ring = new();

    public string LogDirectory { get; }
    public string CrashDirectory { get; }

    public StructuredLogger(IOptions<ConverterXOptions> options)
    {
        _options = options.Value;
        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX");
        LogDirectory = Path.Combine(root, "logs");
        CrashDirectory = Path.Combine(root, "crashes");

        TryEnsureDirectory(LogDirectory);
        TryEnsureDirectory(CrashDirectory);
        TryPruneOldFiles(LogDirectory, "ucx-*.ndjson");
        TryPruneOldFiles(CrashDirectory, "crash_*.zip");

        Log(LogLevel.Info, "logger", $"Structured logger initialized; verbose={_options.VerboseLogging}");
    }

    public void Log(LogLevel level, string category, string message, Exception? exception = null)
    {
        if (level <= LogLevel.Info && !_options.VerboseLogging)
        {
            // Even with verbose off we keep Info+ in the ring buffer so a
            // crash bundle has a meaningful tail. Disk writes are skipped.
            EnqueueRing(BuildEntry(level, category, message, exception));
            return;
        }

        var entry = BuildEntry(level, category, message, exception);
        EnqueueRing(entry);
        TryAppendDisk(entry);
    }

    public IReadOnlyList<LogEntry> Snapshot() => _ring.ToArray();

    private static LogEntry BuildEntry(LogLevel level, string category, string message, Exception? exception)
    {
        return new LogEntry(
            TimestampUtc: DateTime.UtcNow,
            Level: level,
            Category: string.IsNullOrWhiteSpace(category) ? "ucx" : category,
            Message: message ?? string.Empty,
            ExceptionType: exception?.GetType().FullName,
            ExceptionMessage: exception?.Message,
            StackTrace: exception?.StackTrace);
    }

    private void EnqueueRing(LogEntry entry)
    {
        _ring.Enqueue(entry);
        while (_ring.Count > RingBufferCapacity && _ring.TryDequeue(out _)) { }
    }

    private void TryAppendDisk(LogEntry entry)
    {
        try
        {
            var path = Path.Combine(LogDirectory, $"ucx-{entry.TimestampUtc:yyyyMMdd}.ndjson");
            var line = JsonSerializer.Serialize(entry, JsonOpts);
            lock (_writeGate)
            {
                File.AppendAllText(path, line + Environment.NewLine, Encoding.UTF8);
            }
        }
        catch
        {
            // Disk full / locked profile / antivirus quarantine — never let
            // logging crash the app. The ring buffer still holds the entry.
        }
    }

    private static void TryEnsureDirectory(string path)
    {
        try { Directory.CreateDirectory(path); }
        catch { /* permission-denied profile — ring buffer is the fallback */ }
    }

    private static void TryPruneOldFiles(string directory, string pattern)
    {
        try
        {
            if (!Directory.Exists(directory)) return;
            var cutoff = DateTime.UtcNow.AddDays(-RetentionDays);
            foreach (var file in Directory.EnumerateFiles(directory, pattern))
            {
                try
                {
                    if (File.GetLastWriteTimeUtc(file) < cutoff)
                        File.Delete(file);
                }
                catch { /* one stuck file shouldn't stop the sweep */ }
            }
        }
        catch { }
    }

    /// <summary>
    /// Compose a "system info" block embedded in every crash bundle. Stays
    /// process-local — no MAC addresses, no usernames, no machine GUID.
    /// </summary>
    internal static string BuildSystemInfo()
    {
        var sb = new StringBuilder();
        sb.AppendLine("=== UniversalConverterX crash bundle ===");
        sb.AppendLine($"timestamp_utc      : {DateTime.UtcNow:O}");
        sb.AppendLine($"app_version        : {GetAppVersion()}");
        sb.AppendLine($"runtime            : {Environment.Version}");
        sb.AppendLine($"os                 : {Environment.OSVersion.VersionString}");
        sb.AppendLine($"os_64bit           : {Environment.Is64BitOperatingSystem}");
        sb.AppendLine($"process_64bit      : {Environment.Is64BitProcess}");
        sb.AppendLine($"processors         : {Environment.ProcessorCount}");
        sb.AppendLine($"working_set_mb     : {Environment.WorkingSet / 1024 / 1024}");
        sb.AppendLine($"culture            : {System.Globalization.CultureInfo.CurrentCulture.Name}");
        sb.AppendLine($"system_dir         : {Environment.SystemDirectory}");
        return sb.ToString();
    }

    private static string GetAppVersion()
    {
        try
        {
            return Assembly.GetEntryAssembly()?.GetName().Version?.ToString()
                ?? typeof(StructuredLogger).Assembly.GetName().Version?.ToString()
                ?? "unknown";
        }
        catch { return "unknown"; }
    }
}
