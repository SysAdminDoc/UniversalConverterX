using UniversalConverterX.Core.Utilities;
using System.Text.Json;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class PrometheusTextExporterTests
{
    private static readonly DateTime Started = new(2026, 7, 17, 10, 0, 0, DateTimeKind.Utc);

    [Fact]
    public void Render_UsesPrometheus004ContractAndLfTermination()
    {
        var text = PrometheusTextExporter.Render(
            "2.28.0",
            Started,
            Started.AddSeconds(12.5),
            [new("converter", 3, 2, 0, 1, 3)]);

        Assert.Equal("text/plain; version=0.0.4; charset=utf-8", PrometheusTextExporter.ContentType);
        Assert.Contains("# TYPE ucx_jobs_started_total counter\n", text);
        Assert.Contains("ucx_jobs_started_total{engine=\"converter\"} 3\n", text);
        Assert.Contains("ucx_jobs_completed_total{engine=\"converter\",status=\"succeeded\"} 2\n", text);
        Assert.Contains("ucx_jobs_running{engine=\"converter\"} 1\n", text);
        Assert.Contains("ucx_server_uptime_seconds 12.5\n", text);
        Assert.EndsWith("\n", text);
        Assert.DoesNotContain("\r", text);
    }

    [Fact]
    public void Render_EscapesUntrustedLabelValues()
    {
        var text = PrometheusTextExporter.Render(
            "2.28\"dev\\local\r\nnext",
            Started,
            Started,
            [new("odd\"engine\\name\nnext", 1, 0, 1, 0, 1)]);

        Assert.Contains("version=\"2.28\\\"dev\\\\local\\nnext\"", text);
        Assert.Contains("engine=\"odd\\\"engine\\\\name\\nnext\"", text);
        Assert.DoesNotContain("odd\"engine", text);
    }

    [Fact]
    public void Render_IsDeterministicAndClampsInvalidSnapshots()
    {
        var text = PrometheusTextExporter.Render(
            "2.28.0",
            Started,
            Started.AddSeconds(-1),
            [
                new("zeta", -1, -2, -3, -4, -5),
                new("alpha", 1, 1, 0, 0, 1),
            ]);

        Assert.True(text.IndexOf("engine=\"alpha\"", StringComparison.Ordinal)
                    < text.IndexOf("engine=\"zeta\"", StringComparison.Ordinal));
        Assert.Contains("ucx_server_uptime_seconds 0\n", text);
        Assert.Contains("ucx_jobs_started_total{engine=\"zeta\"} 0\n", text);
        Assert.Contains("ucx_jobs_retained{engine=\"zeta\"} 0\n", text);
    }

    [Fact]
    public void BundledDashboardAndScrapeConfig_ReferenceExportedMetrics()
    {
        var root = FindRepoRoot();
        var integration = Path.Combine(root, "integrations", "prometheus");
        using var dashboard = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            integration, "universalconverterx-grafana-dashboard.json")));
        var json = dashboard.RootElement.GetRawText();
        var scrape = File.ReadAllText(Path.Combine(integration, "prometheus.yml"));

        Assert.Equal("UniversalConverterX Local Jobs", dashboard.RootElement.GetProperty("title").GetString());
        Assert.Contains("ucx_jobs_running", json);
        Assert.Contains("ucx_jobs_started_total", json);
        Assert.Contains("ucx_jobs_completed_total", json);
        Assert.Contains("127.0.0.1:17654", scrape);
    }

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "README.md"))
                && Directory.Exists(Path.Combine(directory.FullName, "integrations")))
                return directory.FullName;
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException("Could not locate the UniversalConverterX repo root.");
    }
}
