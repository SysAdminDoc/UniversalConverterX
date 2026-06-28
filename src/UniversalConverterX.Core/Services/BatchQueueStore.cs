using System.Text.Json;
using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Services;

public interface IBatchQueueStore
{
    PersistedBatchQueue? Load(string queueKey);
    void Save(PersistedBatchQueue queue);
    void Clear(string queueKey);
}

public sealed record PersistedBatchQueue
{
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
    public string Status { get; init; } = "Queued";
    public string? ErrorMessage { get; init; }
}

public sealed class JsonBatchQueueStore : IBatchQueueStore
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    private readonly string _directory;
    private readonly object _gate = new();

    public JsonBatchQueueStore(string directory)
    {
        if (string.IsNullOrWhiteSpace(directory))
            throw new ArgumentException("Queue directory is required.", nameof(directory));

        _directory = directory;
        Directory.CreateDirectory(_directory);
    }

    public PersistedBatchQueue? Load(string queueKey)
    {
        var path = PathFor(queueKey);
        lock (_gate)
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
        }
    }

    public void Save(PersistedBatchQueue queue)
    {
        if (string.IsNullOrWhiteSpace(queue.QueueKey))
            throw new ArgumentException("Queue key is required.", nameof(queue));

        var path = PathFor(queue.QueueKey);
        var snapshot = queue with { UpdatedUtc = DateTime.UtcNow };
        lock (_gate)
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
    }

    public void Clear(string queueKey)
    {
        var path = PathFor(queueKey);
        lock (_gate)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch { }
        }
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
