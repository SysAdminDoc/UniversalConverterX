using System.Globalization;
using System.Text;

namespace UniversalConverterX.Core.Utilities;

/// <summary>One immutable per-engine view of the loopback automation server.</summary>
public sealed record UcxEngineMetricSnapshot(
    string Engine,
    long Started,
    long Succeeded,
    long Failed,
    int Running,
    int Retained);

/// <summary>
/// Dependency-free Prometheus 0.0.4 text exposition for the loopback REST
/// server. Keeping formatting in Core makes escaping and metric semantics
/// independently testable without starting a listener.
/// </summary>
public static class PrometheusTextExporter
{
    public const string ContentType = "text/plain; version=0.0.4; charset=utf-8";

    public static string Render(
        string version,
        DateTime serverStartedUtc,
        DateTime observedUtc,
        IEnumerable<UcxEngineMetricSnapshot> engines)
    {
        ArgumentNullException.ThrowIfNull(version);
        ArgumentNullException.ThrowIfNull(engines);

        serverStartedUtc = serverStartedUtc.ToUniversalTime();
        observedUtc = observedUtc.ToUniversalTime();
        var uptime = Math.Max(0, (observedUtc - serverStartedUtc).TotalSeconds);
        var builder = new StringBuilder();

        Line(builder, "# HELP ucx_build_info UniversalConverterX build identity.");
        Line(builder, "# TYPE ucx_build_info gauge");
        Line(builder, $"ucx_build_info{{version=\"{EscapeLabel(version)}\"}} 1");
        Line(builder, "# HELP ucx_server_start_time_seconds Unix time when this ucx serve process started.");
        Line(builder, "# TYPE ucx_server_start_time_seconds gauge");
        Line(builder, $"ucx_server_start_time_seconds {(new DateTimeOffset(serverStartedUtc).ToUnixTimeMilliseconds() / 1000.0).ToString(CultureInfo.InvariantCulture)}");
        Line(builder, "# HELP ucx_server_uptime_seconds Seconds since this ucx serve process started.");
        Line(builder, "# TYPE ucx_server_uptime_seconds gauge");
        Line(builder, $"ucx_server_uptime_seconds {uptime.ToString("0.###", CultureInfo.InvariantCulture)}");

        Line(builder, "# HELP ucx_jobs_started_total Jobs whose child process started successfully.");
        Line(builder, "# TYPE ucx_jobs_started_total counter");
        Line(builder, "# HELP ucx_jobs_completed_total Completed jobs partitioned by final status.");
        Line(builder, "# TYPE ucx_jobs_completed_total counter");
        Line(builder, "# HELP ucx_jobs_running Jobs currently running.");
        Line(builder, "# TYPE ucx_jobs_running gauge");
        Line(builder, "# HELP ucx_jobs_retained Jobs still queryable through the REST API.");
        Line(builder, "# TYPE ucx_jobs_retained gauge");

        foreach (var engine in engines.OrderBy(item => item.Engine, StringComparer.Ordinal))
        {
            var label = EscapeLabel(engine.Engine);
            Line(builder, $"ucx_jobs_started_total{{engine=\"{label}\"}} {Math.Max(0, engine.Started)}");
            Line(builder, $"ucx_jobs_completed_total{{engine=\"{label}\",status=\"succeeded\"}} {Math.Max(0, engine.Succeeded)}");
            Line(builder, $"ucx_jobs_completed_total{{engine=\"{label}\",status=\"failed\"}} {Math.Max(0, engine.Failed)}");
            Line(builder, $"ucx_jobs_running{{engine=\"{label}\"}} {Math.Max(0, engine.Running)}");
            Line(builder, $"ucx_jobs_retained{{engine=\"{label}\"}} {Math.Max(0, engine.Retained)}");
        }
        return builder.ToString();
    }

    private static string EscapeLabel(string value) => value
        .Replace("\r\n", "\n", StringComparison.Ordinal)
        .Replace("\r", "\n", StringComparison.Ordinal)
        .Replace("\\", "\\\\", StringComparison.Ordinal)
        .Replace("\n", "\\n", StringComparison.Ordinal)
        .Replace("\"", "\\\"", StringComparison.Ordinal);

    private static void Line(StringBuilder builder, string value) => builder.Append(value).Append('\n');
}
