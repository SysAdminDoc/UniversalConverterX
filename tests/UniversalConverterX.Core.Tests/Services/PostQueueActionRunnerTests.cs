using System.Text.Json;
using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class PostQueueActionRunnerTests : IDisposable
{
    private readonly string _tempDirectory = Path.Combine(
        Path.GetTempPath(),
        $"ucx-post-queue-tests-{Guid.NewGuid():N}");

    [Fact]
    public async Task Shutdown_ShouldRunOnlyForCleanQueues()
    {
        var host = new RecordingHost();
        var runner = CreateRunner(host);

        var cleanResult = await runner.ExecuteAsync(
            QueueCompletionAction.Shutdown,
            scriptPath: null,
            notificationsEnabled: true,
            CreateSummary(QueueCompletionItemStatus.Succeeded));
        var failedResult = await runner.ExecuteAsync(
            QueueCompletionAction.Shutdown,
            scriptPath: null,
            notificationsEnabled: true,
            CreateSummary(QueueCompletionItemStatus.Failed));

        cleanResult.Executed.Should().BeTrue();
        failedResult.Executed.Should().BeFalse();
        failedResult.Message.Should().Contain("not completely successful");
        host.ShutdownCount.Should().Be(1);
        host.Notifications.Should().HaveCount(2);
    }

    [Fact]
    public async Task RunScript_ShouldReceiveAtomicJsonSummaryForFailedQueues()
    {
        Directory.CreateDirectory(_tempDirectory);
        var scriptPath = Path.Combine(_tempDirectory, "after-queue.ps1");
        File.WriteAllText(scriptPath, "param([string]$summaryPath)");
        var host = new RecordingHost();
        var runner = CreateRunner(host);

        var result = await runner.ExecuteAsync(
            QueueCompletionAction.RunScript,
            scriptPath,
            notificationsEnabled: false,
            CreateSummary(QueueCompletionItemStatus.Failed));

        result.Executed.Should().BeTrue();
        result.ReportPath.Should().NotBeNull();
        File.Exists(result.ReportPath).Should().BeTrue();
        host.ScriptRuns.Should().ContainSingle().Which.Should().Be((scriptPath, result.ReportPath!));

        using var json = JsonDocument.Parse(await File.ReadAllTextAsync(result.ReportPath!));
        json.RootElement.GetProperty("workflow").GetString().Should().Be("Converter");
        json.RootElement.GetProperty("failed").GetInt32().Should().Be(1);
        json.RootElement.GetProperty("items")[0].GetProperty("status").GetString().Should().Be("Failed");
    }

    [Theory]
    [InlineData(null)]
    [InlineData("missing.ps1")]
    [InlineData("unsafe.cmd")]
    [InlineData("tool.exe")]
    public async Task RunScript_ShouldRejectMissingOrUnsupportedScripts(string? scriptPath)
    {
        var host = new RecordingHost();
        var runner = CreateRunner(host);

        var result = await runner.ExecuteAsync(
            QueueCompletionAction.RunScript,
            scriptPath,
            notificationsEnabled: false,
            CreateSummary(QueueCompletionItemStatus.Succeeded));

        result.Executed.Should().BeFalse();
        host.ScriptRuns.Should().BeEmpty();
        Directory.Exists(Path.Combine(_tempDirectory, "reports")).Should().BeFalse();
    }

    [Fact]
    public async Task Notify_ShouldRespectNotificationPreference()
    {
        var host = new RecordingHost();
        var runner = CreateRunner(host);

        var result = await runner.ExecuteAsync(
            QueueCompletionAction.Notify,
            scriptPath: null,
            notificationsEnabled: false,
            CreateSummary(QueueCompletionItemStatus.Succeeded));

        result.Executed.Should().BeFalse();
        host.Notifications.Should().BeEmpty();
    }

    [Fact]
    public async Task NotificationFailure_ShouldNotSuppressPrimaryPowerAction()
    {
        var host = new RecordingHost { ThrowOnNotification = true };
        var runner = CreateRunner(host);

        var result = await runner.ExecuteAsync(
            QueueCompletionAction.Sleep,
            scriptPath: null,
            notificationsEnabled: true,
            CreateSummary(QueueCompletionItemStatus.Succeeded));

        result.Executed.Should().BeTrue();
        host.SleepCount.Should().Be(1);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDirectory))
                Directory.Delete(_tempDirectory, recursive: true);
        }
        catch { }
    }

    private PostQueueActionRunner CreateRunner(RecordingHost host) =>
        new(Path.Combine(_tempDirectory, "reports"), host);

    private static QueueCompletionSummary CreateSummary(QueueCompletionItemStatus status) => new()
    {
        Workflow = "Converter",
        StartedUtc = new DateTime(2026, 7, 16, 12, 0, 0, DateTimeKind.Utc),
        CompletedUtc = new DateTime(2026, 7, 16, 12, 1, 0, DateTimeKind.Utc),
        Items =
        [
            new QueueCompletionItem
            {
                Source = "input.mov",
                Output = status == QueueCompletionItemStatus.Succeeded ? "output.mp4" : null,
                Status = status,
                Message = status == QueueCompletionItemStatus.Failed ? "encode failed" : null,
            },
        ],
    };

    private sealed class RecordingHost : IPostQueueActionHost
    {
        public List<(string Title, string Message)> Notifications { get; } = [];
        public List<(string Script, string Summary)> ScriptRuns { get; } = [];
        public int SleepCount { get; private set; }
        public int ShutdownCount { get; private set; }
        public bool ThrowOnNotification { get; init; }

        public Task NotifyAsync(string title, string message, CancellationToken cancellationToken)
        {
            if (ThrowOnNotification)
                throw new InvalidOperationException("Toast unavailable");
            Notifications.Add((title, message));
            return Task.CompletedTask;
        }

        public Task SleepAsync(CancellationToken cancellationToken)
        {
            SleepCount++;
            return Task.CompletedTask;
        }

        public Task ShutdownAsync(CancellationToken cancellationToken)
        {
            ShutdownCount++;
            return Task.CompletedTask;
        }

        public Task RunScriptAsync(
            string scriptPath,
            string summaryPath,
            CancellationToken cancellationToken)
        {
            ScriptRuns.Add((scriptPath, summaryPath));
            return Task.CompletedTask;
        }
    }
}
