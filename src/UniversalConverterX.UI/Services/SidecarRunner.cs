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

    Task<SidecarResult> RunAsync(
        string toolName,
        IEnumerable<string> args,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken ct = default);
}

public sealed class SidecarRunner : ISidecarRunner
{
    public string? Locate(string toolName)
    {
        var exeName = toolName + ".exe";

        // 1) Walk up from BaseDirectory looking for tools/<name>/<name>.exe
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "tools", toolName, exeName);
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }

        // 2) %LocalAppData%/UniversalConverterX/tools/<name>/<name>.exe
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
        CancellationToken ct = default)
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
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);

        // Inject the shared model cache directory as an environment variable.
        // ONNX-based sidecars can read UCX_MODEL_DIR to locate/store models in a
        // single location instead of per-tool subdirectories.
        var modelCacheDir = ResolveModelCacheDirectory();
        if (modelCacheDir is not null)
        {
            psi.EnvironmentVariables["UCX_MODEL_DIR"] = modelCacheDir;
            Directory.CreateDirectory(modelCacheDir);
        }

        using var process = new Process { StartInfo = psi };

        string? finalOutput = null;
        long? finalSize = null;
        string? errorCode = null;
        string? errorMessage = null;

        process.Start();

        // Stream stdout line-by-line, parsing NDJSON.
        var stdoutTask = Task.Run(async () =>
        {
            try
            {
                while (!process.StandardOutput.EndOfStream)
                {
                    ct.ThrowIfCancellationRequested();
                    var line = await process.StandardOutput.ReadLineAsync(ct).ConfigureAwait(false);
                    if (string.IsNullOrWhiteSpace(line)) continue;

                    try
                    {
                        using var doc = JsonDocument.Parse(line);
                        var root = doc.RootElement;
                        if (!root.TryGetProperty("event", out var ev)) continue;
                        var evName = ev.GetString();

                        switch (evName)
                        {
                            case "progress":
                                progress?.Report(new SidecarProgress(
                                    Percent: root.TryGetProperty("percent", out var p) && p.ValueKind == JsonValueKind.Number ? p.GetDouble() : 0,
                                    Stage: root.TryGetProperty("stage", out var s) ? s.GetString() ?? "" : "",
                                    EtaSeconds: root.TryGetProperty("eta_seconds", out var e) && e.ValueKind == JsonValueKind.Number ? e.GetInt32() : null));
                                break;

                            case "log":
                                log?.Report(new SidecarLog(
                                    Level: root.TryGetProperty("level", out var lv) ? lv.GetString() ?? "info" : "info",
                                    Message: root.TryGetProperty("message", out var m) ? m.GetString() ?? "" : ""));
                                break;

                            case "complete":
                                finalOutput = root.TryGetProperty("output", out var o) ? o.GetString() : null;
                                finalSize = root.TryGetProperty("size_bytes", out var sb) && sb.ValueKind == JsonValueKind.Number ? sb.GetInt64() : null;
                                break;

                            case "error":
                                errorCode = root.TryGetProperty("code", out var c) ? c.GetString() : "unknown";
                                errorMessage = root.TryGetProperty("message", out var em) ? em.GetString() : null;
                                break;
                        }
                    }
                    catch (JsonException)
                    {
                        // Sidecar wrote a non-JSON line — surface as a log entry.
                        log?.Report(new SidecarLog("debug", line));
                    }
                }
            }
            catch (OperationCanceledException) { /* propagated below */ }
        }, ct);

        // Drain stderr too — sidecars shouldn't write here, but capture anything that leaks.
        var stderrTask = Task.Run(async () =>
        {
            try
            {
                var stderr = await process.StandardError.ReadToEndAsync().ConfigureAwait(false);
                if (!string.IsNullOrWhiteSpace(stderr))
                {
                    foreach (var ln in stderr.Split('\n'))
                        if (!string.IsNullOrWhiteSpace(ln))
                            log?.Report(new SidecarLog("stderr", ln.TrimEnd('\r')));
                }
            }
            catch { /* swallow — best-effort */ }
        }, ct);

        try
        {
            await process.WaitForExitAsync(ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { /* swallow */ }
            return new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", -1);
        }

        await Task.WhenAll(stdoutTask, stderrTask).ConfigureAwait(false);

        var success = process.ExitCode == 0 && errorCode is null;
        return new SidecarResult(
            Success: success,
            OutputPath: finalOutput,
            SizeBytes: finalSize,
            ErrorCode: success ? null : (errorCode ?? "exit_nonzero"),
            ErrorMessage: success ? null : (errorMessage ?? $"Sidecar exited with code {process.ExitCode}"),
            ExitCode: process.ExitCode);
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
