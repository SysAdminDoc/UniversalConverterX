using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.UI.Services;

public sealed record RepresentativePreviewPromotion(
    string Surface,
    string SourcePath,
    string? OutputDirectory,
    string OutputFormat,
    IReadOnlyDictionary<string, string?> PageSettings);

public sealed record VideoEnhancerRerunRequest(
    IReadOnlyList<string> SourcePaths,
    IReadOnlyDictionary<string, string?> PageSettings);

public sealed record RepresentativePreviewRequest(
    string Surface,
    string SourcePath,
    string Engine,
    IReadOnlyList<string> Arguments,
    RepresentativePreviewPromotion Promotion,
    double StartSeconds = 0,
    double DurationSeconds = 10);

public sealed record RepresentativePreviewResult(
    bool Success,
    string? SourceSamplePath,
    string? OutputSamplePath,
    long SourceSampleBytes,
    long OutputSampleBytes,
    double SourceDurationSeconds,
    double SampleDurationSeconds,
    TimeSpan RenderDuration,
    bool CacheHit,
    string? ErrorCode,
    string? ErrorMessage,
    RepresentativePreviewEstimate? Estimate)
{
    public static RepresentativePreviewResult Failure(string code, string message) => new(
        Success: false,
        SourceSamplePath: null,
        OutputSamplePath: null,
        SourceSampleBytes: 0,
        OutputSampleBytes: 0,
        SourceDurationSeconds: 0,
        SampleDurationSeconds: 0,
        RenderDuration: TimeSpan.Zero,
        CacheHit: false,
        ErrorCode: code,
        ErrorMessage: message,
        Estimate: null);
}

public interface IRepresentativePreviewService
{
    Task<RepresentativePreviewResult> RenderAsync(
        RepresentativePreviewRequest request,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Creates a short, deterministic preview from the exact argument vector a
/// full Compressor or Video Enhancer job will use. Source and rendered samples
/// are content-addressed under the local preview cache and never overwrite a
/// user-selected destination.
/// </summary>
public sealed class RepresentativePreviewService : IRepresentativePreviewService
{
    internal const double MinimumSampleSeconds = 3;
    internal const double MaximumSampleSeconds = 15;
    private const long MaximumCacheBytes = 256L * 1024 * 1024;
    private const int CacheDays = 30;

    private readonly ISidecarRunner _runner;

    public RepresentativePreviewService(ISidecarRunner runner)
    {
        _runner = runner;
    }

    public async Task<RepresentativePreviewResult> RenderAsync(
        RepresentativePreviewRequest request,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken cancellationToken = default)
    {
        if (request is null)
            return RepresentativePreviewResult.Failure("invalid_request", "The preview request is missing.");
        if (string.IsNullOrWhiteSpace(request.SourcePath) || !File.Exists(request.SourcePath))
            return RepresentativePreviewResult.Failure("missing_input", "The preview source file no longer exists.");
        if (string.IsNullOrWhiteSpace(request.Engine))
            return RepresentativePreviewResult.Failure("invalid_engine", "The preview engine is missing.");

        var inputIndex = FindArgument(request.Arguments, "--input");
        var outputIndex = FindArgument(request.Arguments, "--output");
        if (inputIndex < 0 || outputIndex < 0
            || inputIndex + 1 >= request.Arguments.Count
            || outputIndex + 1 >= request.Arguments.Count)
        {
            return RepresentativePreviewResult.Failure(
                "invalid_arguments",
                "The selected workflow does not expose one input and one output path for previewing.");
        }

        var ffprobe = LocateFfprobe();
        var fullDuration = ffprobe is null
            ? null
            : await OutputDurationValidator.ProbeDurationSecondsAsync(
                ffprobe, request.SourcePath, cancellationToken).ConfigureAwait(false);
        if (fullDuration is not > 0)
        {
            return RepresentativePreviewResult.Failure(
                ffprobe is null ? "missing_ffprobe" : "probe_failed",
                ffprobe is null
                    ? "FFprobe is required to choose a safe representative segment."
                    : "Could not determine the source duration for the representative segment.");
        }

        var sampleDuration = Math.Clamp(
            double.IsFinite(request.DurationSeconds) ? request.DurationSeconds : 10,
            MinimumSampleSeconds,
            MaximumSampleSeconds);
        sampleDuration = Math.Min(sampleDuration, fullDuration.Value);
        var start = Math.Clamp(
            double.IsFinite(request.StartSeconds) ? request.StartSeconds : 0,
            0,
            Math.Max(0, fullDuration.Value - sampleDuration));
        var end = Math.Min(fullDuration.Value, start + sampleDuration);
        sampleDuration = end - start;
        if (sampleDuration <= 0)
            return RepresentativePreviewResult.Failure("invalid_range", "The source is too short for a representative sample.");

        var originalOutput = request.Arguments[outputIndex + 1];
        var outputExtension = SafeOutputExtension(originalOutput);
        var cacheDirectory = ResolveCacheDirectory();
        try { Directory.CreateDirectory(cacheDirectory); }
        catch (Exception ex)
        {
            return RepresentativePreviewResult.Failure("cache_unavailable", $"Preview cache could not be created: {ex.Message}");
        }

        var key = BuildCacheKey(request, start, sampleDuration, fullDuration.Value);
        var sourceSample = Path.Combine(cacheDirectory, $"{key}.source.mp4");
        var outputSample = Path.Combine(cacheDirectory, $"{key}.output{outputExtension}");
        var manifestPath = Path.Combine(cacheDirectory, $"{key}.json");
        var cached = await TryReadCacheAsync(
            manifestPath, sourceSample, outputSample, fullDuration.Value, sampleDuration,
            cancellationToken).ConfigureAwait(false);
        if (cached is not null)
        {
            TryPruneCache(cacheDirectory);
            return cached;
        }

        var trimResult = await _runner.RunAsync(
            "clipforge",
            [
                "trim", "--input", request.SourcePath, "--output", sourceSample,
                "--start", start.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture),
                "--end", end.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture),
                "--codec", "libx264", "--crf", "18", "--preset", "veryfast",
                "--audio-codec", "aac", "--audio-bitrate", "128",
            ],
            progress, log, cancellationToken,
            silenceTimeout: TimeSpan.FromMinutes(2)).ConfigureAwait(false);
        if (!trimResult.Success || !IsNonEmptyFile(sourceSample))
        {
            return RepresentativePreviewResult.Failure(
                trimResult.ErrorCode ?? "sample_trim_failed",
                trimResult.ErrorMessage ?? "Could not create the representative source segment.");
        }

        var previewArguments = request.Arguments.ToList();
        previewArguments[inputIndex + 1] = sourceSample;
        previewArguments[outputIndex + 1] = outputSample;
        var started = Stopwatch.StartNew();
        var renderResult = await _runner.RunAsync(
            request.Engine,
            previewArguments,
            progress,
            log,
            cancellationToken,
            silenceTimeout: TimeSpan.FromMinutes(15)).ConfigureAwait(false);
        started.Stop();
        if (!renderResult.Success || !IsNonEmptyFile(outputSample))
        {
            return RepresentativePreviewResult.Failure(
                renderResult.ErrorCode ?? "sample_render_failed",
                renderResult.ErrorMessage ?? "The representative render did not produce an output.");
        }

        var renderedDuration = ffprobe is null
            ? sampleDuration
            : await OutputDurationValidator.ProbeDurationSecondsAsync(
                ffprobe, outputSample, cancellationToken).ConfigureAwait(false) ?? sampleDuration;
        var sourceBytes = new FileInfo(sourceSample).Length;
        var outputBytes = new FileInfo(outputSample).Length;
        var estimate = new RepresentativePreviewEstimate(
            renderedDuration, outputBytes, fullDuration.Value, started.Elapsed.TotalSeconds);
        await WriteCacheManifestAsync(
            manifestPath,
            new PreviewCacheManifest(
                fullDuration.Value,
                renderedDuration,
                started.Elapsed.TotalSeconds,
                DateTime.UtcNow),
            cancellationToken).ConfigureAwait(false);
        TryPruneCache(cacheDirectory);

        return new RepresentativePreviewResult(
            Success: true,
            SourceSamplePath: sourceSample,
            OutputSamplePath: outputSample,
            SourceSampleBytes: sourceBytes,
            OutputSampleBytes: outputBytes,
            SourceDurationSeconds: fullDuration.Value,
            SampleDurationSeconds: renderedDuration,
            RenderDuration: started.Elapsed,
            CacheHit: false,
            ErrorCode: null,
            ErrorMessage: null,
            Estimate: estimate);
    }

    private async Task<RepresentativePreviewResult?> TryReadCacheAsync(
        string manifestPath,
        string sourceSample,
        string outputSample,
        double fullDuration,
        double requestedSampleDuration,
        CancellationToken cancellationToken)
    {
        if (!IsNonEmptyFile(sourceSample) || !IsNonEmptyFile(outputSample) || !File.Exists(manifestPath))
            return null;

        try
        {
            await using var stream = File.OpenRead(manifestPath);
            var manifest = await JsonSerializer.DeserializeAsync<PreviewCacheManifest>(
                stream, cancellationToken: cancellationToken).ConfigureAwait(false);
            if (manifest is null) return null;
            var createdUtc = manifest.CreatedUtc == default
                ? File.GetLastWriteTimeUtc(manifestPath)
                : manifest.CreatedUtc;
            if (createdUtc < DateTime.UtcNow.AddDays(-CacheDays))
                return null;
            var sampleDuration = manifest.SampleDurationSeconds > 0
                ? manifest.SampleDurationSeconds
                : requestedSampleDuration;
            var renderSeconds = Math.Max(0, manifest.RenderSeconds);
            var outputBytes = new FileInfo(outputSample).Length;
            var sourceDuration = manifest.SourceDurationSeconds > 0
                ? manifest.SourceDurationSeconds
                : fullDuration;
            return new RepresentativePreviewResult(
                Success: true,
                SourceSamplePath: sourceSample,
                OutputSamplePath: outputSample,
                SourceSampleBytes: new FileInfo(sourceSample).Length,
                OutputSampleBytes: outputBytes,
                SourceDurationSeconds: sourceDuration,
                SampleDurationSeconds: sampleDuration,
                RenderDuration: TimeSpan.FromSeconds(renderSeconds),
                CacheHit: true,
                ErrorCode: null,
                ErrorMessage: null,
                Estimate: new RepresentativePreviewEstimate(
                    sampleDuration, outputBytes, sourceDuration, renderSeconds));
        }
        catch (OperationCanceledException) { throw; }
        catch { return null; }
    }

    private static async Task WriteCacheManifestAsync(
        string path,
        PreviewCacheManifest manifest,
        CancellationToken cancellationToken)
    {
        var temporary = path + ".tmp";
        await using (var stream = File.Create(temporary))
        {
            await JsonSerializer.SerializeAsync(stream, manifest, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
        }
        File.Move(temporary, path, overwrite: true);
    }

    private static string BuildCacheKey(
        RepresentativePreviewRequest request,
        double start,
        double duration,
        double fullDuration)
    {
        var info = new FileInfo(request.SourcePath);
        var inputIndex = FindArgument(request.Arguments, "--input");
        var outputIndex = FindArgument(request.Arguments, "--output");
        var canonicalArguments = request.Arguments.Select((argument, index) =>
            index == inputIndex + 1
                ? "<input>"
                : index == outputIndex + 1
                    ? "<output>"
                    : argument);
        var material = string.Join("\n", [
            request.Surface,
            request.Engine,
            request.SourcePath,
            info.Length.ToString(System.Globalization.CultureInfo.InvariantCulture),
            info.LastWriteTimeUtc.Ticks.ToString(System.Globalization.CultureInfo.InvariantCulture),
            start.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
            duration.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
            fullDuration.ToString("R", System.Globalization.CultureInfo.InvariantCulture),
            .. canonicalArguments,
        ]);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(material))).ToLowerInvariant();
    }

    private static int FindArgument(IReadOnlyList<string> arguments, string name)
    {
        for (var i = 0; i < arguments.Count; i++)
        {
            if (string.Equals(arguments[i], name, StringComparison.OrdinalIgnoreCase))
                return i;
        }
        return -1;
    }

    private static string SafeOutputExtension(string path)
    {
        var extension = Path.GetExtension(path);
        return extension.Length is > 1 and <= 8
               && extension.All(character => char.IsLetterOrDigit(character) || character == '.')
            ? extension.ToLowerInvariant()
            : ".mp4";
    }

    private static bool IsNonEmptyFile(string path)
    {
        try { return File.Exists(path) && new FileInfo(path).Length > 0; }
        catch { return false; }
    }

    private static string ResolveCacheDirectory() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX", "preview-cache");

    private static string? LocateFfprobe()
    {
        var roots = new List<string>();
        var baseDirectory = new DirectoryInfo(AppContext.BaseDirectory);
        while (baseDirectory is not null)
        {
            roots.Add(baseDirectory.FullName);
            baseDirectory = baseDirectory.Parent;
        }

        foreach (var root in roots)
        {
            foreach (var relative in new[]
            {
                Path.Combine("tools", "ffmpeg", "ffprobe.exe"),
                Path.Combine("tools", "bin", "ffprobe.exe"),
                Path.Combine("tools", "_bin", "ffprobe.exe"),
                Path.Combine("tools", "videocrush", "ffprobe.exe"),
                Path.Combine("tools", "clipforge", "ffprobe.exe"),
            })
            {
                var candidate = Path.Combine(root, relative);
                if (File.Exists(candidate)) return candidate;
            }
        }

        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
        {
            if (string.IsNullOrWhiteSpace(directory)) continue;
            var candidate = Path.Combine(directory.Trim(), "ffprobe.exe");
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }

    private static void TryPruneCache(string directory)
    {
        try
        {
            var files = new DirectoryInfo(directory).EnumerateFiles()
                .OrderBy(file => file.LastWriteTimeUtc)
                .ToList();
            var cutoff = DateTime.UtcNow.AddDays(-CacheDays);
            foreach (var file in files.Where(file => file.LastWriteTimeUtc < cutoff))
                file.Delete();

            files = new DirectoryInfo(directory).EnumerateFiles()
                .OrderBy(file => file.LastWriteTimeUtc)
                .ToList();
            var total = files.Sum(file => file.Length);
            foreach (var file in files)
            {
                if (total <= MaximumCacheBytes) break;
                total -= file.Length;
                file.Delete();
            }
        }
        catch { /* A stale preview cache is never allowed to fail a job. */ }
    }

    private sealed record PreviewCacheManifest(
        double SourceDurationSeconds,
        double SampleDurationSeconds,
        double RenderSeconds,
        DateTime CreatedUtc);
}
