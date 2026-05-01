using System.Collections.ObjectModel;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Options;
using Microsoft.UI.Dispatching;
using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.UI.Services;

public sealed record HistoryRecord
{
    public long Id { get; init; }
    public DateTime Timestamp { get; init; } = DateTime.UtcNow;
    public string Engine { get; init; } = "";        // "videocrush" | "clipforge" | etc.
    public string Action { get; init; } = "";        // "compress" | "convert" | "trim" | ...
    public string SourcePath { get; init; } = "";
    public string? OutputPath { get; init; }
    public long? SourceBytes { get; init; }
    public long? OutputBytes { get; init; }
    public double DurationSeconds { get; init; }
    public bool Success { get; init; }
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
    public string? Profile { get; init; }            // preset / target format / op tag
    public string ErrorDetails =>
        string.IsNullOrWhiteSpace(ErrorMessage) ? "No error details were provided." : ErrorMessage;

    public string Display
    {
        get
        {
            var src = System.IO.Path.GetFileName(SourcePath);
            var status = Success ? "OK" : "FAIL";
            var saved = SavedDelta is long s ? $" (saved {FormatBytes(s)})" : "";
            return $"[{Timestamp.ToLocalTime():yyyy-MM-dd HH:mm}] {Engine} {Action} {src} -- {status}{saved}";
        }
    }

    public long? SavedDelta =>
        (SourceBytes is long sb && OutputBytes is long ob && sb > ob) ? sb - ob : null;

    /// <summary>UI-friendly visibility for the success icon (collapsed on failure).</summary>
    public Microsoft.UI.Xaml.Visibility SuccessIconVisibility =>
        Success ? Microsoft.UI.Xaml.Visibility.Visible : Microsoft.UI.Xaml.Visibility.Collapsed;

    /// <summary>UI-friendly visibility for failure indicators (collapsed on success).</summary>
    public Microsoft.UI.Xaml.Visibility ErrorVisibility =>
        Success ? Microsoft.UI.Xaml.Visibility.Collapsed : Microsoft.UI.Xaml.Visibility.Visible;

    public static string FormatBytes(long b)
    {
        double v = b;
        string[] u = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        while (v >= 1024 && i < u.Length - 1) { v /= 1024; i++; }
        return $"{v:0.##} {u[i]}";
    }
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

    /// <summary>Append a job to the persistent log and to the in-memory Recent collection.</summary>
    Task LogAsync(HistoryRecord record);

    /// <summary>Query the history table. <paramref name="search"/> matches engine/action/source/profile.</summary>
    Task<IReadOnlyList<HistoryRecord>> QueryAsync(string? search = null, int? limit = 500);

    Task<HistorySummary> SummarizeAsync(string? search = null);

    Task DeleteAsync(long id);
    Task ClearAsync();
}

public sealed class HistoryService : IHistoryService
{
    private const int RecentCap = 100;

    /// <summary>Lower bound on the row cap so a misconfigured options blob
    /// (Max=0) can't reduce retention to zero and silently drop every job.</summary>
    private const int MinRetentionRows = 100;

    /// <summary>Default when no options provider is registered (tests, CLI scaffolds).</summary>
    private const int DefaultRetentionRows = 10_000;

    private readonly int _retentionMaxRows;
    private readonly int _retentionDays;
    private readonly DispatcherQueue _ui;
    private readonly string _dbPath;
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private int _writesSinceLastPrune;

    public ObservableCollection<HistoryRecord> Recent { get; } = [];

    public HistoryService() : this(null) { }

    public HistoryService(IOptions<ConverterXOptions>? options)
    {
        _ui = DispatcherQueue.GetForCurrentThread()
              ?? throw new InvalidOperationException(
                     "HistoryService must be constructed on a UI thread.");

        // Honour the user-configured cap when present; clamp to a sane floor
        // so a hostile config can't disable retention entirely.
        var opts = options?.Value;
        _retentionMaxRows = Math.Max(MinRetentionRows,
            opts?.MaxHistoryEntries > 0 ? opts.MaxHistoryEntries : DefaultRetentionRows);
        _retentionDays = opts?.HistoryRetentionDays > 0 ? opts.HistoryRetentionDays : 0;

        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX");
        Directory.CreateDirectory(dir);
        _dbPath = Path.Combine(dir, "history.db");

        EnsureSchema();
        _ = Task.Run(async () =>
        {
            try
            {
                var initial = await QueryAsync(search: null, limit: RecentCap);
                _ui.TryEnqueue(() =>
                {
                    Recent.Clear();
                    foreach (var r in initial) Recent.Add(r);
                });
            }
            catch
            {
                // Failing to load initial history must never crash the app —
                // empty Recent[] is a recoverable state.
            }
        });
    }

    private SqliteConnection Open()
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = _dbPath,
        };
        var conn = new SqliteConnection(builder.ToString());
        conn.Open();
        // WAL improves concurrency between the main-thread inserts and the
        // background QueryAsync reader without requiring a process-wide lock.
        // synchronous=NORMAL trades a small durability window for ~3-5x faster
        // writes and is appropriate for a non-critical UX log.
        using (var pragma = conn.CreateCommand())
        {
            pragma.CommandText = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;";
            try { pragma.ExecuteNonQuery(); } catch { /* WAL unsupported on some drives */ }
        }
        return conn;
    }

    private void EnsureSchema()
    {
        using var conn = Open();
        using var cmd = conn.CreateCommand();
        cmd.CommandText = """
            CREATE TABLE IF NOT EXISTS history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc   TEXT    NOT NULL,
                engine          TEXT    NOT NULL,
                action          TEXT    NOT NULL,
                source_path     TEXT    NOT NULL,
                output_path     TEXT,
                source_bytes    INTEGER,
                output_bytes    INTEGER,
                duration_sec    REAL    NOT NULL DEFAULT 0,
                success         INTEGER NOT NULL,
                error_code      TEXT,
                error_message   TEXT,
                profile         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_history_ts     ON history(timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_history_engine ON history(engine);
            CREATE INDEX IF NOT EXISTS idx_history_id     ON history(id DESC);
            """;
        cmd.ExecuteNonQuery();
    }

    /// <summary>
    /// Trim the oldest rows back to the configured retention cap, and (if
    /// HistoryRetentionDays is set) drop anything older than that age. Called
    /// from the write path under the write lock; cheap when no rows need
    /// removing (single COUNT(*) + zero-row DELETEs).
    /// </summary>
    private void PruneIfNeeded(SqliteConnection conn)
    {
        // Date-based prune first so the row-count prune doesn't have to chase
        // a moving target.
        if (_retentionDays > 0)
        {
            using var ageCmd = conn.CreateCommand();
            var cutoff = DateTime.UtcNow.AddDays(-_retentionDays).ToString("O");
            ageCmd.CommandText = "DELETE FROM history WHERE timestamp_utc < @cut;";
            ageCmd.Parameters.AddWithValue("@cut", cutoff);
            ageCmd.ExecuteNonQuery();
        }

        using var cnt = conn.CreateCommand();
        cnt.CommandText = "SELECT COUNT(*) FROM history;";
        var total = (long)(cnt.ExecuteScalar() ?? 0L);
        if (total <= _retentionMaxRows) return;

        using var prune = conn.CreateCommand();
        prune.CommandText = """
            DELETE FROM history
            WHERE id IN (
                SELECT id FROM history ORDER BY id ASC LIMIT @cull
            );
            """;
        prune.Parameters.AddWithValue("@cull", total - _retentionMaxRows);
        prune.ExecuteNonQuery();
    }

    public async Task LogAsync(HistoryRecord record)
    {
        await _writeLock.WaitAsync().ConfigureAwait(false);
        try
        {
            long newId;
            using (var conn = Open())
            {
                using (var cmd = conn.CreateCommand())
                {
                    cmd.CommandText = """
                        INSERT INTO history
                            (timestamp_utc, engine, action, source_path, output_path,
                             source_bytes, output_bytes, duration_sec, success,
                             error_code, error_message, profile)
                        VALUES
                            (@ts, @engine, @action, @src, @out,
                             @sb, @ob, @dur, @ok,
                             @ec, @em, @prof);
                        SELECT last_insert_rowid();
                        """;
                    // Always store timestamps in UTC so local-zone shifts (DST,
                    // travel) don't reorder the displayed history.
                    var tsUtc = record.Timestamp.Kind == DateTimeKind.Utc
                        ? record.Timestamp
                        : record.Timestamp.ToUniversalTime();
                    cmd.Parameters.AddWithValue("@ts",     tsUtc.ToString("O"));
                    cmd.Parameters.AddWithValue("@engine", record.Engine);
                    cmd.Parameters.AddWithValue("@action", record.Action);
                    cmd.Parameters.AddWithValue("@src",    record.SourcePath);
                    cmd.Parameters.AddWithValue("@out",    (object?)record.OutputPath  ?? DBNull.Value);
                    cmd.Parameters.AddWithValue("@sb",     (object?)record.SourceBytes ?? DBNull.Value);
                    cmd.Parameters.AddWithValue("@ob",     (object?)record.OutputBytes ?? DBNull.Value);
                    cmd.Parameters.AddWithValue("@dur",    record.DurationSeconds);
                    cmd.Parameters.AddWithValue("@ok",     record.Success ? 1 : 0);
                    cmd.Parameters.AddWithValue("@ec",     (object?)record.ErrorCode    ?? DBNull.Value);
                    cmd.Parameters.AddWithValue("@em",     (object?)record.ErrorMessage ?? DBNull.Value);
                    cmd.Parameters.AddWithValue("@prof",   (object?)record.Profile      ?? DBNull.Value);
                    newId = (long)(cmd.ExecuteScalar() ?? 0L);
                }

                // Amortise the prune COUNT(*) over many writes so a hot batch
                // doesn't pay for it on every insert.
                if (Interlocked.Increment(ref _writesSinceLastPrune) >= 100)
                {
                    Interlocked.Exchange(ref _writesSinceLastPrune, 0);
                    try { PruneIfNeeded(conn); } catch { /* prune is best-effort */ }
                }
            }

            var stamped = record with { Id = newId };
            _ui.TryEnqueue(() =>
            {
                Recent.Insert(0, stamped);
                while (Recent.Count > RecentCap) Recent.RemoveAt(Recent.Count - 1);
            });
        }
        finally { _writeLock.Release(); }
    }

    public Task<IReadOnlyList<HistoryRecord>> QueryAsync(string? search = null, int? limit = 500)
        => Task.Run<IReadOnlyList<HistoryRecord>>(() =>
        {
            var rowLimit = Math.Clamp(limit ?? 500, 1, 10_000);
            var list = new List<HistoryRecord>();
            using var conn = Open();
            using var cmd = conn.CreateCommand();
            var where = string.IsNullOrWhiteSpace(search) ? "" : """
                WHERE engine LIKE @q OR action LIKE @q
                   OR source_path LIKE @q OR output_path LIKE @q OR profile LIKE @q
                """;
            cmd.CommandText = $"""
                SELECT id, timestamp_utc, engine, action, source_path, output_path,
                       source_bytes, output_bytes, duration_sec, success,
                       error_code, error_message, profile
                FROM history
                {where}
                ORDER BY id DESC
                LIMIT @lim;
                """;
            if (!string.IsNullOrWhiteSpace(search))
                cmd.Parameters.AddWithValue("@q", $"%{search}%");
            cmd.Parameters.AddWithValue("@lim", rowLimit);
            using var rdr = cmd.ExecuteReader();
            while (rdr.Read())
            {
                // Hostile timestamps from a hand-edited DB shouldn't crash the
                // entire load — fall back to UnixEpoch so the row is still
                // visible (and obvious as broken) instead of disappearing.
                DateTime ts;
                if (!DateTime.TryParse(rdr.GetString(1), null,
                        System.Globalization.DateTimeStyles.RoundtripKind, out ts))
                    ts = DateTime.UnixEpoch;

                list.Add(new HistoryRecord
                {
                    Id              = rdr.GetInt64(0),
                    Timestamp       = ts,
                    Engine          = rdr.GetString(2),
                    Action          = rdr.GetString(3),
                    SourcePath      = rdr.GetString(4),
                    OutputPath      = rdr.IsDBNull(5)  ? null : rdr.GetString(5),
                    SourceBytes     = rdr.IsDBNull(6)  ? null : rdr.GetInt64(6),
                    OutputBytes     = rdr.IsDBNull(7)  ? null : rdr.GetInt64(7),
                    DurationSeconds = rdr.GetDouble(8),
                    Success         = rdr.GetInt64(9) == 1,
                    ErrorCode       = rdr.IsDBNull(10) ? null : rdr.GetString(10),
                    ErrorMessage    = rdr.IsDBNull(11) ? null : rdr.GetString(11),
                    Profile         = rdr.IsDBNull(12) ? null : rdr.GetString(12),
                });
            }
            return list;
        });

    public Task<HistorySummary> SummarizeAsync(string? search = null) => Task.Run(() =>
    {
        using var conn = Open();
        using var cmd = conn.CreateCommand();
        var where = string.IsNullOrWhiteSpace(search) ? "" : """
            WHERE engine LIKE @q OR action LIKE @q
               OR source_path LIKE @q OR output_path LIKE @q OR profile LIKE @q
            """;
        cmd.CommandText = $"""
            SELECT
                COUNT(*),
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END),
                COALESCE(SUM(source_bytes), 0),
                COALESCE(SUM(output_bytes), 0),
                COALESCE(SUM(CASE
                    WHEN source_bytes IS NOT NULL AND output_bytes IS NOT NULL
                         AND source_bytes > output_bytes
                    THEN source_bytes - output_bytes
                    ELSE 0
                END), 0)
            FROM history
            {where};
            """;
        if (!string.IsNullOrWhiteSpace(search))
            cmd.Parameters.AddWithValue("@q", $"%{search}%");
        using var rdr = cmd.ExecuteReader();
        if (!rdr.Read())
            return new HistorySummary(0, 0, 0, 0, 0, 0);
        return new HistorySummary(
            TotalJobs:          (int)rdr.GetInt64(0),
            Succeeded:          rdr.IsDBNull(1) ? 0 : (int)rdr.GetInt64(1),
            Failed:             rdr.IsDBNull(2) ? 0 : (int)rdr.GetInt64(2),
            TotalSourceBytes:   rdr.GetInt64(3),
            TotalOutputBytes:   rdr.GetInt64(4),
            SpaceSavedBytes:    rdr.GetInt64(5));
    });

    public async Task DeleteAsync(long id)
    {
        await _writeLock.WaitAsync().ConfigureAwait(false);
        try
        {
            using (var conn = Open())
            using (var cmd = conn.CreateCommand())
            {
                cmd.CommandText = "DELETE FROM history WHERE id = @id;";
                cmd.Parameters.AddWithValue("@id", id);
                cmd.ExecuteNonQuery();
            }
            _ui.TryEnqueue(() =>
            {
                for (int i = Recent.Count - 1; i >= 0; i--)
                    if (Recent[i].Id == id) Recent.RemoveAt(i);
            });
        }
        finally { _writeLock.Release(); }
    }

    public async Task ClearAsync()
    {
        await _writeLock.WaitAsync().ConfigureAwait(false);
        try
        {
            using (var conn = Open())
            using (var cmd = conn.CreateCommand())
            {
                cmd.CommandText = "DELETE FROM history;";
                cmd.ExecuteNonQuery();
            }
            _ui.TryEnqueue(Recent.Clear);
        }
        finally { _writeLock.Release(); }
    }
}
