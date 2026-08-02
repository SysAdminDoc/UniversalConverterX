using System.Collections.ObjectModel;
using Microsoft.Extensions.Options;
using Microsoft.UI.Dispatching;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.UI.Services;

public sealed record HistoryRecord
{
    public long Id { get; init; }
    public DateTime Timestamp { get; init; } = DateTime.UtcNow;
    public string Engine { get; init; } = "";
    public string Action { get; init; } = "";
    public string SourcePath { get; init; } = "";
    public string? OutputPath { get; init; }
    public long? SourceBytes { get; init; }
    public long? OutputBytes { get; init; }
    public double DurationSeconds { get; init; }
    public bool Success { get; init; }
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
    public string? Profile { get; init; }
    public string? RerunParameters { get; init; }

    /// <summary>
    /// Serialized job provenance: redacted arguments, the binary that ran,
    /// input and output identity, and the post-hoc probe.
    /// </summary>
    public string? Provenance { get; init; }
    public string ErrorDetails =>
        string.IsNullOrWhiteSpace(ErrorMessage) ? "No error details were provided." : ErrorMessage;

    public string Display
    {
        get
        {
            var source = Path.GetFileName(SourcePath);
            var status = Success ? "OK" : "FAIL";
            var saved = SavedDelta is long bytes ? $" (saved {FormatBytes(bytes)})" : "";
            return $"[{Timestamp.ToLocalTime():yyyy-MM-dd HH:mm}] {Engine} {Action} {source} -- {status}{saved}";
        }
    }

    public long? SavedDelta =>
        SourceBytes is long sourceBytes && OutputBytes is long outputBytes && sourceBytes > outputBytes
            ? sourceBytes - outputBytes
            : null;

    public Microsoft.UI.Xaml.Visibility SuccessIconVisibility =>
        Success ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    public Microsoft.UI.Xaml.Visibility ErrorVisibility =>
        Success ? Microsoft.UI.Xaml.Visibility.Collapsed : Microsoft.UI.Xaml.Visibility.Visible;

    public static string FormatBytes(long bytes)
    {
        double value = bytes;
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        var index = 0;
        while (value >= 1024 && index < units.Length - 1)
        {
            value /= 1024;
            index++;
        }

        return $"{value:0.##} {units[index]}";
    }

    internal ConversionHistoryEntry ToEntry() => new()
    {
        Id = Id,
        Timestamp = Timestamp,
        Engine = Engine,
        Action = Action,
        SourcePath = SourcePath,
        OutputPath = OutputPath,
        SourceBytes = SourceBytes,
        OutputBytes = OutputBytes,
        DurationSeconds = DurationSeconds,
        Success = Success,
        ErrorCode = ErrorCode,
        ErrorMessage = ErrorMessage,
        Profile = Profile,
        RerunParameters = RerunParameters,
        Provenance = Provenance,
    };

    internal static HistoryRecord FromEntry(ConversionHistoryEntry entry) => new()
    {
        Id = entry.Id,
        Timestamp = entry.Timestamp,
        Engine = entry.Engine,
        Action = entry.Action,
        SourcePath = entry.SourcePath,
        OutputPath = entry.OutputPath,
        SourceBytes = entry.SourceBytes,
        OutputBytes = entry.OutputBytes,
        DurationSeconds = entry.DurationSeconds,
        Success = entry.Success,
        ErrorCode = entry.ErrorCode,
        ErrorMessage = entry.ErrorMessage,
        Profile = entry.Profile,
        RerunParameters = entry.RerunParameters,
        Provenance = entry.Provenance,
    };
}

public sealed record HistorySummary(
    int TotalJobs,
    int Succeeded,
    int Failed,
    long TotalSourceBytes,
    long TotalOutputBytes,
    long SpaceSavedBytes);

public interface IHistoryService
{
    ObservableCollection<HistoryRecord> Recent { get; }
    Task LogAsync(HistoryRecord record);
    Task<IReadOnlyList<HistoryRecord>> QueryAsync(string? search = null, int? limit = 500);
    Task<HistoryRecord?> GetAsync(long id);
    Task<HistorySummary> SummarizeAsync(string? search = null);
    Task<int> ExportAsync(string path, string? search = null);
    Task DeleteAsync(long id);
    Task ClearAsync();
}

/// <summary>
/// WinUI adapter around the headless <see cref="HistoryStore"/>. Only
/// collection updates are dispatched to the UI thread; SQLite behavior lives
/// in Core where it is reusable and covered by integration tests.
/// </summary>
public sealed class HistoryService : IHistoryService, IDisposable
{
    private const int RecentCap = 100;
    private const int MinRetentionRows = 100;
    private const int DefaultRetentionRows = 10_000;

    private readonly DispatcherQueue _ui;
    private readonly HistoryStore _store;
    private bool _disposed;

    public ObservableCollection<HistoryRecord> Recent { get; } = [];

    public HistoryService() : this(null)
    {
    }

    public HistoryService(IOptions<ConverterXOptions>? options)
    {
        _ui = DispatcherQueue.GetForCurrentThread()
              ?? throw new InvalidOperationException("HistoryService must be constructed on a UI thread.");

        var configured = options?.Value;
        var retentionMaxRows = Math.Max(
            MinRetentionRows,
            configured?.MaxHistoryEntries > 0
                ? configured.MaxHistoryEntries
                : DefaultRetentionRows);
        var retentionDays = configured?.HistoryRetentionDays > 0
            ? configured.HistoryRetentionDays
            : 0;

        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX");
        _store = new HistoryStore(
            Path.Combine(directory, "history.db"),
            retentionMaxRows,
            retentionDays);

        _ = LoadRecentAsync();
    }

    public async Task LogAsync(HistoryRecord record)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var id = await _store.AddAsync(record.ToEntry()).ConfigureAwait(false);
        var stamped = record with { Id = id };
        _ui.TryEnqueue(() =>
        {
            Recent.Insert(0, stamped);
            while (Recent.Count > RecentCap)
                Recent.RemoveAt(Recent.Count - 1);
        });
    }

    public async Task<IReadOnlyList<HistoryRecord>> QueryAsync(string? search = null, int? limit = 500)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var entries = await _store.QueryAsync(search, limit).ConfigureAwait(false);
        return entries.Select(HistoryRecord.FromEntry).ToList();
    }

    public async Task<HistoryRecord?> GetAsync(long id)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var entry = await _store.GetAsync(id).ConfigureAwait(false);
        return entry is null ? null : HistoryRecord.FromEntry(entry);
    }

    public async Task<HistorySummary> SummarizeAsync(string? search = null)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var summary = await _store.SummarizeAsync(search).ConfigureAwait(false);
        return new HistorySummary(
            summary.TotalJobs,
            summary.Succeeded,
            summary.Failed,
            summary.TotalSourceBytes,
            summary.TotalOutputBytes,
            summary.SpaceSavedBytes);
    }

    public async Task<int> ExportAsync(string path, string? search = null)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var entries = await _store.QueryAsync(search, limit: 10_000).ConfigureAwait(false);
        var report = ConversionReportWriter.CreateFromHistory(entries);
        await ConversionReportWriter.WriteAsync(path, report).ConfigureAwait(false);
        return entries.Count;
    }

    public async Task DeleteAsync(long id)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _store.DeleteAsync(id).ConfigureAwait(false);
        _ui.TryEnqueue(() =>
        {
            for (var index = Recent.Count - 1; index >= 0; index--)
            {
                if (Recent[index].Id == id)
                    Recent.RemoveAt(index);
            }
        });
    }

    public async Task ClearAsync()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _store.ClearAsync().ConfigureAwait(false);
        _ui.TryEnqueue(Recent.Clear);
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        _store.Dispose();
    }

    private async Task LoadRecentAsync()
    {
        try
        {
            var initial = await _store.QueryAsync(search: null, limit: RecentCap).ConfigureAwait(false);
            _ui.TryEnqueue(() =>
            {
                Recent.Clear();
                foreach (var entry in initial)
                    Recent.Add(HistoryRecord.FromEntry(entry));
            });
        }
        catch
        {
            // History is non-critical. A locked or damaged database leaves the
            // in-memory collection empty instead of preventing app startup.
        }
    }
}
