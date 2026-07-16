using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Services;

public sealed record QueueCompletionItem
{
    public string Source { get; init; } = "";
    public string? Output { get; init; }
    public QueueCompletionItemStatus Status { get; init; }
    public string? Message { get; init; }
}

public sealed record QueueCompletionSummary
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public string Workflow { get; init; } = "";
    public DateTime StartedUtc { get; init; }
    public DateTime CompletedUtc { get; init; }
    public IReadOnlyList<QueueCompletionItem> Items { get; init; } = [];
    public int Total => Items.Count;
    public int Succeeded => Items.Count(item => item.Status == QueueCompletionItemStatus.Succeeded);
    public int Failed => Items.Count(item => item.Status == QueueCompletionItemStatus.Failed);
    public int Cancelled => Items.Count(item => item.Status == QueueCompletionItemStatus.Cancelled);
    public bool IsClean => Total > 0 && Succeeded == Total;
}

public sealed record PostQueueActionResult(
    bool Executed,
    QueueCompletionAction Action,
    string Message,
    string? ReportPath = null);

public interface IPostQueueActionHost
{
    Task NotifyAsync(string title, string message, CancellationToken cancellationToken);
    Task SleepAsync(CancellationToken cancellationToken);
    Task ShutdownAsync(CancellationToken cancellationToken);
    Task RunScriptAsync(string scriptPath, string summaryPath, CancellationToken cancellationToken);
}

/// <summary>
/// Applies the post-queue safety policy independently of WinUI. Sleep and
/// shutdown run only after a completely successful queue; script hooks run
/// for every outcome and receive an atomic JSON summary path.
/// </summary>
public sealed class PostQueueActionRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() },
    };

    private readonly string _reportDirectory;
    private readonly IPostQueueActionHost _host;

    public PostQueueActionRunner(string reportDirectory, IPostQueueActionHost host)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(reportDirectory);
        _reportDirectory = Path.GetFullPath(reportDirectory);
        _host = host ?? throw new ArgumentNullException(nameof(host));
    }

    public async Task<PostQueueActionResult> ExecuteAsync(
        QueueCompletionAction action,
        string? scriptPath,
        bool notificationsEnabled,
        QueueCompletionSummary summary,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(summary);
        Validate(summary);

        if (action == QueueCompletionAction.None)
            return new(false, action, "No post-queue action is configured.");

        var completionMessage = $"{summary.Succeeded} succeeded, {summary.Failed} failed, {summary.Cancelled} cancelled.";
        if (action == QueueCompletionAction.Notify)
        {
            if (!notificationsEnabled)
                return new(false, action, "Windows notifications are disabled.");
            await _host.NotifyAsync($"{summary.Workflow} queue complete", completionMessage, cancellationToken)
                .ConfigureAwait(false);
            return new(true, action, "Completion notification sent.");
        }

        if (action is QueueCompletionAction.Sleep or QueueCompletionAction.Shutdown
            && !summary.IsClean)
        {
            const string blocked = "Power action skipped because the queue was not completely successful.";
            if (notificationsEnabled)
                await TryNotifyAsync("Queue power action skipped", blocked, cancellationToken).ConfigureAwait(false);
            return new(false, action, blocked);
        }

        if (notificationsEnabled)
            await TryNotifyAsync($"{summary.Workflow} queue complete", completionMessage, cancellationToken)
                .ConfigureAwait(false);

        switch (action)
        {
            case QueueCompletionAction.Sleep:
                await _host.SleepAsync(cancellationToken).ConfigureAwait(false);
                return new(true, action, "Sleep requested after a clean queue.");

            case QueueCompletionAction.Shutdown:
                await _host.ShutdownAsync(cancellationToken).ConfigureAwait(false);
                return new(true, action, "Shutdown scheduled after a clean queue.");

            case QueueCompletionAction.RunScript:
                if (!TryValidateScript(scriptPath, out var fullScriptPath, out var error))
                    return new(false, action, error!);
                var reportPath = await WriteSummaryAsync(summary, cancellationToken).ConfigureAwait(false);
                await _host.RunScriptAsync(fullScriptPath!, reportPath, cancellationToken).ConfigureAwait(false);
                return new(true, action, "Post-queue script started.", reportPath);

            default:
                return new(false, action, "Unsupported post-queue action.");
        }
    }

    private async Task<string> WriteSummaryAsync(
        QueueCompletionSummary summary,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(_reportDirectory);
        var workflow = new string(summary.Workflow
            .Where(character => char.IsLetterOrDigit(character) || character is '-' or '_')
            .ToArray());
        if (string.IsNullOrWhiteSpace(workflow))
            workflow = "queue";
        var path = Path.Combine(
            _reportDirectory,
            $"{DateTime.UtcNow:yyyyMMdd-HHmmss}-{workflow}-{Guid.NewGuid():N}.json");
        var temp = path + ".tmp";
        try
        {
            var json = JsonSerializer.Serialize(summary, JsonOptions) + Environment.NewLine;
            await File.WriteAllTextAsync(
                    temp,
                    json,
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                    cancellationToken)
                .ConfigureAwait(false);
            File.Move(temp, path, overwrite: false);
            return path;
        }
        finally
        {
            try { File.Delete(temp); } catch { }
        }
    }

    private async Task TryNotifyAsync(
        string title,
        string message,
        CancellationToken cancellationToken)
    {
        try
        {
            await _host.NotifyAsync(title, message, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            // A toast is supplementary to power/script actions and must not
            // prevent the explicitly configured primary action from running.
        }
    }

    private static bool TryValidateScript(
        string? scriptPath,
        out string? fullPath,
        out string? error)
    {
        fullPath = null;
        error = null;
        if (string.IsNullOrWhiteSpace(scriptPath))
        {
            error = "No post-queue script is configured.";
            return false;
        }

        try { fullPath = Path.GetFullPath(scriptPath); }
        catch (Exception ex)
        {
            error = $"The post-queue script path is invalid: {ex.Message}";
            return false;
        }

        var extension = Path.GetExtension(fullPath);
        if (!string.Equals(extension, ".ps1", StringComparison.OrdinalIgnoreCase))
        {
            error = "Post-queue scripts must be a PowerShell .ps1 file.";
            return false;
        }
        if (!File.Exists(fullPath))
        {
            error = "The configured post-queue script does not exist.";
            return false;
        }

        return true;
    }

    private static void Validate(QueueCompletionSummary summary)
    {
        if (summary.SchemaVersion != QueueCompletionSummary.CurrentSchemaVersion)
            throw new ArgumentException("Unsupported queue summary schema version.", nameof(summary));
        if (string.IsNullOrWhiteSpace(summary.Workflow))
            throw new ArgumentException("Queue workflow is required.", nameof(summary));
        if (summary.CompletedUtc < summary.StartedUtc)
            throw new ArgumentException("Queue completion time cannot precede its start time.", nameof(summary));
        if (summary.Items.Count == 0)
            throw new ArgumentException("Queue summary must contain at least one item.", nameof(summary));
    }
}
