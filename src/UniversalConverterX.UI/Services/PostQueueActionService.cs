using System.Diagnostics;
using Microsoft.Extensions.Options;
using Microsoft.Windows.AppNotifications;
using Microsoft.Windows.AppNotifications.Builder;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.UI.Services;

public interface IPostQueueActionService
{
    Task<PostQueueActionResult> ExecuteAsync(
        QueueCompletionSummary summary,
        CancellationToken cancellationToken = default);
}

public sealed class PostQueueActionService : IPostQueueActionService, IPostQueueActionHost
{
    private readonly ConverterXOptions _options;
    private readonly PostQueueActionRunner _runner;

    public PostQueueActionService(IOptions<ConverterXOptions> options)
    {
        _options = options.Value;
        var reportDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "queue-reports");
        _runner = new PostQueueActionRunner(reportDirectory, this);
    }

    public async Task<PostQueueActionResult> ExecuteAsync(
        QueueCompletionSummary summary,
        CancellationToken cancellationToken = default)
    {
        try
        {
            return await _runner.ExecuteAsync(
                    _options.QueueCompletionAction,
                    _options.QueueCompletionScriptPath,
                    _options.ShowNotifications,
                    summary,
                    cancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            return new PostQueueActionResult(
                false,
                _options.QueueCompletionAction,
                $"Post-queue action failed: {ex.Message}");
        }
    }

    public Task NotifyAsync(string title, string message, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var notification = new AppNotificationBuilder()
            .AddText(title)
            .AddText(message)
            .BuildNotification();
        AppNotificationManager.Default.Show(notification);
        return Task.CompletedTask;
    }

    public Task SleepAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        StartHidden(
            Path.Combine(Environment.SystemDirectory, "rundll32.exe"),
            ["powrprof.dll,SetSuspendState", "0,1,0"]);
        return Task.CompletedTask;
    }

    public Task ShutdownAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        StartHidden(
            Path.Combine(Environment.SystemDirectory, "shutdown.exe"),
            ["/s", "/t", "60", "/d", "p:0:0", "/c", "UniversalConverterX queue completed successfully."]);
        return Task.CompletedTask;
    }

    public Task RunScriptAsync(
        string scriptPath,
        string summaryPath,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        StartHidden(
            Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            ["-NoLogo", "-NoProfile", "-NonInteractive", "-File", scriptPath, summaryPath],
            Path.GetDirectoryName(scriptPath));
        return Task.CompletedTask;
    }

    private static void StartHidden(
        string executable,
        IEnumerable<string> arguments,
        string? workingDirectory = null)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            WorkingDirectory = workingDirectory ?? Environment.CurrentDirectory,
        };
        foreach (var argument in arguments)
            startInfo.ArgumentList.Add(argument);
        if (Process.Start(startInfo) is null)
            throw new InvalidOperationException($"Could not start {Path.GetFileName(executable)}.");
    }
}
