using System.IO.Compression;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Builds local-only crash bundles for support handoff. Pure local; charter
/// rule: nothing leaves the user's disk unless they manually attach the
/// resulting zip to a bug report.
/// </summary>
public static class CrashBundle
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    /// <summary>
    /// Capture a zip containing recent log entries, system info, and the
    /// triggering exception (if any). Returns the bundle path on success
    /// or <c>null</c> if the write failed.
    /// </summary>
    public static string? Capture(IStructuredLogger logger, Exception? exception, string? note = null)
    {
        try
        {
            Directory.CreateDirectory(logger.CrashDirectory);
            var stamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss");
            var bundlePath = Path.Combine(logger.CrashDirectory, $"crash_{stamp}.zip");

            using var zipStream = new FileStream(bundlePath, FileMode.Create, FileAccess.Write);
            using var zip = new ZipArchive(zipStream, ZipArchiveMode.Create);

            WriteEntry(zip, "system-info.txt", StructuredLogger.BuildSystemInfo());

            if (exception is not null)
            {
                var exDump = new StringBuilder();
                exDump.AppendLine("=== Triggering exception ===");
                AppendException(exDump, exception, depth: 0);
                WriteEntry(zip, "exception.txt", exDump.ToString());
            }

            if (!string.IsNullOrWhiteSpace(note))
                WriteEntry(zip, "user-note.txt", note);

            // Recent NDJSON tail (ring buffer) — most actionable signal.
            WriteEntry(zip, "log-tail.ndjson", FormatRingBuffer(logger.Snapshot()));

            // Today's full log file, if it exists, for full-context reads.
            try
            {
                var today = Path.Combine(logger.LogDirectory, $"ucx-{DateTime.UtcNow:yyyyMMdd}.ndjson");
                if (File.Exists(today))
                {
                    using var fs = File.OpenRead(today);
                    var entry = zip.CreateEntry("log-today.ndjson", CompressionLevel.Optimal);
                    using var es = entry.Open();
                    fs.CopyTo(es);
                }
            }
            catch { /* missing today file is OK — ring buffer is the fallback */ }

            return bundlePath;
        }
        catch
        {
            return null;
        }
    }

    private static void AppendException(StringBuilder sb, Exception ex, int depth)
    {
        var indent = new string(' ', depth * 2);
        sb.AppendLine($"{indent}Type    : {ex.GetType().FullName}");
        sb.AppendLine($"{indent}Message : {ex.Message}");
        if (!string.IsNullOrWhiteSpace(ex.StackTrace))
        {
            sb.AppendLine($"{indent}Stack   :");
            foreach (var line in ex.StackTrace.Split('\n'))
                sb.AppendLine($"{indent}  {line.TrimEnd()}");
        }
        if (ex.InnerException is not null)
        {
            sb.AppendLine($"{indent}--- inner ---");
            AppendException(sb, ex.InnerException, depth + 1);
        }
    }

    private static string FormatRingBuffer(IReadOnlyList<LogEntry> snapshot)
    {
        var sb = new StringBuilder();
        foreach (var entry in snapshot)
            sb.AppendLine(JsonSerializer.Serialize(entry, JsonOpts));
        return sb.ToString();
    }

    private static void WriteEntry(ZipArchive zip, string name, string contents)
    {
        var entry = zip.CreateEntry(name, CompressionLevel.Optimal);
        using var stream = entry.Open();
        using var writer = new StreamWriter(stream, Encoding.UTF8);
        writer.Write(contents);
    }
}
