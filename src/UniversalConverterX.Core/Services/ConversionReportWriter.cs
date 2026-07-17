using System.Globalization;
using System.Text;
using System.Text.Json;

namespace UniversalConverterX.Core.Services;

public sealed record ConversionReportEntry
{
    public DateTime TimestampUtc { get; init; }
    public string SourcePath { get; init; } = "";
    public string? OutputPath { get; init; }
    public string Status { get; init; } = "failed";
    public long? SourceBytes { get; init; }
    public long? OutputBytes { get; init; }

    /// <summary>
    /// Output bytes minus source bytes. Negative values mean the output is smaller.
    /// </summary>
    public long? ByteDelta =>
        SourceBytes is long source && OutputBytes is long output ? output - source : null;

    public double DurationSeconds { get; init; }
    public string? Engine { get; init; }
    public string Action { get; init; } = "convert";
    public string? Profile { get; init; }
    public IReadOnlyList<string> Warnings { get; init; } = [];
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
}

public sealed record ConversionReportSummary(
    int TotalFiles,
    int Succeeded,
    int Failed,
    int Skipped,
    int Cancelled,
    long TotalSourceBytes,
    long TotalOutputBytes,
    long ByteDelta,
    double DurationSeconds);

public sealed record ConversionBatchReport(
    int SchemaVersion,
    DateTime GeneratedAtUtc,
    ConversionReportSummary Summary,
    IReadOnlyList<ConversionReportEntry> Files);

/// <summary>
/// Creates deterministic, machine-readable JSON and RFC 4180 CSV reports for
/// live conversion results or persisted history rows.
/// </summary>
public static class ConversionReportWriter
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public static bool SupportsPath(string? path)
    {
        var extension = Path.GetExtension(path);
        return string.Equals(extension, ".json", StringComparison.OrdinalIgnoreCase)
            || string.Equals(extension, ".csv", StringComparison.OrdinalIgnoreCase);
    }

    public static ConversionBatchReport Create(
        IEnumerable<ConversionResult> results,
        DateTime? generatedAtUtc = null)
    {
        ArgumentNullException.ThrowIfNull(results);

        var entries = results.Select(result =>
        {
            var timestamp = result.Job.CompletedAt
                ?? result.Job.StartedAt
                ?? result.Job.CreatedAt;
            return new ConversionReportEntry
            {
                TimestampUtc = ToUtc(timestamp),
                SourcePath = result.Job.InputPath,
                OutputPath = result.OutputPath,
                Status = GetStatus(result),
                SourceBytes = GetSourceBytes(result.Job),
                OutputBytes = result.Success ? result.OutputSize : null,
                DurationSeconds = result.Duration.TotalSeconds,
                Engine = result.ConverterUsed,
                Profile = result.Job.Options.Quality.ToString().ToLowerInvariant(),
                Warnings = result.Warnings.ToArray(),
                ErrorCode = result.Success ? null : GetErrorCode(result),
                ErrorMessage = result.ErrorMessage,
            };
        }).ToList();

        return CreateDocument(entries, generatedAtUtc);
    }

    public static ConversionBatchReport CreateFromHistory(
        IEnumerable<ConversionHistoryEntry> history,
        DateTime? generatedAtUtc = null)
    {
        ArgumentNullException.ThrowIfNull(history);

        var entries = history.Select(row => new ConversionReportEntry
        {
            TimestampUtc = ToUtc(row.Timestamp),
            SourcePath = row.SourcePath,
            OutputPath = row.OutputPath,
            Status = row.Success ? "succeeded" : "failed",
            SourceBytes = row.SourceBytes,
            OutputBytes = row.OutputBytes,
            DurationSeconds = row.DurationSeconds,
            Engine = row.Engine,
            Action = row.Action,
            Profile = row.Profile,
            ErrorCode = row.ErrorCode,
            ErrorMessage = row.ErrorMessage,
        }).ToList();

        return CreateDocument(entries, generatedAtUtc);
    }

    public static async Task WriteAsync(
        string path,
        ConversionBatchReport report,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(report);
        if (!SupportsPath(path))
            throw new ArgumentException("Report path must end in .json or .csv.", nameof(path));

        var fullPath = Path.GetFullPath(path);
        var directory = Path.GetDirectoryName(fullPath)
            ?? throw new ArgumentException("Report path has no directory.", nameof(path));
        Directory.CreateDirectory(directory);

        var content = Path.GetExtension(fullPath).Equals(".csv", StringComparison.OrdinalIgnoreCase)
            ? ToCsv(report)
            : JsonSerializer.Serialize(report, JsonOptions) + Environment.NewLine;
        var tempPath = Path.Combine(directory, $".{Path.GetFileName(fullPath)}.{Guid.NewGuid():N}.tmp");

        try
        {
            await File.WriteAllTextAsync(
                    tempPath,
                    content,
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                    cancellationToken)
                .ConfigureAwait(false);
            File.Move(tempPath, fullPath, overwrite: true);
        }
        finally
        {
            try { File.Delete(tempPath); } catch { /* best-effort temp cleanup */ }
        }
    }

    private static ConversionBatchReport CreateDocument(
        IReadOnlyList<ConversionReportEntry> entries,
        DateTime? generatedAtUtc)
    {
        var sourceBytes = entries.Sum(entry => entry.SourceBytes ?? 0L);
        var outputBytes = entries.Sum(entry => entry.OutputBytes ?? 0L);
        var byteDelta = entries.Sum(entry => entry.ByteDelta ?? 0L);
        var summary = new ConversionReportSummary(
            TotalFiles: entries.Count,
            Succeeded: entries.Count(entry => entry.Status == "succeeded"),
            Failed: entries.Count(entry => entry.Status == "failed"),
            Skipped: entries.Count(entry => entry.Status == "skipped"),
            Cancelled: entries.Count(entry => entry.Status == "cancelled"),
            TotalSourceBytes: sourceBytes,
            TotalOutputBytes: outputBytes,
            ByteDelta: byteDelta,
            DurationSeconds: entries.Sum(entry => entry.DurationSeconds));

        return new ConversionBatchReport(
            SchemaVersion: 1,
            GeneratedAtUtc: ToUtc(generatedAtUtc ?? DateTime.UtcNow),
            Summary: summary,
            Files: entries);
    }

    private static string ToCsv(ConversionBatchReport report)
    {
        var csv = new StringBuilder();
        AppendRow(csv,
        [
            "timestamp_utc", "source_path", "output_path", "status",
            "source_bytes", "output_bytes", "byte_delta", "duration_seconds",
            "engine", "action", "profile", "warnings", "error_code", "error_message",
        ]);

        foreach (var entry in report.Files)
        {
            AppendRow(csv,
            [
                entry.TimestampUtc.ToString("O", CultureInfo.InvariantCulture),
                entry.SourcePath,
                entry.OutputPath,
                entry.Status,
                Format(entry.SourceBytes),
                Format(entry.OutputBytes),
                Format(entry.ByteDelta),
                entry.DurationSeconds.ToString("0.######", CultureInfo.InvariantCulture),
                entry.Engine,
                entry.Action,
                entry.Profile,
                string.Join(" | ", entry.Warnings),
                entry.ErrorCode,
                entry.ErrorMessage,
            ]);
        }

        return csv.ToString();
    }

    private static void AppendRow(StringBuilder csv, IEnumerable<string?> fields)
    {
        var first = true;
        foreach (var field in fields)
        {
            if (!first)
                csv.Append(',');
            first = false;
            csv.Append(EscapeCsv(field));
        }
        csv.Append("\r\n");
    }

    private static string EscapeCsv(string? value)
    {
        value ??= "";

        // CSV-injection hardening: report fields (source paths, engine names,
        // warnings, error messages) come from filenames and external tool output.
        // A leading =, +, -, or @ is interpreted as a formula when the report is
        // opened in Excel/LibreOffice. Neutralize it with a leading apostrophe —
        // but leave genuine numeric fields (e.g. a negative byte delta) untouched.
        if (value.Length > 0 && value[0] is '=' or '+' or '-' or '@'
            && !double.TryParse(value, NumberStyles.Float | NumberStyles.AllowLeadingSign,
                CultureInfo.InvariantCulture, out _))
            value = "'" + value;

        if (!value.ContainsAny([',', '"', '\r', '\n']))
            return value;
        return $"\"{value.Replace("\"", "\"\"")}\"";
    }

    private static string Format(long? value) =>
        value?.ToString(CultureInfo.InvariantCulture) ?? "";

    private static long? GetSourceBytes(ConversionJob job)
    {
        if (job.InputFileSize > 0)
            return job.InputFileSize;
        try { return File.Exists(job.InputPath) ? new FileInfo(job.InputPath).Length : null; }
        catch { return null; }
    }

    private static string GetStatus(ConversionResult result) => result switch
    {
        { WasCancelled: true } => "cancelled",
        { WasSkipped: true } => "skipped",
        { Success: true } => "succeeded",
        _ => "failed",
    };

    private static string? GetErrorCode(ConversionResult result) => result switch
    {
        { WasCancelled: true } => "cancelled",
        { WasSkipped: true } => "skipped",
        { ExitCode: not 0 } => $"exit_{result.ExitCode}",
        _ => null,
    };

    private static DateTime ToUtc(DateTime value) => value.Kind switch
    {
        DateTimeKind.Utc => value,
        DateTimeKind.Local => value.ToUniversalTime(),
        _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
    };
}
