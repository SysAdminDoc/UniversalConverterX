using System.Diagnostics;
using System.Text.Json;

namespace UniversalConverterX.UI.Services;

public sealed record SidecarProgress(double Percent, string Stage, int? EtaSeconds);

public sealed record SidecarLog(string Level, string Message);

public sealed record SidecarResult(
    bool Success,
    string? OutputPath,
    long? SizeBytes,
    string? ErrorCode,
    string? ErrorMessage,
    int ExitCode);

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
    public string? Locate(string toolName)
    {
        if (string.IsNullOrWhiteSpace(toolName)) return null;
        // Reject any input that could escape the tools/ root via traversal.
        if (toolName.IndexOfAny(['/', '\\', ':', '\0']) >= 0 || toolName == "." || toolName == "..")
            return null;

        var exeName = toolName + ".exe";

        // Walk up from BaseDirectory checking the three layouts a frozen sidecar
        // can take: PyInstaller one-folder builds drop to dist/, classic builds
        // place the exe alongside sidecar.py, and the old tools-bin convention
        // groups everything under bin/. PresetRunner / ServeCommand mirror this
        // search order so the UI and CLI agree on which binary to run.
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            foreach (var rel in new[]
            {
                Path.Combine("tools", toolName, "dist", exeName),
                Path.Combine("tools", toolName, exeName),
                Path.Combine("tools", toolName, "bin", exeName),
            })
            {
                var candidate = Path.Combine(dir.FullName, rel);
                if (File.Exists(candidate)) return candidate;
            }
            dir = dir.Parent;
        }

        // Fall back to %LocalAppData%/UniversalConverterX/tools/<name>/<name>.exe.
        var localApp = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "tools", toolName, exeName);
        if (File.Exists(localApp)) return localApp;

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
                    $"%LocalAppData%/UniversalConverterX/tools/{toolName}/{toolName}.exe.",
                ExitCode: -1);
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
            StandardErrorEncoding  = System.Text.Encoding.UTF8,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

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
        ResetWatchdog();

        try
        {
            process.Start();
        }
        catch (Exception ex)
        {
            return new SidecarResult(
                Success: false,
                OutputPath: null,
                SizeBytes: null,
                ErrorCode: "spawn_failed",
                ErrorMessage: $"Could not launch '{toolName}': {ex.Message}",
                ExitCode: -1);
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
                                progress?.Report(new SidecarProgress(
                                    Percent: root.TryGetProperty("percent", out var p) && p.ValueKind == JsonValueKind.Number ? p.GetDouble() : 0,
                                    Stage: root.TryGetProperty("stage", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() ?? "" : "",
                                    EtaSeconds: root.TryGetProperty("eta_seconds", out var e) && e.ValueKind == JsonValueKind.Number ? e.GetInt32() : null));
                                break;

                            case "log":
                                log?.Report(new SidecarLog(
                                    Level: root.TryGetProperty("level", out var lv) && lv.ValueKind == JsonValueKind.String ? lv.GetString() ?? "info" : "info",
                                    Message: root.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String ? m.GetString() ?? "" : ""));
                                break;

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
        return new SidecarResult(
            Success: success,
            OutputPath: finalOutput,
            SizeBytes: finalSize,
            ErrorCode: success ? null : (errorCode ?? "exit_nonzero"),
            ErrorMessage: success ? null : (errorMessage ?? $"Sidecar exited with code {exitCode}"),
            ExitCode: exitCode);
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

