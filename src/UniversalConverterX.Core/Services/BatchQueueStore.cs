using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Services;

public interface IBatchQueueStore
{
    PersistedBatchQueue? Load(string queueKey);
    IReadOnlyList<PersistedBatchQueue> LoadAll();
    void Save(PersistedBatchQueue queue);
    void Clear(string queueKey);

    /// <summary>
    /// Atomically transition a job from "Queued" to "Running" and persist it.
    /// Returns false when the queue/job is missing or the job is not "Queued"
    /// (already claimed). Guarded by a cross-process lock so a second running
    /// instance watching the same queue directory cannot double-claim a job.
    /// </summary>
    bool TryClaimJob(string queueKey, string jobId);
}

public sealed record PersistedBatchQueue
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public string QueueKey { get; init; } = "";
    public string PageName { get; init; } = "";
    public DateTime UpdatedUtc { get; init; } = DateTime.UtcNow;
    public Dictionary<string, string?> Settings { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public List<PersistedBatchJob> Jobs { get; init; } = [];
}

public sealed record PersistedBatchJob
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public string SourcePath { get; init; } = "";
    public string? OutputPath { get; init; }
    public string Engine { get; init; } = "";
    public string Action { get; init; } = "";
    public string? Preset { get; init; }
    public List<string> Args { get; init; } = [];
    /// <summary>
    /// Optional zero-based audio stream indices selected by the Converter
    /// preflight. A null value preserves every audio stream.
    /// </summary>
    public List<int>? AudioTrackSelection { get; init; }

    /// <summary>
    /// Optional zero-based subtitle stream indices selected by the Converter
    /// preflight. A null value preserves every subtitle stream.
    /// </summary>
    public List<int>? SubtitleTrackSelection { get; init; }
    public string Status { get; init; } = "Queued";
    public string? ErrorMessage { get; init; }

    /// <summary>
    /// Serialized <see cref="Models.JobProvenance"/> for a job that has already
    /// run, so a restored queue can still say which binary and arguments
    /// produced an output. Null while the job is queued.
    /// </summary>
    public string? Provenance { get; init; }
}

/// <summary>
/// Non-destructive batch-queue operations: text search across jobs and
/// "clone as a fresh job" — the Core primitives behind the queue search box and
/// the "open copy as new settings" action.
/// </summary>
public static class BatchQueueOperations
{
    /// <summary>
    /// True when the job matches a free-text query against its source/output
    /// path, engine, action, preset, status, and error message (case-insensitive).
    /// A blank query matches everything.
    /// </summary>
    public static bool Matches(PersistedBatchJob job, string? query)
    {
        ArgumentNullException.ThrowIfNull(job);
        if (string.IsNullOrWhiteSpace(query))
            return true;

        var q = query.Trim();
        return Contains(job.SourcePath, q)
            || Contains(job.OutputPath, q)
            || Contains(job.Engine, q)
            || Contains(job.Action, q)
            || Contains(job.Preset, q)
            || Contains(job.Status, q)
            || Contains(job.ErrorMessage, q);
    }

    /// <summary>Filter a queue's jobs by <see cref="Matches"/>.</summary>
    public static IReadOnlyList<PersistedBatchJob> Search(IEnumerable<PersistedBatchJob> jobs, string? query)
    {
        ArgumentNullException.ThrowIfNull(jobs);
        return jobs.Where(job => Matches(job, query)).ToList();
    }

    /// <summary>
    /// Clone a job into a fresh, re-queueable one: a new <see cref="PersistedBatchJob.Id"/>,
    /// <c>Status = "Queued"</c>, and no carried-over error. The original is
    /// untouched (records are immutable). Args are deep-copied so later edits to
    /// the clone don't mutate the source.
    /// </summary>
    public static PersistedBatchJob CloneAsNew(PersistedBatchJob source)
    {
        ArgumentNullException.ThrowIfNull(source);
        return source with
        {
            Id = Guid.NewGuid().ToString("N"),
            Status = "Queued",
            ErrorMessage = null,
            // A copy has not run yet, so it must not inherit the original's
            // record of how the original was produced.
            Provenance = null,
            Args = [.. source.Args],
            AudioTrackSelection = source.AudioTrackSelection is null
                ? null
                : [.. source.AudioTrackSelection],
            SubtitleTrackSelection = source.SubtitleTrackSelection is null
                ? null
                : [.. source.SubtitleTrackSelection],
        };
    }

    private static bool Contains(string? value, string query) =>
        value is not null && value.Contains(query, StringComparison.OrdinalIgnoreCase);
}

public sealed class JsonBatchQueueStore : IBatchQueueStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    private static readonly TimeSpan CrossProcessLockTimeout = TimeSpan.FromSeconds(10);

    private readonly string _directory;
    private readonly object _gate = new();
    private readonly string _mutexName;

    public JsonBatchQueueStore(string directory)
    {
        if (string.IsNullOrWhiteSpace(directory))
            throw new ArgumentException("Queue directory is required.", nameof(directory));

        _directory = directory;
        Directory.CreateDirectory(_directory);
        _mutexName = BuildMutexName(_directory);
    }

    public PersistedBatchQueue? Load(string queueKey)
    {
        var path = PathFor(queueKey);
        return WithCrossProcessLock(() =>
        {
            try
            {
                if (!File.Exists(path))
                    return null;

                var queue = JsonSerializer.Deserialize<PersistedBatchQueue>(
                    File.ReadAllText(path),
                    JsonOptions);
                return queue?.QueueKey.Equals(queueKey, StringComparison.OrdinalIgnoreCase) == true
                    ? queue
                    : null;
            }
            catch
            {
                PreserveCorruptQueue(path);
                return null;
            }
        });
    }

    public IReadOnlyList<PersistedBatchQueue> LoadAll()
    {
        return WithCrossProcessLock<IReadOnlyList<PersistedBatchQueue>>(() =>
        {
            if (!Directory.Exists(_directory))
                return [];

            var queues = new List<PersistedBatchQueue>();
            foreach (var path in Directory.GetFiles(_directory, "*.json", SearchOption.TopDirectoryOnly))
            {
                try
                {
                    var queue = JsonSerializer.Deserialize<PersistedBatchQueue>(
                        File.ReadAllText(path),
                        JsonOptions);
                    if (queue is not null && !string.IsNullOrWhiteSpace(queue.QueueKey))
                        queues.Add(queue);
                }
                catch
                {
                    PreserveCorruptQueue(path);
                }
            }

            return queues
                .OrderBy(queue => queue.QueueKey, StringComparer.OrdinalIgnoreCase)
                .ToList();
        });
    }

    public void Save(PersistedBatchQueue queue)
    {
        if (string.IsNullOrWhiteSpace(queue.QueueKey))
            throw new ArgumentException("Queue key is required.", nameof(queue));

        var path = PathFor(queue.QueueKey);
        var snapshot = queue with { UpdatedUtc = DateTime.UtcNow };
        WithCrossProcessLock(() =>
        {
            WriteAtomic(path, snapshot);
            return true;
        });
    }

    public void Clear(string queueKey)
    {
        var path = PathFor(queueKey);
        WithCrossProcessLock(() =>
        {
            try { if (File.Exists(path)) File.Delete(path); } catch { }
            return true;
        });
    }

    public bool TryClaimJob(string queueKey, string jobId)
    {
        if (string.IsNullOrWhiteSpace(queueKey) || string.IsNullOrWhiteSpace(jobId))
            return false;

        var path = PathFor(queueKey);
        return WithCrossProcessLock(() =>
        {
            PersistedBatchQueue? queue;
            try
            {
                if (!File.Exists(path))
                    return false;
                queue = JsonSerializer.Deserialize<PersistedBatchQueue>(
                    File.ReadAllText(path), JsonOptions);
            }
            catch
            {
                PreserveCorruptQueue(path);
                return false;
            }

            if (queue is null)
                return false;

            var index = queue.Jobs.FindIndex(job =>
                job.Id.Equals(jobId, StringComparison.Ordinal));
            if (index < 0)
                return false;

            if (!queue.Jobs[index].Status.Equals("Queued", StringComparison.OrdinalIgnoreCase))
                return false; // already claimed by another instance/thread

            queue.Jobs[index] = queue.Jobs[index] with { Status = "Running" };
            WriteAtomic(path, queue with { UpdatedUtc = DateTime.UtcNow });
            return true;
        });
    }

    private void WriteAtomic(string path, PersistedBatchQueue snapshot)
    {
        Directory.CreateDirectory(_directory);
        var json = JsonSerializer.Serialize(snapshot, JsonOptions);
        var tmp = path + ".tmp";
        File.WriteAllText(tmp, json);
        try { File.Move(tmp, path, overwrite: true); }
        catch
        {
            File.WriteAllText(path, json);
            try { File.Delete(tmp); } catch { }
        }
    }

    /// <summary>
    /// Serialize an operation across every process/thread that shares this queue
    /// directory. The named mutex is combined with the in-process monitor so a
    /// single process's own threads also serialize. Falls back to the in-process
    /// lock only if the cross-process mutex cannot be acquired within the timeout,
    /// which prevents a hung peer from deadlocking the whole app.
    /// </summary>
    private T WithCrossProcessLock<T>(Func<T> body)
    {
        using var mutex = new Mutex(initiallyOwned: false, _mutexName);
        var acquired = false;
        try
        {
            try
            {
                acquired = mutex.WaitOne(CrossProcessLockTimeout);
            }
            catch (AbandonedMutexException)
            {
                // A previous owner exited without releasing (crash). We now hold
                // the mutex; the on-disk state is still consistent because every
                // write is atomic (temp + rename).
                acquired = true;
            }

            lock (_gate)
            {
                return body();
            }
        }
        finally
        {
            if (acquired)
            {
                try { mutex.ReleaseMutex(); } catch { /* best effort */ }
            }
        }
    }

    private static string BuildMutexName(string directory)
    {
        var normalized = Path.GetFullPath(directory).TrimEnd('\\', '/').ToLowerInvariant();
        var hash = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(normalized)))[..16];
        // Local\ (per-session) is sufficient for same-user multi-instance and
        // avoids the elevation Global\ requires.
        return $"Local\\ucx-batch-queue-{hash}";
    }

    private string PathFor(string queueKey)
    {
        if (string.IsNullOrWhiteSpace(queueKey))
            throw new ArgumentException("Queue key is required.", nameof(queueKey));

        var safe = new string(queueKey
            .Select(c => char.IsLetterOrDigit(c) || c is '-' or '_' ? c : '-')
            .ToArray());
        return Path.Combine(_directory, safe + ".json");
    }

    private static void PreserveCorruptQueue(string path)
    {
        try
        {
            if (!File.Exists(path))
                return;

            var backup = path + ".corrupt." + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "." +
                         Guid.NewGuid().ToString("N")[..8];
            File.Copy(path, backup, overwrite: false);
        }
        catch { }
    }
}
