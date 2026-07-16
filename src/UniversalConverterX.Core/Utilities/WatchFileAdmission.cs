using System.Collections.Concurrent;

namespace UniversalConverterX.Core.Utilities;

public readonly record struct WatchFileObservation(long Length, long LastWriteTimeUtcTicks);

/// <summary>Tracks consecutive metadata reads while a watched file settles.</summary>
public sealed class FileStabilityTracker
{
    private readonly int _requiredMatchingReads;
    private WatchFileObservation? _last;
    private int _matchingReads;

    public FileStabilityTracker(int requiredMatchingReads = 2)
    {
        if (requiredMatchingReads < 2)
            throw new ArgumentOutOfRangeException(nameof(requiredMatchingReads));
        _requiredMatchingReads = requiredMatchingReads;
    }

    public bool Observe(WatchFileObservation observation)
    {
        if (_last == observation)
            _matchingReads++;
        else
            _matchingReads = 1;

        _last = observation;
        return _matchingReads >= _requiredMatchingReads;
    }
}

/// <summary>
/// Suppresses concurrent and repeated FileSystemWatcher notifications without
/// retaining an unbounded set for long-running watch sessions.
/// </summary>
public sealed class WatchFileAdmission
{
    private readonly int _seenCapacity;
    private readonly ConcurrentDictionary<string, byte> _inFlight;
    private readonly ConcurrentDictionary<string, byte> _seen;
    private readonly ConcurrentQueue<string> _seenOrder = new();
    private readonly ConcurrentDictionary<string, byte> _suppressedOutputs;
    private readonly ConcurrentQueue<string> _suppressedOrder = new();

    public WatchFileAdmission(int seenCapacity = 4096, StringComparer? pathComparer = null)
    {
        if (seenCapacity < 1)
            throw new ArgumentOutOfRangeException(nameof(seenCapacity));

        _seenCapacity = seenCapacity;
        pathComparer ??= OperatingSystem.IsWindows()
            ? StringComparer.OrdinalIgnoreCase
            : StringComparer.Ordinal;
        _inFlight = new ConcurrentDictionary<string, byte>(pathComparer);
        _seen = new ConcurrentDictionary<string, byte>(pathComparer);
        _suppressedOutputs = new ConcurrentDictionary<string, byte>(pathComparer);
    }

    public int InFlightCount => _inFlight.Count;
    public int RememberedCount => _seen.Count + _suppressedOutputs.Count;

    public bool TryBegin(string path) => _inFlight.TryAdd(NormalizePath(path), 0);

    public void End(string path) => _inFlight.TryRemove(NormalizePath(path), out _);

    public bool IsSuppressedOutput(string path) => _suppressedOutputs.ContainsKey(NormalizePath(path));

    public void SuppressOutput(string path)
    {
        var normalized = NormalizePath(path);
        if (!_suppressedOutputs.TryAdd(normalized, 0))
            return;

        _suppressedOrder.Enqueue(normalized);
        while (_suppressedOutputs.Count > _seenCapacity && _suppressedOrder.TryDequeue(out var expired))
            _suppressedOutputs.TryRemove(expired, out _);
    }

    public bool TryRemember(string path, WatchFileObservation observation)
    {
        var key = Fingerprint(path, observation);
        if (!_seen.TryAdd(key, 0))
            return false;

        _seenOrder.Enqueue(key);
        while (_seen.Count > _seenCapacity && _seenOrder.TryDequeue(out var expired))
            _seen.TryRemove(expired, out _);
        return true;
    }

    private static string Fingerprint(string path, WatchFileObservation observation) =>
        $"{NormalizePath(path)}\0{observation.Length}\0{observation.LastWriteTimeUtcTicks}";

    private static string NormalizePath(string path)
    {
        try { return Path.GetFullPath(path); }
        catch { return path; }
    }
}
