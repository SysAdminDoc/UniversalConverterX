using System.Runtime.InteropServices;
using UniversalConverterX.Console.Commands;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class ServeMetricsContractTests
{
    [Fact]
    public void MetricsSnapshotUsesCanonicalEngineKeysForLiveJobs()
    {
        Assert.Equal("converter", JobManager.NormalizeMetricEngine(" Converter "));
    }

    [Fact]
    public void NullExitCodeIsUnknownRatherThanFailed()
    {
        var counters = new JobManager.EngineJobCounters();

        counters.MarkStarted();
        counters.MarkCompleted(null);

        var snapshot = counters.Snapshot("converter", running: 0, retained: 1);

        Assert.Equal(1, snapshot.Started);
        Assert.Equal(0, snapshot.Succeeded);
        Assert.Equal(0, snapshot.Failed);
    }

    [Fact]
    public async Task MixedCaseEngineKeepsLiveMetricsAttachedToItsCounter()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return;

        var manager = new JobManager(configuredMaxConcurrentJobs: 1);
        try
        {
            var result = await manager.StartAsync(
                "Converter",
                Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                ["/c", "ping -n 20 127.0.0.1 > nul"]);

            Assert.Equal(JobStartStatus.Started, result.Status);

            UcxEngineMetricSnapshot? snapshot = null;
            for (var attempt = 0; attempt < 100; attempt++)
            {
                snapshot = Assert.Single(manager.MetricsSnapshot());
                if (snapshot.Running == 1)
                    break;
                await Task.Delay(10, TestContext.Current.CancellationToken);
            }

            var liveSnapshot = snapshot ?? throw new InvalidOperationException("No metrics snapshot was produced.");
            Assert.Equal("converter", liveSnapshot.Engine);
            Assert.Equal(1, liveSnapshot.Started);
            Assert.Equal(1, liveSnapshot.Running);
            Assert.Equal(1, liveSnapshot.Retained);
        }
        finally
        {
            manager.KillAll();
        }
    }
}
