using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.UI.Services;

public sealed record SidecarProgress(double Percent, string Stage, int? EtaSeconds);

public sealed record SidecarLog(string Level, string Message);

public sealed record SidecarResult(
    bool Success,
    string? OutputPath,
    long? SizeBytes,
    string? ErrorCode,
    string? ErrorMessage,
    int ExitCode)
{
    /// <summary>
    /// How this output was produced — redacted args, the binary that ran, input
    /// and output identity, the capability decision, and the post-hoc probe.
    /// Null only for results produced before the engine was even launched.
    /// </summary>
    public JobProvenance? Provenance { get; init; }

    /// <summary>
    /// The requested and actual encoder/backend reported by the sidecar. Kept
    /// beside the serialized provenance so pages can show the decision without
    /// reparsing the history payload.
    /// </summary>
    public CapabilityDecision? Capability { get; init; }
}

public interface ISidecarRunner
{
    /// <summary>
    /// Resolve the full path to a sidecar binary. Returns null if not found.
    /// Search order: tools/&lt;name&gt;/&lt;name&gt;.exe relative to AppContext.BaseDirectory,
    /// then walking up to find a tools/ directory, then %LocalAppData%/UniversalConverterX/tools/.
    /// </summary>
    string? Locate(string toolName);

    /// <summary>
    /// Default watchdog grace period. A sidecar that emits no NDJSON events for
    /// longer than this is presumed stuck and killed. Pages that genuinely run
    /// quietly (e.g. waiting on a long network upload) should pass a larger
    /// <c>silenceTimeout</c> rather than relying on the default.
    /// </summary>
    public static readonly TimeSpan DefaultSilenceTimeout = TimeSpan.FromMinutes(10);

    Task<SidecarResult> RunAsync(
        string toolName,
        IEnumerable<string> args,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken ct = default,
        Action<string, JsonElement>? onRawEvent = null,
        TimeSpan? silenceTimeout = null);
}

public sealed class SidecarRunner : ISidecarRunner
{
    private readonly ConverterXOptions? _options;
    private readonly IFfmpegCommandReviewService? _ffmpegCommandReview;
    private readonly IPluginTrustService? _pluginTrustService;

    /// <summary>Default constructor for callers that don't need options injection.</summary>
    public SidecarRunner() { }

    /// <summary>DI-aware constructor — used by App.xaml.cs ServiceProvider.</summary>
    public SidecarRunner(IOptions<ConverterXOptions> options) { _options = options?.Value; }

    public SidecarRunner(
        IOptions<ConverterXOptions> options,
        IFfmpegCommandReviewService ffmpegCommandReview,
        IPluginTrustService? pluginTrustService = null)
    {
        _options = options?.Value;
        _ffmpegCommandReview = ffmpegCommandReview;
        _pluginTrustService = pluginTrustService;
    }

    public string? Locate(string toolName)
    {
        var builtIn = SidecarCatalog.Resolve(toolName);
        if (builtIn is not null) return builtIn;

        // Third-party plugins are a separate, default-deny execution root.
        // TryGetTrustedPlugin recomputes the whole-directory SHA-256 before
        // every launch, so modified or symlinked plugin files never run.
        if (_pluginTrustService?.TryGetTrustedPlugin(toolName, out var plugin) == true)
            return plugin!.ExecutablePath;

        return null;
    }

    public async Task<SidecarResult> RunAsync(
        string toolName,
        IEnumerable<string> args,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken ct = default,
        Action<string, JsonElement>? onRawEvent = null,
        TimeSpan? silenceTimeout = null)
    {
        // Materialize once: the vector is walked for the input path, the
        // approved output root, and the provenance record, and an
        // IEnumerable built from a generator would give different answers.
        var argumentVector = args as IReadOnlyList<string> ?? [.. args];
        args = argumentVector;

        var startedUtc = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();
        var progressTracker = new JobProgressTracker();
        var capability = InferCapability(argumentVector);

        var exe = Locate(toolName);
        if (exe is null)
        {
            return new SidecarResult(
                Success: false,
                OutputPath: null,
                SizeBytes: null,
                ErrorCode: "sidecar_not_found",
                ErrorMessage:
                    $"Could not locate '{toolName}.exe'. Build it with " +
                    $"`pwsh tools/{toolName}/build.ps1`, or drop a frozen exe at " +
                    $"%LocalAppData%/UniversalConverterX/tools/{toolName}/{toolName}.exe. " +
                    "Third-party engines must also be explicitly trusted in Settings > Plugins.",
                ExitCode: -1);
        }

        // A discovered binary is not executable until its signed-in-repo
        // compatibility contract agrees with this host. Trusted plugins are
        // already validated by PluginTrustService; built-in sidecars use the
        // shared manifest gate here so direct page launches cannot bypass
        // health diagnostics.
        if (SidecarCatalog.Resolve(toolName) is not null)
        {
            var compatibility = ExtensionManifestCompatibility.ValidateSidecar(toolName, exe);
            if (!compatibility.IsCompatible)
            {
                return new SidecarResult(
                    Success: false,
                    OutputPath: null,
                    SizeBytes: null,
                    ErrorCode: "extension_incompatible",
                    ErrorMessage: compatibility.Reason,
                    ExitCode: -1);
            }
        }

        var psi = new ProcessStartInfo
        {
            FileName = exe,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // Closing stdin lets sidecars that accidentally read stdin (e.g. a Python
            // input() during a debug build) fail fast instead of hanging forever.
            RedirectStandardInput = true,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            // Force UTF-8 on stdout/stderr so non-ASCII messages from sidecars
            // (file paths, language names, error text) survive the pipe round-trip
            // without mojibake on the typical Windows codepage.
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        // Python chooses the legacy Windows code page for redirected streams
        // unless told otherwise. Keep the producer and the UTF-8 .NET decoder
        // aligned so Unicode paths can be emitted in NDJSON events.
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        // Inject the shared model cache directory as an environment variable.
        // ONNX-based sidecars can read UCX_MODEL_DIR to locate/store models in a
        // single location instead of per-tool subdirectories.
        var modelCacheDir = ResolveModelCacheDirectory();
        if (modelCacheDir is not null)
        {
            try
            {
                Directory.CreateDirectory(modelCacheDir);
                psi.EnvironmentVariables["UCX_MODEL_DIR"] = modelCacheDir;
            }
            catch
            {
                // Locked-down profile / disk full / non-writable parent — fall back
                // to letting each sidecar pick its own location. Never fail the run
                // just because we couldn't seed the shared cache hint.
            }
        }

        // Managed downloader runtimes live together in tools/bin. Expose the
        // exact directory to StreamKeep and prepend it for child discovery;
        // this avoids mutating the user's process-wide PATH.
        var toolsBin = ResolveManagedToolsBin();
        if (toolsBin is not null)
        {
            psi.EnvironmentVariables["UCX_TOOLS_BIN"] = toolsBin;
            var inheritedPath = psi.EnvironmentVariables["PATH"] ?? "";
            psi.EnvironmentVariables["PATH"] = string.IsNullOrWhiteSpace(inheritedPath)
                ? toolsBin
                : toolsBin + Path.PathSeparator + inheritedPath;
        }

        var ffmpegReview = ConfigureFfmpegReview(psi, toolsBin, log);

        // Give the engine its own scratch root so one job's frame dumps and
        // demuxes are never visible to the next, and cleanup is unambiguous.
        // The using declaration deletes it on every exit path, including the
        // cancellation and watchdog returns below.
        using var workspace = TryCreatePrivateWorkspace(psi, log);

        using var containment = _options?.ContainSidecarProcesses != false
            ? ProcessContainment.Create(BuildContainmentLimits())
            : null;

        using var process = new Process { StartInfo = psi };

        string? finalOutput = null;
        long? finalSize = null;
        string? errorCode = null;
        string? errorMessage = null;

        // Watchdog: if no NDJSON event lands for `effectiveTimeout`, cancel via
        // a linked CTS so the kill path below runs. Reset on every event the
        // sidecar emits — progress, log, segment, stem, device, complete, error.
        var effectiveTimeout = silenceTimeout ?? ISidecarRunner.DefaultSilenceTimeout;
        using var watchdogCts = new CancellationTokenSource();
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct, watchdogCts.Token);
        var lct = linkedCts.Token;

        void ResetWatchdog()
        {
            try { watchdogCts.CancelAfter(effectiveTimeout); }
            catch (ObjectDisposedException) { /* race with completion — ignore */ }
        }

        void SuspendWatchdog()
        {
            try { watchdogCts.CancelAfter(Timeout.InfiniteTimeSpan); }
            catch (ObjectDisposedException) { /* race with completion — ignore */ }
        }
        ResetWatchdog();

        using var reviewCts = CancellationTokenSource.CreateLinkedTokenSource(lct);
        var reviewServerTask = ffmpegReview is null
            ? Task.CompletedTask
            : RunFfmpegReviewServerAsync(
                ffmpegReview,
                SuspendWatchdog,
                ResetWatchdog,
                log,
                reviewCts.Token);

        async Task StopFfmpegReviewAsync()
        {
            reviewCts.Cancel();
            try { await reviewServerTask.ConfigureAwait(false); }
            catch (OperationCanceledException) { }
            catch (Exception exception)
            {
                log?.Report(new SidecarLog(
                    "warn",
                    $"FFmpeg command review stopped unexpectedly: {exception.Message}"));
            }
        }

        try
        {
            process.Start();
        }
        catch (Exception ex)
        {
            await StopFfmpegReviewAsync().ConfigureAwait(false);
            return new SidecarResult(
                Success: false,
                OutputPath: null,
                SizeBytes: null,
                ErrorCode: "spawn_failed",
                ErrorMessage: $"Could not launch '{toolName}': {ex.Message}",
                ExitCode: -1);
        }

        // Assign before the engine has a chance to spawn helpers. Anything it
        // forks from here on is inside the job and dies with it, including if
        // this app is terminated rather than exiting cleanly.
        if (containment is not null)
        {
            try
            {
                if (!containment.TryAssign(process.Handle) && containment.FailureReason is not null)
                {
                    log?.Report(new SidecarLog(
                        "debug",
                        $"Process containment unavailable: {containment.FailureReason}"));
                }
            }
            catch (Exception exception) when (
                exception is InvalidOperationException or NotSupportedException)
            {
                log?.Report(new SidecarLog(
                    "debug",
                    $"Process containment unavailable: {exception.Message}"));
            }
        }

        // Close stdin: the sidecar will see EOF on read and abort cleanly rather
        // than blocking on input that will never arrive.
        try { process.StandardInput.Close(); } catch { /* never fatal */ }

        // Stream stdout line-by-line, parsing NDJSON. Use ReadLineAsync(lct) and
        // exit on null (true EOF) — the EndOfStream property issues a synchronous
        // peek that ignores the cancellation token and was the source of stuck
        // shutdowns when a sidecar wedged mid-pipe.
        var stdoutTask = Task.Run(async () =>
        {
            try
            {
                var reader = process.StandardOutput;
                while (true)
                {
                    string? line;
                    try
                    {
                        line = await reader.ReadLineAsync(lct).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                    catch (IOException)
                    {
                        // Pipe closed underneath us (process killed). EOF.
                        break;
                    }
                    if (line is null) break;
                    if (string.IsNullOrWhiteSpace(line)) continue;

                    // Any output (NDJSON or otherwise) means the sidecar is alive.
                    ResetWatchdog();

                    try
                    {
                        using var doc = JsonDocument.Parse(line);
                        var root = doc.RootElement;
                        if (root.ValueKind != JsonValueKind.Object) continue;
                        if (!root.TryGetProperty("event", out var ev)) continue;
                        var evName = ev.GetString();

                        // Notify raw event subscriber before processing known events
                        if (onRawEvent is not null && evName is not null)
                        {
                            try { onRawEvent(evName, root.Clone()); }
                            catch { /* never let a subscriber kill the parse loop */ }
                        }

                        switch (evName)
                        {
                            case "progress":
                            {
                                // Normalize centrally. Engines report NaN, values
                                // above 100, and percentages that walk backwards;
                                // pages must not each re-derive the rules, and a
                                // stale ETA must expire rather than keep counting.
                                var normalized = progressTracker.Report(
                                    root.TryGetProperty("percent", out var p) && p.ValueKind == JsonValueKind.Number ? p.GetDouble() : double.NaN,
                                    root.TryGetProperty("stage", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null,
                                    root.TryGetProperty("eta_seconds", out var e) && e.ValueKind == JsonValueKind.Number && e.TryGetInt32(out var etaValue) ? etaValue : null);
                                progress?.Report(new SidecarProgress(
                                    normalized.Percent,
                                    normalized.Stage,
                                    normalized.EtaSeconds));
                                break;
                            }

                            case "log":
                            {
                                var level = root.TryGetProperty("level", out var lv) && lv.ValueKind == JsonValueKind.String
                                    ? lv.GetString() ?? "info"
                                    : "info";
                                var message = root.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String
                                    ? m.GetString() ?? ""
                                    : "";
                                capability = ObserveCapabilityLog(capability, message);
                                log?.Report(new SidecarLog(level, message));
                                break;
                            }

                            case "complete":
                                if (root.TryGetProperty("output", out var o) && o.ValueKind == JsonValueKind.String)
                                    finalOutput = o.GetString();
                                if (root.TryGetProperty("size_bytes", out var sb) && sb.ValueKind == JsonValueKind.Number && sb.TryGetInt64(out var sbVal))
                                    finalSize = sbVal;
                                break;

                            case "error":
                                errorCode = root.TryGetProperty("code", out var c) && c.ValueKind == JsonValueKind.String
                                    ? c.GetString() ?? "unknown"
                                    : "unknown";
                                if (root.TryGetProperty("message", out var em) && em.ValueKind == JsonValueKind.String)
                                    errorMessage = em.GetString();
                                break;

                            case "capability":
                                if (root.TryGetProperty("name", out var capabilityName)
                                    && capabilityName.ValueKind == JsonValueKind.String
                                    && string.Equals(capabilityName.GetString(), "rife", StringComparison.OrdinalIgnoreCase)
                                    && root.TryGetProperty("status", out var capabilityStatus)
                                    && capabilityStatus.ValueKind == JsonValueKind.String
                                    && string.Equals(capabilityStatus.GetString(), "ready", StringComparison.OrdinalIgnoreCase))
                                {
                                    var selected = root.TryGetProperty("runtime", out var runtime)
                                        && runtime.ValueKind == JsonValueKind.String
                                        ? runtime.GetString()
                                        : "rife-ncnn-vulkan";
                                    capability = new CapabilityDecision(
                                        Requested: "vulkan",
                                        Selected: selected ?? "rife-ncnn-vulkan",
                                        FellBack: false,
                                        Reason: null);
                                }
                                break;
                        }
                    }
                    catch (JsonException)
                    {
                        // Sidecar wrote a non-JSON line — surface as a log entry. Cap
                        // the noise: a sidecar dumping megabytes of warnings would
                        // otherwise spam the UI's log panel.
                        log?.Report(new SidecarLog(
                            "debug",
                            line.Length > 4096 ? line[..4096] + "…" : line));
                    }
                }
            }
            catch (OperationCanceledException) { /* propagated below */ }
        }, CancellationToken.None);

        // Drain stderr too — sidecars shouldn't write here, but capture anything that leaks.
        var stderrTask = Task.Run(async () =>
        {
            try
            {
                using var er = process.StandardError;
                while (true)
                {
                    string? ln;
                    try
                    {
                        ln = await er.ReadLineAsync(lct).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException) { break; }
                    catch (IOException) { break; }
                    if (ln is null) break;
                    if (string.IsNullOrWhiteSpace(ln)) continue;
                    log?.Report(new SidecarLog("stderr", ln.TrimEnd('\r')));
                }
            }
            catch { /* swallow — best-effort */ }
        }, CancellationToken.None);

        var stuckByWatchdog = false;
        var cancelledByUser = false;
        try
        {
            await process.WaitForExitAsync(lct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // Determine which side of the linked CTS fired: watchdog vs. user.
            stuckByWatchdog = watchdogCts.IsCancellationRequested && !ct.IsCancellationRequested;
            cancelledByUser = ct.IsCancellationRequested;
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { /* swallow */ }

            // Wait for the process to actually exit so its pipes flush, then drain
            // both reader tasks before the using-scope disposes the streams under
            // them. Bound the wait so a wedged kernel handle can't hang the UI.
            try
            {
                using var graceCts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                await process.WaitForExitAsync(graceCts.Token).ConfigureAwait(false);
            }
            catch { /* either timed out or already exited — proceed to drain */ }
        }

        // Always drain the reader tasks before returning so we don't leak threads
        // or read from a stream that the using-scope is about to dispose.
        try
        {
            await Task.WhenAll(stdoutTask, stderrTask).ConfigureAwait(false);
        }
        catch { /* both tasks swallow internally; this is paranoia */ }

        await StopFfmpegReviewAsync().ConfigureAwait(false);

        if (stuckByWatchdog)
        {
            log?.Report(new SidecarLog(
                "warn",
                $"{toolName} emitted no output for " +
                $"{(int)effectiveTimeout.TotalSeconds}s — killed as stuck"));
            return new SidecarResult(
                Success: false,
                OutputPath: null,
                SizeBytes: null,
                ErrorCode: "stuck_sidecar",
                ErrorMessage:
                    $"{toolName} produced no output for " +
                    $"{(int)effectiveTimeout.TotalSeconds}s and was terminated. " +
                    $"Pass a larger silenceTimeout to RunAsync if this sidecar " +
                    $"runs quietly during long network or model-load phases.",
                ExitCode: -1);
        }

        if (cancelledByUser)
            return new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", -1);

        // process.ExitCode requires HasExited; if the kill grace timed out it may
        // not have updated. Treat that as a failure with a synthetic exit code.
        int exitCode;
        try { exitCode = process.ExitCode; }
        catch (InvalidOperationException) { exitCode = -1; }

        var success = exitCode == 0 && errorCode is null;

        // The reported output path comes from an engine that just consumed an
        // untrusted file, so it is untrusted too. Confine it to the destination
        // this app named before anything downstream opens, probes, moves, or
        // reports it.
        if (success
            && finalOutput is not null
            && _options?.EnforceSidecarOutputBoundary != false)
        {
            var boundary = SidecarOutputBoundary.Validate(
                finalOutput,
                SidecarOutputBoundary.ResolveApprovedRoot(args));
            if (!boundary.IsAllowed)
            {
                log?.Report(new SidecarLog("error", boundary.Rejection ?? "Output rejected."));
                return new SidecarResult(
                    Success: false,
                    OutputPath: null,
                    SizeBytes: null,
                    ErrorCode: "output_outside_destination",
                    ErrorMessage: boundary.Rejection,
                    ExitCode: exitCode);
            }

            finalOutput = boundary.CanonicalPath;
        }

        // A verified success pins the bar at 100; a failure leaves it where it
        // stopped, because claiming completion for a job that produced nothing
        // is a lie the user then has to untangle.
        var finalProgress = progressTracker.Complete(success);
        progress?.Report(new SidecarProgress(
            finalProgress.Percent,
            finalProgress.Stage,
            finalProgress.EtaSeconds));

        OutputProbeSummary? outputProbe = null;

        // ROADMAP Item 72: post-encode duration validation. Only fires on a
        // successful job whose input/output both look like media files; on
        // anything else (probe missing, sidecar isn't a media converter, etc.)
        // the validator silently no-ops. The job result remains Success even
        // if validation flags truncation — we surface a warn-level log entry
        // so the History page / status text can pick it up without rejecting
        // an output the sidecar itself reported as complete.
        if (success && _options is { ValidateOutputDuration: true } opts)
        {
            try
            {
                var inputPath = ExtractInputPathFromArgs(args);
                if (!string.IsNullOrWhiteSpace(inputPath)
                    && !string.IsNullOrWhiteSpace(finalOutput)
                    && OutputDurationValidator.LooksLikeMedia(inputPath)
                    && OutputDurationValidator.LooksLikeMedia(finalOutput))
                {
                    var ffprobePath = LocateFfprobe();
                    if (!string.IsNullOrWhiteSpace(ffprobePath))
                    {
                        var validation = await OutputDurationValidator.ValidateAsync(
                            ffprobePath!, inputPath!, finalOutput!,
                            opts.MinDurationDeltaSeconds, ct).ConfigureAwait(false);

                        // The probe used to be discarded after one log line, so
                        // a truncation warning could not be reviewed afterwards.
                        // Keep it on the job record.
                        outputProbe = new OutputProbeSummary(
                            SizeBytes: finalSize,
                            DurationSeconds: validation.OutputSeconds,
                            SourceDurationSeconds: validation.InputSeconds,
                            DurationWithinTolerance: validation.IsValid,
                            Note: validation.Reason);

                        if (!validation.IsValid)
                        {
                            log?.Report(new SidecarLog(
                                "warn",
                                $"PARTIAL / TRUNCATED — {validation.Reason}. " +
                                "Disable in Settings → Advanced if false-positive."));
                        }
                    }
                }
            }
            catch
            {
                // Validation is opportunistic — never propagate a probe error
                // back into the sidecar result.
            }
        }

        outputProbe ??= finalSize is not null
            ? new OutputProbeSummary(finalSize, null, null, null, null)
            : null;

        if (capability is { Selected: "pending" })
        {
            capability = capability with
            {
                Selected = "unknown",
                Reason = "The sidecar did not report which encoder it selected.",
            };
        }

        return new SidecarResult(
            Success: success,
            OutputPath: finalOutput,
            SizeBytes: finalSize,
            ErrorCode: success ? null : (errorCode ?? "exit_nonzero"),
            ErrorMessage: success ? null : (errorMessage ?? $"Sidecar exited with code {exitCode}"),
            ExitCode: exitCode)
        {
            Provenance = BuildProvenance(
                toolName,
                exe,
                argumentVector,
                startedUtc,
                stopwatch.Elapsed,
                finalOutput,
                outputProbe,
                exitCode,
                success,
                success ? null : (errorCode ?? "exit_nonzero"),
                capability),
            Capability = capability,
        };
    }

    /// <summary>
    /// Assembles the immutable record of how one output was produced. Every
    /// string is redacted at capture so the result can go straight into a
    /// diagnostics bundle or a bug report.
    /// </summary>
    private JobProvenance BuildProvenance(
        string toolName,
        string executablePath,
        IReadOnlyList<string> args,
        DateTime startedUtc,
        TimeSpan duration,
        string? outputPath,
        OutputProbeSummary? outputProbe,
        int exitCode,
        bool success,
        string? errorCode,
        CapabilityDecision? capability)
    {
        var inputPath = ExtractInputPathFromArgs(args);
        return new JobProvenance
        {
            StartedUtc = startedUtc,
            DurationSeconds = duration.TotalSeconds,
            Engine = toolName,
            RedactedArgs = [.. ArgumentRedactor.Redact(args)],
            Executable = ExecutableIdentity.Capture(
                toolName,
                executablePath,
                ResolveExecutableVersion(executablePath)),
            Input = FileIdentity.Capture(inputPath),
            Output = FileIdentity.Capture(outputPath),
            Capability = capability,
            OutputProbe = outputProbe,
            ProductVersion = typeof(SidecarRunner).Assembly.GetName().Version?.ToString(3),
            ExitCode = exitCode,
            Succeeded = success,
            ErrorCode = errorCode,
        };
    }

    private static CapabilityDecision? InferCapability(IReadOnlyList<string> args)
    {
        var encoder = GetArgumentValue(args, "--encoder");
        if (!string.IsNullOrWhiteSpace(encoder))
            return new CapabilityDecision("software", encoder, false, null);

        var accelerator = GetArgumentValue(args, "--hwaccel");
        if (string.IsNullOrWhiteSpace(accelerator))
            return null;
        if (accelerator.Equals("none", StringComparison.OrdinalIgnoreCase))
            return new CapabilityDecision("software", "software", false, null);

        return new CapabilityDecision(accelerator, "pending", false, null);
    }

    private static CapabilityDecision? ObserveCapabilityLog(
        CapabilityDecision? current,
        string message)
    {
        if (string.IsNullOrWhiteSpace(message))
            return current;

        if (message.StartsWith("Hardware accelerator:", StringComparison.OrdinalIgnoreCase)
            && message.Contains("-> encoder:", StringComparison.OrdinalIgnoreCase))
        {
            var separator = message.IndexOf("-> encoder:", StringComparison.OrdinalIgnoreCase);
            var requested = message["Hardware accelerator:".Length..separator].Trim();
            var selected = message[(separator + "-> encoder:".Length)..].Trim();
            return new CapabilityDecision(
                current?.Requested ?? requested,
                selected,
                false,
                null);
        }

        if (message.StartsWith("D3D12 zero-copy enabled:", StringComparison.OrdinalIgnoreCase)
            && message.Contains("->", StringComparison.Ordinal))
        {
            var selected = message[(message.LastIndexOf("->", StringComparison.Ordinal) + 2)..].Trim();
            return new CapabilityDecision(
                current?.Requested ?? "d3d12",
                selected,
                false,
                null);
        }

        const string fallbackMarker = "falling back to software ";
        var fallbackIndex = message.IndexOf(fallbackMarker, StringComparison.OrdinalIgnoreCase);
        if (fallbackIndex >= 0)
        {
            var selected = message[(fallbackIndex + fallbackMarker.Length)..]
                .Trim()
                .TrimEnd('.');
            return new CapabilityDecision(
                current?.Requested ?? "hardware",
                string.IsNullOrWhiteSpace(selected) ? "software" : selected,
                true,
                ArgumentRedactor.RedactMessage(message));
        }

        return current;
    }

    private static string? GetArgumentValue(IReadOnlyList<string> args, string option)
    {
        for (var index = 0; index < args.Count; index++)
        {
            var argument = args[index];
            if (argument.Equals(option, StringComparison.OrdinalIgnoreCase))
                return index + 1 < args.Count ? args[index + 1] : null;
            if (argument.StartsWith(option + "=", StringComparison.OrdinalIgnoreCase))
                return argument[(option.Length + 1)..];
        }

        return null;
    }

    private static string? ResolveExecutableVersion(string? executablePath)
    {
        if (string.IsNullOrWhiteSpace(executablePath))
        {
            return null;
        }

        try
        {
            var info = FileVersionInfo.GetVersionInfo(executablePath);
            return string.IsNullOrWhiteSpace(info.FileVersion)
                ? info.ProductVersion
                : info.FileVersion;
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return null;
        }
    }

    private SidecarWorkspace? TryCreatePrivateWorkspace(
        ProcessStartInfo startInfo,
        IProgress<SidecarLog>? log)
    {
        if (_options?.UsePrivateSidecarTemp == false)
        {
            return null;
        }

        try
        {
            var workspace = SidecarWorkspace.Create();
            workspace.ApplyTo(startInfo.EnvironmentVariables);
            return workspace;
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            log?.Report(new SidecarLog(
                "warn",
                $"Could not create a private job workspace ({exception.Message}); "
                + "the sidecar will use the shared temp directory."));
            return null;
        }
    }

    private ProcessContainmentLimits BuildContainmentLimits()
    {
        if (_options is null)
        {
            return ProcessContainmentLimits.Default;
        }

        var memoryBytes = _options.SidecarMaxMemoryMegabytes > 0
            ? (long)_options.SidecarMaxMemoryMegabytes * 1024L * 1024L
            : ProcessContainmentLimits.Default.MaxMemoryBytes;
        return new ProcessContainmentLimits(
            MaxProcesses: Math.Max(0, _options.SidecarMaxProcesses),
            MaxMemoryBytes: memoryBytes,
            MaxRuntime: _options.SidecarMaxRuntime);
    }

    private string? ResolveManagedToolsBin()
    {
        if (!string.IsNullOrWhiteSpace(_options?.ToolsBasePath))
            return Path.Combine(_options.ToolsBasePath, "bin");

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "tools", "bin");
            if (Directory.Exists(candidate))
                return candidate;
            dir = dir.Parent;
        }

        return null;
    }

    private FfmpegReviewConfiguration? ConfigureFfmpegReview(
        ProcessStartInfo sidecarStartInfo,
        string? toolsBin,
        IProgress<SidecarLog>? log)
    {
        if (_options?.EnableFfmpegCommandEditing != true || _ffmpegCommandReview is null)
            return null;

        var realFfmpeg = ResolveRealFfmpegPath(toolsBin);
        if (realFfmpeg is null)
            return null;

        var proxy = ResolveFfmpegProxyPath();
        if (proxy is null)
        {
            log?.Report(new SidecarLog(
                "warn",
                "FFmpeg command editing is enabled, but the packaged review proxy was not found. The sidecar will use the generated command unchanged."));
            return null;
        }

        var pipeName = $"ucx-ffmpeg-{Guid.NewGuid():N}";
        sidecarStartInfo.EnvironmentVariables["UCX_FFMPEG_PIPE"] = pipeName;
        sidecarStartInfo.EnvironmentVariables["UCX_REAL_FFMPEG"] = realFfmpeg;
        sidecarStartInfo.EnvironmentVariables["FFMPEG_PATH"] = proxy;

        var proxyDirectory = Path.GetDirectoryName(proxy)!;
        var inheritedPath = sidecarStartInfo.EnvironmentVariables["PATH"] ?? "";
        sidecarStartInfo.EnvironmentVariables["PATH"] = string.IsNullOrWhiteSpace(inheritedPath)
            ? proxyDirectory
            : proxyDirectory + Path.PathSeparator + inheritedPath;
        return new FfmpegReviewConfiguration(pipeName);
    }

    private string? ResolveRealFfmpegPath(string? toolsBin)
    {
        var executable = OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg";
        if (!string.IsNullOrWhiteSpace(toolsBin))
        {
            var managed = Path.Combine(toolsBin, executable);
            if (File.Exists(managed))
                return Path.GetFullPath(managed);
        }

        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var directory in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), executable);
                if (File.Exists(candidate))
                    return Path.GetFullPath(candidate);
            }
            catch { }
        }

        return null;
    }

    private static string? ResolveFfmpegProxyPath()
    {
        var executable = OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg";
        var directCandidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools", "ffmpeg-proxy", executable),
            Path.Combine(AppContext.BaseDirectory, "ffmpeg-proxy", executable),
        };
        foreach (var candidate in directCandidates)
        {
            if (File.Exists(candidate))
                return Path.GetFullPath(candidate);
        }

        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var projectDirectory = Path.Combine(directory.FullName, "src", "UniversalConverterX.FfmpegProxy", "bin");
            if (Directory.Exists(projectDirectory))
            {
                try
                {
                    var candidate = Directory
                        .EnumerateFiles(projectDirectory, executable, SearchOption.AllDirectories)
                        .OrderByDescending(File.GetLastWriteTimeUtc)
                        .FirstOrDefault();
                    if (candidate is not null)
                        return Path.GetFullPath(candidate);
                }
                catch { }
            }
            directory = directory.Parent;
        }

        return null;
    }

    private async Task RunFfmpegReviewServerAsync(
        FfmpegReviewConfiguration configuration,
        Action suspendWatchdog,
        Action reportActivity,
        IProgress<SidecarLog>? log,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await using var pipe = new NamedPipeServerStream(
                    configuration.PipeName,
                    PipeDirection.InOut,
                    1,
                    PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
                await pipe.WaitForConnectionAsync(cancellationToken).ConfigureAwait(false);
                reportActivity();

                using var reader = new StreamReader(pipe, new UTF8Encoding(false), leaveOpen: true);
                using var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true)
                {
                    AutoFlush = true,
                };
                var line = await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                ProxyReviewResponse response;
                if (string.IsNullOrWhiteSpace(line) || line.Length > 1_000_000)
                {
                    response = new(false, null, "FFmpeg review proxy sent an invalid request.");
                }
                else
                {
                    var request = JsonSerializer.Deserialize<ProxyReviewRequest>(
                        line,
                        new JsonSerializerOptions(JsonSerializerDefaults.Web));
                    if (request is null || request.Arguments is null or { Length: 0 })
                    {
                        response = new(false, null, "FFmpeg review proxy sent an empty argument vector.");
                    }
                    else
                    {
                        FfmpegCommandReviewResult reviewed;
                        suspendWatchdog();
                        try
                        {
                            reviewed = await _ffmpegCommandReview!.ReviewAsync(
                                new FfmpegCommandReviewRequest(request.ProcessId, request.Arguments),
                                cancellationToken).ConfigureAwait(false);
                        }
                        finally
                        {
                            reportActivity();
                        }
                        response = new(
                            reviewed.Approved,
                            reviewed.Approved ? reviewed.Arguments.ToArray() : null,
                            reviewed.Error);
                    }
                }

                await writer.WriteLineAsync(JsonSerializer.Serialize(
                    response,
                    new JsonSerializerOptions(JsonSerializerDefaults.Web))).ConfigureAwait(false);
                reportActivity();
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                log?.Report(new SidecarLog(
                    "warn",
                    $"FFmpeg command review rejected a proxy request: {exception.Message}"));
            }
        }
    }

    private sealed record FfmpegReviewConfiguration(string PipeName);

    private sealed record ProxyReviewRequest(int ProcessId, string[]? Arguments);

    private sealed record ProxyReviewResponse(bool Approved, string[]? Arguments, string? Error);

    /// <summary>
    /// Scan a sidecar argv for <c>--input &lt;path&gt;</c> and return the path.
    /// All NDJSON-contract sidecars use this flag (see tools/README.md). When
    /// the convention isn't followed the validator falls through silently.
    /// </summary>
    private static string? ExtractInputPathFromArgs(IEnumerable<string> args)
    {
        string? next = null;
        foreach (var arg in args)
        {
            if (next is not null)
                return arg;
            if (string.Equals(arg, "--input", StringComparison.OrdinalIgnoreCase))
                next = arg;
        }
        return null;
    }

    /// <summary>
    /// Resolve a bundled FFprobe binary near the tools/ root. Caches the
    /// first hit on disk for the process lifetime.
    /// </summary>
    private static string? _cachedFfprobe;
    private static string? LocateFfprobe()
    {
        if (_cachedFfprobe is not null) return _cachedFfprobe.Length == 0 ? null : _cachedFfprobe;
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            foreach (var rel in new[]
            {
                Path.Combine("tools", "ffmpeg", "ffprobe.exe"),
                Path.Combine("tools", "_bin", "ffprobe.exe"),
                Path.Combine("tools", "videocrush", "ffprobe.exe"),
                Path.Combine("tools", "clipforge", "ffprobe.exe"),
            })
            {
                var candidate = Path.Combine(dir.FullName, rel);
                if (File.Exists(candidate)) { _cachedFfprobe = candidate; return candidate; }
            }
            dir = dir.Parent;
        }
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var p in path.Split(';'))
        {
            try
            {
                if (string.IsNullOrWhiteSpace(p)) continue;
                var candidate = Path.Combine(p.Trim(), "ffprobe.exe");
                if (File.Exists(candidate)) { _cachedFfprobe = candidate; return candidate; }
            }
            catch { }
        }
        _cachedFfprobe = "";
        return null;
    }

    /// <summary>
    /// Returns the shared model cache directory for ONNX/AI sidecars, or null
    /// if no known tools/ root can be found.
    /// Resolves to tools/_models/ adjacent to the tools/ directory discovered
    /// by the same walk used in <see cref="Locate"/>.
    /// </summary>
    private static string? ResolveModelCacheDirectory()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var toolsDir = Path.Combine(dir.FullName, "tools");
            if (Directory.Exists(toolsDir))
                return Path.Combine(toolsDir, "_models");
            dir = dir.Parent;
        }

        var localApp = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "tools");
        if (Directory.Exists(localApp))
            return Path.Combine(localApp, "_models");

        return null;
    }
}
