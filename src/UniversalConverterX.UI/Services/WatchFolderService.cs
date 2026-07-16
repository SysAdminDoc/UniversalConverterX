using System.Collections.Concurrent;
using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.UI.Dispatching;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.UI.Services;

public enum WatchAction { Convert, Compress }

public enum WatchEventStatus { Settling, Picked, Running, Done, Failed, Skipped }

public sealed record WatchFolderStatus(int ActiveProfiles, int InFlightFiles, int RememberedFiles);

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
    WatchFolderStatus Status { get; }
    void Add(WatchProfile profile);
    void Update(WatchProfile profile);
    void Remove(string id);
    void SetEnabled(string id, bool enabled);
    void Save();
}

public sealed class WatchFolderService : IWatchFolderService, IDisposable
{
    private const int RecentEventCap = 200;
    private const int SeenFileCap = 4096;
    private static readonly TimeSpan StableCheckInterval = TimeSpan.FromSeconds(2);
    private const int StableSamplesNeeded = 2;
    private static readonly TimeSpan StableTimeout = TimeSpan.FromMinutes(15);

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly DispatcherQueue _ui;
    private readonly string _configPath;
    private readonly ConcurrentDictionary<string, FileSystemWatcher> _watchers = new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentDictionary<string, CancellationTokenSource> _profileCts = new(StringComparer.OrdinalIgnoreCase);
    private readonly WatchFileAdmission _admission = new(SeenFileCap);
    private readonly object _saveLock = new();
    private Task _lastSaveTask = Task.CompletedTask;
    /// <summary>
    /// Trips when the whole service is being shut down. Linked into every
    /// per-profile CTS so disposing the service cancels any running sidecar
    /// rather than leaving orphan processes after app exit.
    /// </summary>
    private readonly CancellationTokenSource _shutdownCts = new();

    public ObservableCollection<WatchProfile> Profiles { get; } = [];
    public ObservableCollection<WatchEvent> Recent { get; } = [];
    public WatchFolderStatus Status => new(_watchers.Count, _admission.InFlightCount, _admission.RememberedCount);

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
            PreserveCorruptConfig();
            Profiles.Clear();
        }
    }

    public void Save()
    {
        // Snapshot under the UI thread (where Profiles lives) and serialize on a
        // worker so profile edits don't stutter navigation. Queue writes in the
        // same order Save was called; otherwise an older background write can
        // race and overwrite a newer profile list.
        var snapshot = Profiles.ToList();
        lock (_saveLock)
        {
            _lastSaveTask = _lastSaveTask.ContinueWith(
                _ => WriteProfilesSnapshot(snapshot),
                CancellationToken.None,
                TaskContinuationOptions.None,
                TaskScheduler.Default);
        }
    }

    private void WriteProfilesSnapshot(IReadOnlyList<WatchProfile> snapshot)
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

    private void PreserveCorruptConfig()
    {
        try
        {
            if (!File.Exists(_configPath)) return;
            var backup = _configPath + ".corrupt." + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "." + Guid.NewGuid().ToString("N")[..8];
            File.Copy(_configPath, backup, overwrite: false);
        }
        catch { /* best-effort recovery artifact */ }
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
            else StopWatcher(id);
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
        Task? saveToWait;
        lock (_saveLock) saveToWait = _lastSaveTask;
        try { saveToWait.Wait(TimeSpan.FromSeconds(2)); } catch { }
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
                EnableRaisingEvents = false,
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
        fsw.Changed += (_, e) => OnArrival(profile, e.FullPath);
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
        try
        {
            fsw.EnableRaisingEvents = true;
        }
        catch (Exception ex)
        {
            StopWatcher(profile.Id);
            PostEvent(profile, profile.Path, WatchEventStatus.Failed,
                      $"Could not start folder watch: {ex.Message}");
        }
    }

    private void StopWatcher(string id)
    {
        if (_watchers.TryRemove(id, out var fsw))
        {
            try { fsw.EnableRaisingEvents = false; fsw.Dispose(); } catch { }
        }
        if (_profileCts.TryRemove(id, out var cts))
        {
            try { cts.Cancel(); cts.Dispose(); } catch { }
        }
    }

    private void OnArrival(WatchProfile profile, string path)
    {
        if (!MatchesFilter(profile.Filter, path)) return;
        if (_admission.IsSuppressedOutput(path)) return;
        if (!_admission.TryBegin(path)) return; // already in-flight
        var profileToken = _profileCts.TryGetValue(profile.Id, out var startingCts)
            ? startingCts.Token
            : _shutdownCts.Token;
        PostEvent(profile, path, WatchEventStatus.Settling, "waiting for two stable reads");

        _ = Task.Run(async () =>
        {
            try
            {
                var stableObservation = await WatchFileStability.WaitAsync(
                    path,
                    StableCheckInterval,
                    StableTimeout,
                    StableSamplesNeeded,
                    profileToken);
                if (stableObservation is null)
                {
                    PostEvent(profile, path, WatchEventStatus.Skipped, "file never settled");
                    return;
                }
                if (!_admission.TryRemember(path, stableObservation.Value))
                {
                    PostEvent(profile, path, WatchEventStatus.Skipped, "unchanged duplicate event");
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

                // Register the planned artifact before spawning the sidecar so
                // Created/Changed events raised during the write cannot feed the
                // watcher's own output back into another job.
                _admission.SuppressOutput(output);
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
                    Timestamp = startedAt,
                    Engine = tool,
                    Action = profile.Action == WatchAction.Compress ? "compress" : "convert",
                    SourcePath = path,
                    OutputPath = result.Success ? output : null,
                    SourceBytes = srcBytes,
                    OutputBytes = outBytes,
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                    Success = result.Success,
                    ErrorCode = result.ErrorCode,
                    ErrorMessage = result.ErrorMessage,
                    Profile = profile.Action == WatchAction.Compress ? profile.Preset : profile.TargetFormat,
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
                _admission.End(path);
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
        if (PathSafety.TryNormalizeExtension(extension, out var normalized))
            return normalized;
        return PathSafety.TryNormalizeExtension(fallback, out var normalizedFallback)
            ? normalizedFallback
            : "mp4";
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
