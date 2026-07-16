using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Result of a single tool update probe. Stored on disk so the dashboard /
/// settings page can render results without re-hitting the network.
/// </summary>
public sealed record UpdateInfo
{
    public string Tool { get; init; } = "";          // "yt-dlp", "ffmpeg", ...
    public string DisplayName { get; init; } = "";   // Human-friendly label.
    public string? InstalledVersion { get; init; }   // null if probe failed.
    public string? LatestVersion { get; init; }      // null if remote probe failed.
    public string? ReleaseUrl { get; init; }         // GitHub release page.
    public string? PublishedAt { get; init; }        // ISO timestamp.
    public bool UpdateAvailable { get; init; }
    public string? Error { get; init; }              // Set when probe failed.
}

/// <summary>Application release probe plus local preset/queue compatibility.</summary>
public sealed record ApplicationUpdateInfo
{
    public string InstalledVersion { get; init; } = "";
    public string? LatestVersion { get; init; }
    public string? ReleaseUrl { get; init; }
    public string? PublishedAt { get; init; }
    public bool UpdateAvailable { get; init; }
    public bool CompatibilityMetadataAvailable { get; init; }
    public List<string> CompatibilityWarnings { get; init; } = [];
    public string? Error { get; init; }
}

/// <summary>
/// Persisted cache shape — keeps result of the last successful (or partial)
/// probe so we can surface "updates available" without re-fetching every
/// launch and to throttle outbound network traffic.
/// </summary>
public sealed record UpdateCheckCache
{
    public DateTime LastCheckUtc { get; init; }
    public ApplicationUpdateInfo? Application { get; init; }
    public List<UpdateInfo> Tools { get; init; } = [];
}

public interface IUpdateCheckService
{
    /// <summary>Run a check against all known tools, honouring the throttle and the opt-out toggle.</summary>
    Task<UpdateCheckCache?> CheckAsync(bool force = false, CancellationToken ct = default);

    /// <summary>Read the on-disk cache without hitting the network.</summary>
    UpdateCheckCache? GetCachedResults();
}

/// <summary>
/// Polls GitHub Releases for UCX and four bundled tools (yt-dlp, ffmpeg,
/// whisper, onnxruntime), assesses release compatibility, and caches the result.
///
/// Charter-aligned: outbound traffic is one-way (HTTP GET on public release
/// manifests; no telemetry, no user data); the request is gated by the
/// existing <see cref="ConverterXOptions.CheckForUpdates"/> toggle; results
/// are cached for 24 h so a launch storm doesn't spam GitHub.
/// </summary>
public sealed class UpdateCheckService : IUpdateCheckService
{
    private static readonly TimeSpan ThrottleWindow = TimeSpan.FromHours(24);
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    private readonly ConverterXOptions _options;
    private readonly IToolManager? _toolManager;
    private readonly IBatchQueueStore? _queueStore;
    private readonly string _cachePath;
    private readonly object _gate = new();
    private static readonly HttpClient _http = CreateHttpClient();

    private static HttpClient CreateHttpClient()
    {
        var c = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        c.DefaultRequestHeaders.UserAgent.ParseAdd("UniversalConverterX-UpdateCheck/1.0");
        c.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        return c;
    }

    private sealed record TrackedTool(
        string Key,
        string DisplayName,
        string ReleasesApi,
        Func<UpdateCheckService, Task<string?>> ProbeInstalled);

    private readonly TrackedTool[] _tools;

    public UpdateCheckService(
        IOptions<ConverterXOptions> options,
        IToolManager? toolManager = null,
        IBatchQueueStore? queueStore = null)
    {
        _options = options.Value;
        _toolManager = toolManager;
        _queueStore = queueStore;
        _cachePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "update-cache.json");

        _tools =
        [
            new TrackedTool(
                "yt-dlp", "yt-dlp",
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                s => s.ProbeYtDlpAsync()),
            new TrackedTool(
                "ffmpeg", "FFmpeg (BtbN builds)",
                "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
                s => s.ProbeFfmpegAsync()),
            new TrackedTool(
                "whisper", "whisper.cpp",
                "https://api.github.com/repos/ggerganov/whisper.cpp/releases/latest",
                s => s.ProbeWhisperAsync()),
            new TrackedTool(
                "onnxruntime", "ONNX Runtime",
                "https://api.github.com/repos/microsoft/onnxruntime/releases/latest",
                s => s.ProbeOnnxRuntimeAsync()),
        ];
    }

    public UpdateCheckCache? GetCachedResults()
    {
        try
        {
            if (!File.Exists(_cachePath)) return null;
            var json = File.ReadAllText(_cachePath);
            return string.IsNullOrWhiteSpace(json)
                ? null
                : JsonSerializer.Deserialize<UpdateCheckCache>(json, JsonOpts);
        }
        catch
        {
            return null;
        }
    }

    public async Task<UpdateCheckCache?> CheckAsync(bool force = false, CancellationToken ct = default)
    {
        if (!_options.CheckForUpdates && !force) return GetCachedResults();

        var cached = GetCachedResults();
        if (!force && cached is not null && DateTime.UtcNow - cached.LastCheckUtc < ThrottleWindow)
            return cached;

        var results = new List<UpdateInfo>(_tools.Length);
        foreach (var tool in _tools)
        {
            ct.ThrowIfCancellationRequested();
            results.Add(await ProbeOneAsync(tool, ct).ConfigureAwait(false));
        }

        var fresh = new UpdateCheckCache
        {
            LastCheckUtc = DateTime.UtcNow,
            Application = await ProbeApplicationAsync(ct).ConfigureAwait(false),
            Tools = results,
        };

        TryWriteCache(fresh);
        return fresh;
    }

    private async Task<ApplicationUpdateInfo> ProbeApplicationAsync(CancellationToken ct)
    {
        const string releasesApi =
            "https://api.github.com/repos/SysAdminDoc/UniversalConverterX/releases/latest";
        var installed = GetInstalledApplicationVersion();

        try
        {
            using var response = await _http.GetAsync(releasesApi, ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return new ApplicationUpdateInfo
                {
                    InstalledVersion = installed,
                    Error = $"HTTP {(int)response.StatusCode}",
                };
            }

            var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            var release = await JsonSerializer.DeserializeAsync<GhRelease>(
                stream,
                JsonOpts,
                ct).ConfigureAwait(false);
            if (release is null)
            {
                return new ApplicationUpdateInfo
                {
                    InstalledVersion = installed,
                    Error = "Empty release payload",
                };
            }

            var versionComparison = VersionOrdering.TryCompare(installed, release.TagName);
            if (versionComparison is null)
            {
                return new ApplicationUpdateInfo
                {
                    InstalledVersion = installed,
                    LatestVersion = release.TagName,
                    ReleaseUrl = release.HtmlUrl,
                    PublishedAt = release.PublishedAt,
                    Error = "Release version could not be compared",
                };
            }

            var updateAvailable = versionComparison < 0;
            if (!updateAvailable)
            {
                return new ApplicationUpdateInfo
                {
                    InstalledVersion = installed,
                    LatestVersion = release.TagName,
                    ReleaseUrl = release.HtmlUrl,
                    PublishedAt = release.PublishedAt,
                };
            }

            var warnings = new List<string>();
            var metadataAvailable = false;
            var manifestAsset = release.Assets.FirstOrDefault(asset =>
                asset.Name.EndsWith(".release.json", StringComparison.OrdinalIgnoreCase));
            if (manifestAsset is null || string.IsNullOrWhiteSpace(manifestAsset.DownloadUrl))
            {
                warnings.Add(
                    "This release has no compatibility manifest. Review custom presets and saved queues before updating.");
            }
            else
            {
                try
                {
                    var json = await _http.GetStringAsync(manifestAsset.DownloadUrl, ct).ConfigureAwait(false);
                    var manifest = ReleaseCompatibilityPolicy.ParseManifest(json);
                    if (manifest?.Compatibility is null ||
                        VersionOrdering.TryCompare(manifest.Version, release.TagName) is not 0)
                    {
                        warnings.Add(
                            "The release compatibility manifest is invalid or does not match the release tag.");
                    }
                    else
                    {
                        metadataAvailable = true;
                        warnings.AddRange(AssessLocalCompatibility(manifest.Compatibility).Warnings);
                    }
                }
                catch (OperationCanceledException) { throw; }
                catch
                {
                    warnings.Add(
                        "Release compatibility metadata could not be downloaded. Review custom presets and saved queues before updating.");
                }
            }

            return new ApplicationUpdateInfo
            {
                InstalledVersion = installed,
                LatestVersion = release.TagName,
                ReleaseUrl = release.HtmlUrl,
                PublishedAt = release.PublishedAt,
                UpdateAvailable = true,
                CompatibilityMetadataAvailable = metadataAvailable,
                CompatibilityWarnings = warnings,
            };
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            return new ApplicationUpdateInfo
            {
                InstalledVersion = installed,
                Error = ex.GetType().Name,
            };
        }
    }

    private ReleaseCompatibilityAssessment AssessLocalCompatibility(
        ReleaseCompatibilityRequirements requirements)
    {
        var presets = new List<LocalPresetCompatibility>();
        try
        {
            if (Directory.Exists(UiPresetLoader.UserPresetDirectory))
            {
                foreach (var path in Directory.GetFiles(
                             UiPresetLoader.UserPresetDirectory,
                             "*.preset.xml",
                             SearchOption.TopDirectoryOnly))
                {
                    var metadata = PresetDocument.InspectMetadata(path);
                    presets.Add(new LocalPresetCompatibility(
                        metadata.Readable,
                        metadata.SchemaVersion,
                        metadata.Engine));
                }
            }
        }
        catch
        {
            presets.Add(new LocalPresetCompatibility(false, null, null));
        }

        IReadOnlyList<PersistedBatchQueue> queues;
        try { queues = _queueStore?.LoadAll() ?? []; }
        catch { queues = []; }
        return ReleaseCompatibilityPolicy.Assess(requirements, presets, queues);
    }

    private static string GetInstalledApplicationVersion()
    {
        var version = typeof(UpdateCheckService).Assembly.GetName().Version;
        return version is null ? "0.0.0" : $"{version.Major}.{version.Minor}.{version.Build}";
    }

    private async Task<UpdateInfo> ProbeOneAsync(TrackedTool tool, CancellationToken ct)
    {
        string? installed = null;
        try { installed = await tool.ProbeInstalled(this).ConfigureAwait(false); }
        catch { /* probe failures shouldn't crash the checker */ }

        try
        {
            using var resp = await _http.GetAsync(tool.ReleasesApi, ct).ConfigureAwait(false);
            if (!resp.IsSuccessStatusCode)
            {
                return new UpdateInfo
                {
                    Tool = tool.Key,
                    DisplayName = tool.DisplayName,
                    InstalledVersion = installed,
                    Error = $"HTTP {(int)resp.StatusCode}",
                };
            }

            var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            var release = await JsonSerializer.DeserializeAsync<GhRelease>(stream, JsonOpts, ct).ConfigureAwait(false);
            if (release is null)
            {
                return new UpdateInfo
                {
                    Tool = tool.Key,
                    DisplayName = tool.DisplayName,
                    InstalledVersion = installed,
                    Error = "Empty release payload",
                };
            }

            var hasUpdate = VersionOrdering.IsUpdateAvailable(installed, release.TagName);

            return new UpdateInfo
            {
                Tool = tool.Key,
                DisplayName = tool.DisplayName,
                InstalledVersion = installed,
                LatestVersion = release.TagName,
                ReleaseUrl = release.HtmlUrl,
                PublishedAt = release.PublishedAt,
                UpdateAvailable = hasUpdate,
            };
        }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex)
        {
            return new UpdateInfo
            {
                Tool = tool.Key,
                DisplayName = tool.DisplayName,
                InstalledVersion = installed,
                Error = ex.GetType().Name,
            };
        }
    }

    private void TryWriteCache(UpdateCheckCache cache)
    {
        lock (_gate)
        {
            try
            {
                var dir = Path.GetDirectoryName(_cachePath);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                    Directory.CreateDirectory(dir);

                var tmp = _cachePath + ".tmp";
                var json = JsonSerializer.Serialize(cache, JsonOpts);
                File.WriteAllText(tmp, json);
                try { File.Move(tmp, _cachePath, overwrite: true); }
                catch
                {
                    File.WriteAllText(_cachePath, json);
                    try { File.Delete(tmp); } catch { }
                }
            }
            catch
            {
                /* disk full / locked profile — keep result in memory only */
            }
        }
    }

    // ─── Installed-version probes ────────────────────────────────────────────
    //
    // Each probe is best-effort. Tools live under <ToolsBasePath>/<engine>/...
    // — but the layout differs per tool, so we keep a shared "scan first
    // matching file for a version pattern" approach rather than locking down
    // strict paths the user might never have populated.

    private string ToolsBase => string.IsNullOrWhiteSpace(_options.ToolsBasePath)
        ? AppContext.BaseDirectory
        : _options.ToolsBasePath;

    private async Task<string?> ProbeYtDlpAsync()
    {
        if (_toolManager is not null)
            return await _toolManager.GetToolVersionAsync("yt-dlp").ConfigureAwait(false);

        // Compatibility fallback for callers that construct this service
        // without the tool manager.
        var versionFile = Path.Combine(ToolsBase, "streamkeep", "yt-dlp.version");
        return TryReadVersionFile(versionFile);
    }

    private Task<string?> ProbeFfmpegAsync()
    {
        var versionFile = Path.Combine(ToolsBase, "ffmpeg", "ffmpeg.version");
        return Task.FromResult(TryReadVersionFile(versionFile));
    }

    private Task<string?> ProbeWhisperAsync()
    {
        var versionFile = Path.Combine(ToolsBase, "whisper", "whisper.version");
        return Task.FromResult(TryReadVersionFile(versionFile));
    }

    private Task<string?> ProbeOnnxRuntimeAsync()
    {
        var versionFile = Path.Combine(ToolsBase, "onnxruntime", "onnxruntime.version");
        return Task.FromResult(TryReadVersionFile(versionFile));
    }

    private static string? TryReadVersionFile(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            var v = File.ReadAllText(path).Trim();
            return string.IsNullOrWhiteSpace(v) ? null : v;
        }
        catch { return null; }
    }

    // ─── GitHub release payload (web-cased properties) ──────────────────────

    private sealed record GhRelease
    {
        [JsonPropertyName("tag_name")] public string? TagName { get; init; }
        [JsonPropertyName("name")] public string? Name { get; init; }
        [JsonPropertyName("html_url")] public string? HtmlUrl { get; init; }
        [JsonPropertyName("published_at")] public string? PublishedAt { get; init; }
        [JsonPropertyName("assets")] public List<GhAsset> Assets { get; init; } = [];
    }

    private sealed record GhAsset
    {
        [JsonPropertyName("name")] public string Name { get; init; } = "";
        [JsonPropertyName("browser_download_url")] public string? DownloadUrl { get; init; }
    }
}
