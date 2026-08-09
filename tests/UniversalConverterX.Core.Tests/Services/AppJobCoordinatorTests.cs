using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class AppJobCoordinatorTests : IDisposable
{
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(),
        "ucx-app-job-coordinator-tests",
        Guid.NewGuid().ToString("N"));

    [Fact]
    public void Constructor_RecoversRunningJobsAsInterrupted()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue
        {
            QueueKey = "converter",
            PageName = "Converter",
            Jobs =
            [
                new PersistedBatchJob
                {
                    Id = "running-1",
                    SourcePath = "clip.mov",
                    OutputPath = "clip.mp4",
                    Engine = "converter",
                    Status = "Running",
                },
                new PersistedBatchJob { Id = "done-1", Status = "Completed" },
            ],
        });

        var coordinator = new AppJobCoordinator(store);

        var jobs = coordinator.GetJobs();
        jobs.Single(item => item.Job.Id == "running-1").Job.Status.Should().Be("Interrupted");
        jobs.Single(item => item.Job.Id == "running-1").Job.ErrorMessage
            .Should().Contain("exited");
        jobs.Single(item => item.Job.Id == "done-1").Job.Status.Should().Be("Completed");
        store.Load("converter")!.Jobs.Single(job => job.Id == "running-1").Status
            .Should().Be("Interrupted");
    }

    [Fact]
    public void CancelRetryAndSkip_UseDurableStateAndRuntimeCancellation()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue
        {
            QueueKey = "converter",
            PageName = "Converter",
            Jobs =
            [
                new PersistedBatchJob { Id = "queued-1", Status = "Queued", Engine = "converter" },
                new PersistedBatchJob { Id = "running-1", Status = "Running", Engine = "converter" },
                new PersistedBatchJob { Id = "failed-1", Status = "Failed", Engine = "converter" },
            ],
        });
        var coordinator = new AppJobCoordinator(store);
        var cancelled = false;
        var running = new AppJobHandle("converter", "running-1");
        coordinator.Retry(running).Should().BeTrue();
        coordinator.RegisterCancellation(running, () => cancelled = true);

        coordinator.Cancel(new AppJobHandle("converter", "queued-1")).Should().BeTrue();
        coordinator.Cancel(running).Should().BeTrue();
        cancelled.Should().BeTrue();
        coordinator.Skip(new AppJobHandle("converter", "failed-1")).Should().BeFalse();
        coordinator.Retry(new AppJobHandle("converter", "failed-1")).Should().BeTrue();

        var jobs = coordinator.GetJobs().ToDictionary(item => item.Job.Id);
        jobs["queued-1"].Job.Status.Should().Be("Cancelled");
        jobs["running-1"].Job.Status.Should().Be("Cancelling");
        jobs["failed-1"].Job.Status.Should().Be("Queued");
    }

    [Fact]
    public void SearchAndStatusEvents_ExposeAllWorkflowQueues()
    {
        var store = new JsonBatchQueueStore(_directory);
        store.Save(new PersistedBatchQueue
        {
            QueueKey = "compressor",
            PageName = "Compressor",
            Jobs = [new PersistedBatchJob
            {
                Id = "compress-1",
                SourcePath = @"C:\Media\holiday.mov",
                Engine = "videocrush",
                Status = "Queued",
            }],
        });
        var coordinator = new AppJobCoordinator(store);
        var events = 0;
        coordinator.JobsChanged += (_, _) => events++;

        coordinator.GetJobs("holiday").Should().ContainSingle()
            .Which.DisplayWorkflow.Should().Be("Compressor");
        coordinator.UpdateStatus(
                new AppJobHandle("compressor", "compress-1"),
                "Failed",
                "tool missing")
            .Should().BeTrue();

        events.Should().Be(1);
        coordinator.GetJobs("tool missing").Should().ContainSingle();
    }

    [Fact]
    public void Preflight_SeparatesSourceAndCapabilityBlockersFromWarnings()
    {
        var store = new JsonBatchQueueStore(_directory);
        var source = Path.Combine(_directory, "source.mov");
        var output = Path.Combine(_directory, "output.mp4");
        Directory.CreateDirectory(_directory);
        File.WriteAllText(source, "source");
        File.WriteAllText(output, "existing");

        var coordinator = new AppJobCoordinator(store);
        var result = coordinator.Preflight(
            new PersistedBatchJob
            {
                SourcePath = source,
                OutputPath = output,
                Engine = "converter",
            },
            new AppJobPreflightContext
            {
                ToolsDirectory = Path.Combine(_directory, "missing-tools"),
                CapabilityAvailable = false,
                CapabilityMessage = "The requested encoder is unavailable.",
            });

        result.IsReady.Should().BeFalse();
        result.Blockers.Should().Contain("The requested encoder is unavailable.");
        result.Blockers.Should().NotContain(item => item.Contains("source", StringComparison.OrdinalIgnoreCase));
        result.Warnings.Should().Contain(item => item.Contains("already exists", StringComparison.OrdinalIgnoreCase));
        result.Warnings.Should().Contain(item => item.Contains("tools directory", StringComparison.OrdinalIgnoreCase));
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_directory))
                Directory.Delete(_directory, recursive: true);
        }
        catch { }
    }
}
