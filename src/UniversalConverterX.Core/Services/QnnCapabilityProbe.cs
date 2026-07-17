using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace UniversalConverterX.Core.Services;

public enum QnnProbeStatus
{
    Ready,
    NotArm64,
    PythonUnavailable,
    RuntimeUnavailable,
    ProviderUnavailable,
    WrongPythonArchitecture,
    ProbeFailed,
}

public sealed record QnnCapabilityReport(
    QnnProbeStatus Status,
    bool Ready,
    string ProcessArchitecture,
    string OperatingSystemArchitecture,
    string? PythonArchitecture,
    string? OnnxRuntimeVersion,
    IReadOnlyList<string> Providers,
    string Detail);

/// <summary>
/// Performs a local-only ONNX Runtime QNN provider probe. It never installs a
/// package, downloads a model, or treats a provider name as inference proof.
/// </summary>
public static class QnnCapabilityProbe
{
    private const string ProbeScript = """
        import json, platform
        result = {"pythonArchitecture": platform.machine(), "version": None, "providers": [], "error": None}
        try:
            import onnxruntime as ort
            result["version"] = getattr(ort, "__version__", None)
            result["providers"] = list(ort.get_available_providers())
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, ensure_ascii=True))
        """;

    public static async Task<QnnCapabilityReport> ProbeAsync(
        string? pythonPath = null,
        CancellationToken cancellationToken = default)
    {
        var executable = string.IsNullOrWhiteSpace(pythonPath)
            ? Environment.GetEnvironmentVariable("UCX_PYTHON_PATH") ?? "python"
            : pythonPath;
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add("-c");
        startInfo.ArgumentList.Add(ProbeScript);
        startInfo.Environment["PYTHONUTF8"] = "1";
        startInfo.Environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1";

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
                return Failed(QnnProbeStatus.PythonUnavailable, "Python could not be started.");
        }
        catch (Exception exception) when (exception is IOException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            return Failed(QnnProbeStatus.PythonUnavailable,
                $"Python is unavailable: {exception.Message}");
        }

        var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(20));
        try
        {
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            try { process.Kill(entireProcessTree: true); } catch { }
            return Failed(QnnProbeStatus.ProbeFailed, "Python provider probe timed out after 20 seconds.");
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        if (process.ExitCode != 0 || string.IsNullOrWhiteSpace(stdout))
        {
            var detail = string.IsNullOrWhiteSpace(stderr)
                ? $"Python provider probe exited with code {process.ExitCode}."
                : stderr.Trim();
            return Failed(QnnProbeStatus.ProbeFailed, detail);
        }

        try
        {
            var payload = JsonSerializer.Deserialize<ProbePayload>(stdout.Trim(), JsonOptions);
            if (payload is null)
                return Failed(QnnProbeStatus.ProbeFailed, "Python provider probe returned no payload.");
            return Assess(
                RuntimeInformation.ProcessArchitecture,
                RuntimeInformation.OSArchitecture,
                payload.PythonArchitecture,
                payload.Version,
                payload.Providers ?? [],
                payload.Error);
        }
        catch (JsonException exception)
        {
            return Failed(QnnProbeStatus.ProbeFailed,
                $"Python provider probe returned invalid JSON: {exception.Message}");
        }
    }

    public static QnnCapabilityReport Assess(
        Architecture processArchitecture,
        Architecture operatingSystemArchitecture,
        string? pythonArchitecture,
        string? onnxRuntimeVersion,
        IReadOnlyList<string> providers,
        string? runtimeError = null)
    {
        var process = processArchitecture.ToString();
        var os = operatingSystemArchitecture.ToString();
        var providerList = providers.Order(StringComparer.Ordinal).ToArray();
        if (!string.IsNullOrWhiteSpace(runtimeError))
        {
            return new(QnnProbeStatus.RuntimeUnavailable, false, process, os,
                pythonArchitecture, onnxRuntimeVersion, providerList,
                $"ONNX Runtime could not be loaded: {runtimeError}");
        }
        if (operatingSystemArchitecture != Architecture.Arm64)
        {
            return new(QnnProbeStatus.NotArm64, false, process, os,
                pythonArchitecture, onnxRuntimeVersion, providerList,
                "QNN is a Snapdragon ARM64 target; this operating system is not ARM64.");
        }
        if (!IsArm64(pythonArchitecture))
        {
            return new(QnnProbeStatus.WrongPythonArchitecture, false, process, os,
                pythonArchitecture, onnxRuntimeVersion, providerList,
                "The selected Python runtime is not ARM64; use an ARM64 Python and ARM64 ONNX Runtime QNN package.");
        }
        if (!providerList.Contains("QNNExecutionProvider", StringComparer.Ordinal))
        {
            return new(QnnProbeStatus.ProviderUnavailable, false, process, os,
                pythonArchitecture, onnxRuntimeVersion, providerList,
                "ONNX Runtime loaded, but QNNExecutionProvider is not available.");
        }
        return new(QnnProbeStatus.Ready, true, process, os,
            pythonArchitecture, onnxRuntimeVersion, providerList,
            "ARM64 ONNX Runtime exposes QNNExecutionProvider. Run the on-device inference acceptance smoke before enabling a QNN workload.");
    }

    private static bool IsArm64(string? architecture) =>
        architecture?.Equals("arm64", StringComparison.OrdinalIgnoreCase) == true ||
        architecture?.Equals("aarch64", StringComparison.OrdinalIgnoreCase) == true;

    private static QnnCapabilityReport Failed(QnnProbeStatus status, string detail) =>
        new(status, false,
            RuntimeInformation.ProcessArchitecture.ToString(),
            RuntimeInformation.OSArchitecture.ToString(),
            null, null, [], detail);

    private sealed class ProbePayload
    {
        public string? PythonArchitecture { get; init; }
        public string? Version { get; init; }
        public List<string>? Providers { get; init; }
        public string? Error { get; init; }
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };
}
