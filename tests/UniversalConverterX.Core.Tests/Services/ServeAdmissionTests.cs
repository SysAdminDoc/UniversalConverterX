using FluentAssertions;
using UniversalConverterX.Console.Commands;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class ServeAdmissionTests
{
    [Fact]
    public async Task AdmissionRejectsRequestsBeyondActiveAndQueuedCapacity()
    {
        var admission = new JobAdmissionController(maxConcurrentJobs: 1, maxQueueDepth: 1);
        var first = await admission.TryAcquireAsync();
        first.Should().NotBeNull();

        var queued = admission.TryAcquireAsync();
        var rejected = await admission.TryAcquireAsync();
        rejected.Should().BeNull();

        first!.Dispose();
        var second = await queued;
        second.Should().NotBeNull();
        second!.Dispose();

        var replacement = await admission.TryAcquireAsync();
        replacement.Should().NotBeNull();
        replacement!.Dispose();
    }

    [Fact]
    public async Task StopRejectsNewAndQueuedAdmissions()
    {
        var admission = new JobAdmissionController(maxConcurrentJobs: 1, maxQueueDepth: 1);
        var first = await admission.TryAcquireAsync();
        var queued = admission.TryAcquireAsync();

        admission.Stop();

        (await queued).Should().BeNull();
        (await admission.TryAcquireAsync()).Should().BeNull();
        first!.Dispose();
    }

    [Fact]
    public void JobManagerSharesContainmentBudgetAcrossConfiguredConcurrency()
    {
        var manager = new JobManager(configuredMaxConcurrentJobs: 4, configuredQueueDepth: 2);

        manager.MaxConcurrentJobs.Should().Be(4);
        manager.MaxQueueDepth.Should().Be(2);

        var defaults = ProcessContainmentLimits.Default;
        if (defaults.MaxMemoryBytes > 0)
        {
            manager.ContainmentLimits.MaxMemoryBytes
                .Should().Be(defaults.MaxMemoryBytes / 4);
        }
        if (defaults.MaxProcesses > 0)
        {
            manager.ContainmentLimits.MaxProcesses
                .Should().Be(Math.Max(1, defaults.MaxProcesses / 4));
        }
    }
}
