using System.Collections.Concurrent;
using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.UI.Dispatching;

namespace UniversalConverterX.UI.Services;

public enum WatchAction { Convert, Compress }

public enum WatchEventStatus { Picked, Running, Done, Failed, Skipped }

public sealed record WatchProfile
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public string Name { get; init; } = "Watch";
    public string Path { get; init; } = "";

    /// <summary>Semicolon-delimited globs, e.g. "*.mp4;*.mov".</summary>
    public string Filter { get; init; } = "*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v";
    public WatchAction Action { get; init; } = WatchAction.Compress;

    /// <summary>Used by Convert: target container ext (e.g. "mp4"). Null for Compress.</summary>
    public string? TargetFormat { get; init; }

    /// <summary>Used by Compress: videocrush preset tag (e.g. "web-1080p"). Null for Convert.</summary>
    public string? Preset { get; init; }

    /// <summary>Optional output directory; null = drop next to source with `_out` suffix.</summary>
    public string? OutputDir { get; init; }

    public bool IsEnabled { get; init; } = true;
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
}

public sealed class WatchEvent
{
    public string ProfileId { get; init; } = "";
    public string ProfileName { get; init; } = "";
    public string FilePath { get; init; } = "";
    public DateTime Timestamp { get; init; } = DateTime.Now;
    public WatchEventStatus Status { get; set; }
    public string? Message { get; set; }

    public string Display =>
        $"[{Timestamp:HH:mm:ss}] {ProfileName} -> {System.IO.Path.GetFileName(FilePath)} -- {Status}" +
        (string.IsNullOrEmpty(Message) ? "" : $" ({Message})");
}

public interface IWatchFolderService
{
    ObservableCollection<WatchProfile> Profiles { get; }
    ObservableCollection<WatchEvent> Recent { get; }
    void Add(WatchProfile profile);
    void Update(WatchProfile profile);
    void Remove(string id);
    void SetEnabled(string id, bool enabled);
    void Save();
}

public sealed class WatchFolderService : IWatchFolderService, IDisposable
{
    private const int RecentEventCap = 200;
    private static readonly TimeSpan StableCheckInterval = TimeSpan.FromSeconds(2);
    private const int StableSamplesNeeded = 3;
    private static readonly TimeSpan StableTimeout = TimeSpan.FromMinutes(15);

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly DispatcherQueue _ui;
    private readonly string _configPath;
    private readonly Dictionary<string, FileSystemWatcher> _watchers = [];
    private readonly Dictionary<string, CancellationTokenSource> _profileCts = [];
    private readonly ConcurrentDictionary<string, byte> _processing = new(
        OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal);
    private readonly object _saveLock = new();
    /// <summary>
    /// Trips when the whole service is being shut down. Linked into every
    /// per-profile CTS so disposing the service cancels any running sidecar
    /// rather than leaving orphan processes after app exit.
    /// </summary>
    private readonly CancellationTokenSource _shutdownCts = new();

    public ObservableCollection<WatchProfile> Profiles { get; } = [];
    public ObservableCollection<WatchEvent> Recent { get; } = [];

    public WatchFolderService(ISidecarRunner runner, IHistoryService history)
    {
        _runner = runner;
        _history = history;
        // Marshal back to whichever thread constructed this service (typically UI).
        _ui = DispatcherQueue.GetForCurrentThread()
              ?? throw new InvalidOperationException(
                     "WatchFolderService must be constructed on a thread with a DispatcherQueue.");

        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX");
        Directory.CreateDirectory(dir);
        _configPath = Path.Combine(dir, "watches.json");

        Load();
        foreach (var p in Profiles)
            if (p.IsEnabled) StartWatcher(p);
    }

    // ── Persistence ─────────────────────────────────────────────────────────

    private void Load()
    {
        try
        {
            if (!File.Exists(_configPath)) return;
            var json = File.ReadAllText(_configPath);
            var loaded = JsonSerializer.Deserialize<List<WatchProfile>>(json, JsonOpts);
            if (loaded is null) return;
            Profiles.Clear();
            foreach (var p in loaded) Profiles.Add(p);
        }
        catch
        {
            // Corrupt config -- start fresh; user can re-add. Never block app launch.
        }
    }

    public void Save()
    {
        // Snapshot under the UI thread (where Profiles lives) and serialize on a
        // worker so a noisy Watch Folder profile add/remove storm doesn't stutter
        // the navigation animation.
        var snapshot = Profiles.ToList();
        Task.Run(() =>
        {
            lock (_saveLock)
            {
                try
                {
                    var json = JsonSerializer.Serialize(snapshot, JsonOpts);
                    // Atomic write so a crash mid-Save doesn't leave a half-empty
                    // watches.json that the next launch can't parse.
                    var tmp = _configPath + ".tmp";
                    File.WriteAllText(tmp, json);
                    try { File.Move(tmp, _configPath, overwrite: true); }
                    catch
                    {
                        File.WriteAllText(_configPath, json);
                        try { File.Delete(tmp); } catch { }
                    }
                }
                catch { /* best-effort persistence */ }
            }
        });
    }

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    // ── Public mutators ─────────────────────────────────────────────────────

    public void Add(WatchProfile profile)
    {
        Profiles.Add(profile);
        Save();
        if (profile.IsEnabled) StartWatcher(profile);
    }

    public void Update(WatchProfile profile)
    {
        var idx = -1;
        for (int i = 0; i < Profiles.Count; i++)
            if (Profiles[i].Id == profile.Id) { idx = i; break; }
        if (idx < 0) return;
        StopWatcher(profile.Id);
        Profiles[idx] = profile;
        Save();
        if (profile.IsEnabled) StartWatcher(profile);
    }

    public void Remove(string id)
    {
        StopWatcher(id);
        for (int i = Profiles.Count - 1; i >= 0; i--)
            if (Profiles[i].Id == id) Profiles.RemoveAt(i);
        Save();
    }

    public void SetEnabled(string id, bool enabled)
    {
        for (int i = 0; i < Profiles.Count; i++)
        {
            if (Profiles[i].Id != id) continue;
            var p = Profiles[i] with { IsEnabled = enabled };
            Profiles[i] = p;
            if (enabled) StartWatcher(p);
            else         StopWatcher(id);
            Save();
            return;
        }
    }

    public void Dispose()
    {
        try { _shutdownCts.Cancel(); } catch { }
        foreach (var w in _watchers.Values)
        {
            try { w.EnableRaisingEvents = false; w.Dispose(); } catch { }
        }
        _watchers.Clear();
        foreach (var cts in _profileCts.Values)
        {
            try { cts.Cancel(); cts.Dispose(); } catch { }
        }
        _profileCts.Clear();
        _shutdownCts.Dispose();
    }

    // ── Watcher lifecycle ───────────────────────────────────────────────────

    private void StartWatcher(WatchProfile profile)
    {
        StopWatcher(profile.Id); // idempotent

        if (!Directory.Exists(profile.Path))
        {
            PostEvent(profile, "(folder missing)", WatchEventStatus.Failed,
                      $"Folder does not exist: {profile.Path}");
            return;
        }

        FileSystemWatcher fsw;
        try
        {
            fsw = new FileSystemWatcher(profile.Path)
            {
                IncludeSubdirectories = false,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.Size,
                EnableRaisingEvents = true,
            };
        }
        catch (Exception ex)
        {
            // FileSystemWatcher throws on UNC paths without permission, on
            // certain network drives, and when the path is a CD/DVD root —
            // surface the failure in the event log instead of crashing.
            PostEvent(profile, profile.Path, WatchEventStatus.Failed,
                      $"Could not watch folder: {ex.Message}");
            return;
        }
        fsw.Created += (_, e) => OnArrival(profile, e.FullPath);
        fsw.Renamed += (_, e) => OnArrival(profile, e.FullPath);
        // The Error event fires when the buffer overflows (too many fast
        // events) — log it so the user knows files may have been missed.
        fsw.Error += (_, e) =>
        {
            PostEvent(profile, profile.Path, WatchEventStatus.Failed,
                      $"Watcher buffer overflow: {e.GetException().Message}. Some files may have been missed.");
        };
        _watchers[profile.Id] = fsw;

        // Per-profile CTS lets SetEnabled(false) abort any running sidecar
        // for this profile rather than leaving the job running until natural
        // completion. Linked to _shutdownCts so app exit also cancels.
        _profileCts[profile.Id] = CancellationTokenSource.CreateLinkedTokenSource(_shutdownCts.Token);
    }

    private void StopWatcher(string id)
    {
        if (_watchers.TryGetValue(id, out var fsw))
        {
            try { fsw.EnableRaisingEvents = false; fsw.Dispose(); } catch { }
            _watchers.Remove(id);
        }
        if (_profileCts.TryGetValue(id, out var cts))
        {
            try { cts.Cancel(); cts.Dispose(); } catch { }
            _profileCts.Remove(id);
        }
    }

    private void OnArrival(WatchProfile profile, string path)
    {
        if (!MatchesFilter(profile.Filter, path)) return;
        if (!_processing.TryAdd(path, 0)) return; // already in-flight
        var profileToken = _profileCts.TryGetValue(profile.Id, out var startingCts)
            ? startingCts.Token
            : _shutdownCts.Token;

        _ = Task.Run(async () =>
        {
            try
            {
                if (!await WaitForStableAsync(path, profileToken)) {
                    PostEvent(profile, path, WatchEventStatus.Skipped, "file never settled");
                    return;
                }
                profileToken.ThrowIfCancellationRequested();
                PostEvent(profile, path, WatchEventStatus.Picked, null);

                var (tool, args, output) = BuildJob(profile, path);
                if (tool is null)
                {
                    PostEvent(profile, path, WatchEventStatus.Skipped, "no tool resolved");
                    return;
                }

                PostEvent(profile, path, WatchEventStatus.Running, $"{tool} -> {Path.GetFileName(output)}");
                var startedAt = DateTime.UtcNow;
                // Use the per-profile cancellation token so disabling or
                // removing the watch profile aborts the in-flight job instead
                // of letting it run to completion. Falls back to the shutdown
                // token if the profile was already removed (race).
                var result = await _runner.RunAsync(tool, args!, null, null, profileToken);
                PostEvent(profile, path,
                          result.Success ? WatchEventStatus.Done : WatchEventStatus.Failed,
                          result.Success ? Path.GetFileName(output)
                                         : (result.ErrorMessage ?? result.ErrorCode));

                // Append to the persistent history log so the dashboard can show
                // every job the watcher fired off, with size deltas for the savings counter.
                long? srcBytes = TryFileSize(path);
                long? outBytes = result.Success ? (result.SizeBytes ?? TryFileSize(output)) : null;
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp        = startedAt,
                    Engine           = tool,
                    Action           = profile.Action == WatchAction.Compress ? "compress" : "convert",
                    SourcePath       = path,
                    OutputPath       = result.Success ? output : null,
                    SourceBytes      = srcBytes,
                    OutputBytes      = outBytes,
                    DurationSeconds  = (DateTime.UtcNow - startedAt).TotalSeconds,
                    Success          = result.Success,
                    ErrorCode        = result.ErrorCode,
                    ErrorMessage     = result.ErrorMessage,
                    Profile          = profile.Action == WatchAction.Compress ? profile.Preset : profile.TargetFormat,
                });
            }
            catch (OperationCanceledException)
            {
                if (!_shutdownCts.IsCancellationRequested)
                    PostEvent(profile, path, WatchEventStatus.Skipped, "watch cancelled");
            }
            catch (Exception ex)
            {
                PostEvent(profile, path, WatchEventStatus.Failed, ex.Message);
            }
            finally
            {
                _processing.TryRemove(path, out _);
            }
        });
    }

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; }
        catch { return null; }
    }

    private static bool MatchesFilter(string filter, string path)
    {
        if (string.IsNullOrWhiteSpace(filter)) return true;
        var name = Path.GetFileName(path);
        foreach (var glob in filter.Split(';', StringSplitOptions.RemoveEmptyEntries
                                            | StringSplitOptions.TrimEntries))
        {
            if (LikeMatch(name, glob)) return true;
        }
        return false;
    }

    // Glob -> compiled regex cache. A hot folder (e.g. a Watch Folder picking
    // up a 1000-frame image sequence) used to recompile the same pattern per
    // file; we now build it once and reuse.
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<string, System.Text.RegularExpressions.Regex> _globCache = new();

    /// <summary>Glob match supporting '*' and '?' (case-insensitive).</summary>
    private static bool LikeMatch(string text, string pattern)
    {
        var rx = _globCache.GetOrAdd(pattern, BuildGlob);
        return rx.IsMatch(text);
    }

    private static System.Text.RegularExpressions.Regex BuildGlob(string pattern)
    {
        var sb = new System.Text.StringBuilder("^");
        foreach (var c in pattern)
        {
            sb.Append(c switch
            {
                '*' => ".*",
                '?' => ".",
                _ => System.Text.RegularExpressions.Regex.Escape(c.ToString()),
            });
        }
        sb.Append('$');
        return new System.Text.RegularExpressions.Regex(
            sb.ToString(),
            System.Text.RegularExpressions.RegexOptions.IgnoreCase
            | System.Text.RegularExpressions.RegexOptions.Compiled,
            // Bound runtime so a pathological pattern like "**?**" can't pin a CPU
            // core for an unbounded time on hostile filenames.
            TimeSpan.FromMilliseconds(250));
    }

    /// <summary>Wait until file size hasn't changed for several samples or timeout.</summary>
    private static async Task<bool> WaitForStableAsync(string path, CancellationToken ct)
    {
        var lastSize = -1L;
        var sameCount = 0;
        var deadline = DateTime.UtcNow + StableTimeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                var size = new FileInfo(path).Length;
                if (size == lastSize) sameCount++;
                else                  { sameCount = 0; lastSize = size; }
                if (sameCount >= StableSamplesNeeded)
                {
                    // Final exclusive-open probe to reject files still held by the writer.
                    try
                    {
                        using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                        return true;
                    }
                    catch (IOException) { sameCount = 0; }
                }
            }
            catch (FileNotFoundException) { return false; }
            catch (IOException)           { sameCount = 0; }
            await Task.Delay(StableCheckInterval, ct).ConfigureAwait(false);
        }
        return false;
    }

    private static (string? tool, IEnumerable<string>? args, string output) BuildJob(WatchProfile p, string path)
    {
        var stem = Path.GetFileNameWithoutExtension(path);
        var srcDir = Path.GetDirectoryName(path) ?? Environment.CurrentDirectory;
        var outDir = string.IsNullOrWhiteSpace(p.OutputDir) ? srcDir : p.OutputDir!;
        Directory.CreateDirectory(outDir);

        switch (p.Action)
        {
            case WatchAction.Compress:
            {
                var ext = Path.GetExtension(path);
                if (string.IsNullOrEmpty(ext)) ext = ".mp4";
                var output = Path.Combine(outDir, $"{stem}_compressed{ext}");
                var args = new List<string>
                {
                    "--input", path,
                    "--output", output,
                    "--preset", string.IsNullOrWhiteSpace(p.Preset) ? "web-1080p" : p.Preset!,
                };
                return ("videocrush", args, output);
            }
            case WatchAction.Convert:
            {
                var fmt = NormalizeExtension(p.TargetFormat, "mp4");
                var output = Path.Combine(outDir, $"{stem}.{fmt}");
                // We use clipforge `op_rewrap` for like-codec container swaps; for a
                // real encode pipeline, the converter sidecar would be a better fit
                // but isn't a single binary -- watch profiles ship the rewrap path
                // for now, which is correct for "drop a .mov, get a .mp4" workflows.
                var args = new List<string>
                {
                    "rewrap",
                    "--input",  path,
                    "--output", output,
                };
                return ("clipforge", args, output);
            }
            default:
                return (null, null, "");
        }
    }

    private static string NormalizeExtension(string? extension, string fallback)
    {
        var value = string.IsNullOrWhiteSpace(extension) ? fallback : extension.Trim().TrimStart('.');
        if (string.IsNullOrWhiteSpace(value)) return fallback;

        var invalid = Path.GetInvalidFileNameChars();
        if (value.IndexOfAny(invalid) >= 0 || value.IndexOfAny(['/', '\\', ':', '\0']) >= 0)
            return fallback;
        return value;
    }

    // ── Event log ───────────────────────────────────────────────────────────

    private void PostEvent(WatchProfile profile, string path, WatchEventStatus status, string? message)
    {
        var ev = new WatchEvent
        {
            ProfileId = profile.Id,
            ProfileName = profile.Name,
            FilePath = path,
            Timestamp = DateTime.Now,
            Status = status,
            Message = message,
        };
        _ui.TryEnqueue(() =>
        {
            Recent.Insert(0, ev);
            while (Recent.Count > RecentEventCap) Recent.RemoveAt(Recent.Count - 1);
        });
    }
}
