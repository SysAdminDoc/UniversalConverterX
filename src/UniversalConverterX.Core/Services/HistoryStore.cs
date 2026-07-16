using System.Globalization;
using Microsoft.Data.Sqlite;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// A conversion-history row without any UI-framework dependencies.
/// </summary>
public sealed record ConversionHistoryEntry
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
}

public sealed record ConversionHistorySummary(
    int TotalJobs,
    int Succeeded,
    int Failed,
    long TotalSourceBytes,
    long TotalOutputBytes,
    long SpaceSavedBytes);

/// <summary>
/// Headless SQLite persistence for conversion history. Callers supply the
/// database path so tests, the desktop app, and future CLI reporting can use
/// the same implementation without depending on WinUI or global app folders.
/// </summary>
public sealed class HistoryStore : IDisposable
{
    private static readonly object ProviderLock = new();
    private static bool _providerInitialized;

    private readonly string _dbPath;
    private readonly int _retentionMaxRows;
    private readonly int _retentionDays;
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private bool _disposed;

    public HistoryStore(string databasePath, int retentionMaxRows = 10_000, int retentionDays = 0)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(databasePath);

        _dbPath = Path.GetFullPath(databasePath);
        _retentionMaxRows = Math.Max(1, retentionMaxRows);
        _retentionDays = Math.Max(0, retentionDays);

        var directory = Path.GetDirectoryName(_dbPath)
            ?? throw new ArgumentException("History database path has no directory.", nameof(databasePath));
        Directory.CreateDirectory(directory);
        EnsureSchema();
    }

    public async Task<long> AddAsync(
        ConversionHistoryEntry entry,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(entry);
        ObjectDisposedException.ThrowIf(_disposed, this);

        await _writeLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            using var connection = Open();
            using var transaction = connection.BeginTransaction();
            using var command = connection.CreateCommand();
            command.Transaction = transaction;
            command.CommandText = """
                INSERT INTO history
                    (timestamp_utc, engine, action, source_path, output_path,
                     source_bytes, output_bytes, duration_sec, success,
                     error_code, error_message, profile, rerun_json)
                VALUES
                    (@ts, @engine, @action, @src, @out,
                     @sb, @ob, @dur, @ok,
                     @ec, @em, @prof, @rerun);
                SELECT last_insert_rowid();
                """;
            var timestamp = entry.Timestamp.Kind == DateTimeKind.Utc
                ? entry.Timestamp
                : entry.Timestamp.ToUniversalTime();
            command.Parameters.AddWithValue("@ts", timestamp.ToString("O"));
            command.Parameters.AddWithValue("@engine", entry.Engine);
            command.Parameters.AddWithValue("@action", entry.Action);
            command.Parameters.AddWithValue("@src", entry.SourcePath);
            command.Parameters.AddWithValue("@out", (object?)entry.OutputPath ?? DBNull.Value);
            command.Parameters.AddWithValue("@sb", (object?)entry.SourceBytes ?? DBNull.Value);
            command.Parameters.AddWithValue("@ob", (object?)entry.OutputBytes ?? DBNull.Value);
            command.Parameters.AddWithValue("@dur", entry.DurationSeconds);
            command.Parameters.AddWithValue("@ok", entry.Success ? 1 : 0);
            command.Parameters.AddWithValue("@ec", (object?)entry.ErrorCode ?? DBNull.Value);
            command.Parameters.AddWithValue("@em", (object?)entry.ErrorMessage ?? DBNull.Value);
            command.Parameters.AddWithValue("@prof", (object?)entry.Profile ?? DBNull.Value);
            command.Parameters.AddWithValue("@rerun", (object?)entry.RerunParameters ?? DBNull.Value);
            var id = (long)(command.ExecuteScalar() ?? 0L);

            Prune(connection, transaction);
            transaction.Commit();
            return id;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public Task<IReadOnlyList<ConversionHistoryEntry>> QueryAsync(
        string? search = null,
        int? limit = 500,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return Task.Run<IReadOnlyList<ConversionHistoryEntry>>(
            () => Query(search, limit),
            cancellationToken);
    }

    public Task<ConversionHistoryEntry?> GetAsync(
        long id,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return Task.Run(() => Get(id), cancellationToken);
    }

    public Task<ConversionHistorySummary> SummarizeAsync(
        string? search = null,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return Task.Run(() => Summarize(search), cancellationToken);
    }

    public async Task DeleteAsync(long id, CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _writeLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            using var connection = Open();
            using var command = connection.CreateCommand();
            command.CommandText = "DELETE FROM history WHERE id = @id;";
            command.Parameters.AddWithValue("@id", id);
            command.ExecuteNonQuery();
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public async Task ClearAsync(CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        await _writeLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            using var connection = Open();
            using var command = connection.CreateCommand();
            command.CommandText = "DELETE FROM history;";
            command.ExecuteNonQuery();
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        _writeLock.Dispose();
    }

    private IReadOnlyList<ConversionHistoryEntry> Query(string? search, int? limit)
    {
        var rowLimit = Math.Clamp(limit ?? 500, 1, 10_000);
        var entries = new List<ConversionHistoryEntry>();
        using var connection = Open();
        using var command = connection.CreateCommand();
        var where = string.IsNullOrWhiteSpace(search) ? "" : """
            WHERE engine LIKE @q OR action LIKE @q
               OR source_path LIKE @q OR output_path LIKE @q OR profile LIKE @q
            """;
        command.CommandText = $"""
            SELECT id, timestamp_utc, engine, action, source_path, output_path,
                   source_bytes, output_bytes, duration_sec, success,
                   error_code, error_message, profile, rerun_json
            FROM history
            {where}
            ORDER BY id DESC
            LIMIT @lim;
            """;
        if (!string.IsNullOrWhiteSpace(search))
            command.Parameters.AddWithValue("@q", $"%{search}%");
        command.Parameters.AddWithValue("@lim", rowLimit);

        using var reader = command.ExecuteReader();
        while (reader.Read())
            entries.Add(ReadEntry(reader));

        return entries;
    }

    private ConversionHistoryEntry? Get(long id)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, timestamp_utc, engine, action, source_path, output_path,
                   source_bytes, output_bytes, duration_sec, success,
                   error_code, error_message, profile, rerun_json
            FROM history
            WHERE id = @id
            LIMIT 1;
            """;
        command.Parameters.AddWithValue("@id", id);
        using var reader = command.ExecuteReader();
        return reader.Read() ? ReadEntry(reader) : null;
    }

    private static ConversionHistoryEntry ReadEntry(SqliteDataReader reader)
    {
        if (!DateTime.TryParse(
                reader.GetString(1),
                CultureInfo.InvariantCulture,
                DateTimeStyles.RoundtripKind,
                out var timestamp))
        {
            timestamp = DateTime.UnixEpoch;
        }

        return new ConversionHistoryEntry
        {
            Id = reader.GetInt64(0),
            Timestamp = timestamp,
            Engine = reader.GetString(2),
            Action = reader.GetString(3),
            SourcePath = reader.GetString(4),
            OutputPath = reader.IsDBNull(5) ? null : reader.GetString(5),
            SourceBytes = reader.IsDBNull(6) ? null : reader.GetInt64(6),
            OutputBytes = reader.IsDBNull(7) ? null : reader.GetInt64(7),
            DurationSeconds = reader.GetDouble(8),
            Success = reader.GetInt64(9) == 1,
            ErrorCode = reader.IsDBNull(10) ? null : reader.GetString(10),
            ErrorMessage = reader.IsDBNull(11) ? null : reader.GetString(11),
            Profile = reader.IsDBNull(12) ? null : reader.GetString(12),
            RerunParameters = reader.IsDBNull(13) ? null : reader.GetString(13),
        };
    }

    private ConversionHistorySummary Summarize(string? search)
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        var where = string.IsNullOrWhiteSpace(search) ? "" : """
            WHERE engine LIKE @q OR action LIKE @q
               OR source_path LIKE @q OR output_path LIKE @q OR profile LIKE @q
            """;
        command.CommandText = $"""
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
            command.Parameters.AddWithValue("@q", $"%{search}%");

        using var reader = command.ExecuteReader();
        if (!reader.Read())
            return new ConversionHistorySummary(0, 0, 0, 0, 0, 0);

        return new ConversionHistorySummary(
            TotalJobs: (int)reader.GetInt64(0),
            Succeeded: reader.IsDBNull(1) ? 0 : (int)reader.GetInt64(1),
            Failed: reader.IsDBNull(2) ? 0 : (int)reader.GetInt64(2),
            TotalSourceBytes: reader.GetInt64(3),
            TotalOutputBytes: reader.GetInt64(4),
            SpaceSavedBytes: reader.GetInt64(5));
    }

    private void EnsureSchema()
    {
        using var connection = Open();
        using var command = connection.CreateCommand();
        command.CommandText = """
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
                profile         TEXT,
                rerun_json      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_history_ts     ON history(timestamp_utc);
            CREATE INDEX IF NOT EXISTS idx_history_engine ON history(engine);
            CREATE INDEX IF NOT EXISTS idx_history_id     ON history(id DESC);
            """;
        command.ExecuteNonQuery();
        EnsureColumn(connection, "rerun_json", "TEXT");
    }

    private static void EnsureColumn(SqliteConnection connection, string columnName, string declaration)
    {
        var exists = false;
        using (var inspect = connection.CreateCommand())
        {
            inspect.CommandText = "PRAGMA table_info(history);";
            using var reader = inspect.ExecuteReader();
            while (reader.Read())
            {
                if (!reader.GetString(1).Equals(columnName, StringComparison.OrdinalIgnoreCase))
                    continue;
                exists = true;
                break;
            }
        }
        if (exists)
            return;

        using var alter = connection.CreateCommand();
        alter.CommandText = $"ALTER TABLE history ADD COLUMN {columnName} {declaration};";
        alter.ExecuteNonQuery();
    }

    private SqliteConnection Open()
    {
        EnsureSqliteProvider();
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = _dbPath,
        }.ToString());
        connection.Open();

        using var command = connection.CreateCommand();
        command.CommandText = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;";
        try
        {
            command.ExecuteNonQuery();
        }
        catch (SqliteException)
        {
            // WAL is an optimization and is unsupported by a few network filesystems.
        }

        return connection;
    }

    private void Prune(SqliteConnection connection, SqliteTransaction transaction)
    {
        if (_retentionDays > 0)
        {
            using var ageCommand = connection.CreateCommand();
            ageCommand.Transaction = transaction;
            ageCommand.CommandText = "DELETE FROM history WHERE timestamp_utc < @cutoff;";
            ageCommand.Parameters.AddWithValue(
                "@cutoff",
                DateTime.UtcNow.AddDays(-_retentionDays).ToString("O"));
            ageCommand.ExecuteNonQuery();
        }

        using var countCommand = connection.CreateCommand();
        countCommand.Transaction = transaction;
        countCommand.CommandText = "SELECT COUNT(*) FROM history;";
        var count = (long)(countCommand.ExecuteScalar() ?? 0L);
        if (count <= _retentionMaxRows)
            return;

        using var rowCommand = connection.CreateCommand();
        rowCommand.Transaction = transaction;
        rowCommand.CommandText = """
            DELETE FROM history
            WHERE id IN (
                SELECT id FROM history ORDER BY id ASC LIMIT @count
            );
            """;
        rowCommand.Parameters.AddWithValue("@count", count - _retentionMaxRows);
        rowCommand.ExecuteNonQuery();
    }

    private static void EnsureSqliteProvider()
    {
        lock (ProviderLock)
        {
            if (_providerInitialized)
                return;

            SQLitePCL.raw.SetProvider(new SQLitePCL.SQLite3Provider_winsqlite3());
            _providerInitialized = true;
        }
    }
}
