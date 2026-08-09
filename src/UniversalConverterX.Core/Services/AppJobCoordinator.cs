namespace UniversalConverterX.Core.Services;

/// <summary>
/// Stable identity for a job in one of the app-scoped durable queues.
/// </summary>
public readonly record struct AppJobHandle(string QueueKey, string JobId)
{
    public string Key => $"{QueueKey}:{JobId}";
}

/// <summary>
/// The blocking and non-blocking checks that can be evaluated before a queued
/// job is handed to a page or engine. The coordinator never downloads tools or
/// models; callers provide the already-known local capability facts.
/// </summary>
public sealed record AppJobPreflightContext
{
    public string? ToolsDirectory { get; init; }
    public long? EstimatedOutputBytes { get; init; }
    public bool? CapabilityAvailable { get; init; }
    public string? CapabilityMessage { get; init; }
    public bool RequireOutputPath { get; init; } = true;
}

public sealed record AppJobPreflightResult(
    IReadOnlyList<string> Blockers,
    IReadOnlyList<string> Warnings)
{
    public bool IsReady => Blockers.Count == 0;
}

/// <summary>
/// Read-only projection consumed by the Job Center. It intentionally retains
/// the original persisted job so a workflow page can restore its exact args.
/// </summary>
public sealed record AppJobCenterItem(
    AppJobHandle Handle,
    string PageName,
    PersistedBatchJob Job)
{
    public string Key => Handle.Key;
    public string FileName => string.IsNullOrWhiteSpace(Job.SourcePath)
        ? "Untitled job"
        : Path.GetFileName(Job.SourcePath);
    public string DisplaySource => string.IsNullOrWhiteSpace(Job.SourcePath)
        ? "No source path"
        : Job.SourcePath;
    public string DisplayWorkflow => string.IsNullOrWhiteSpace(PageName) ? "Workflow" : PageName;
    public string DisplayStatus => string.IsNullOrWhiteSpace(Job.Status) ? "Unknown" : Job.Status;
    public string DisplayStatusLine => $"{DisplayWorkflow} · {DisplayStatus}";
    public string DisplayError => Job.ErrorMessage ?? "";
    public string DisplayOutput => string.IsNullOrWhiteSpace(Job.OutputPath)
        ? "Output path will be selected when the job starts."
        : Job.OutputPath;
    public bool CanCancel => Job.Status.Equals("Queued", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Running", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Converting", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Cancelling", StringComparison.OrdinalIgnoreCase);
    public bool CanRetry => Job.Status.Equals("Failed", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Cancelled", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Interrupted", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Skipped", StringComparison.OrdinalIgnoreCase);
    public bool CanSkip => Job.Status.Equals("Queued", StringComparison.OrdinalIgnoreCase)
        || Job.Status.Equals("Interrupted", StringComparison.OrdinalIgnoreCase);
}

public interface IAppJobCoordinator
{
    event EventHandler? JobsChanged;

    IReadOnlyList<AppJobCenterItem> GetJobs(string? search = null);
    void RecoverInterruptedJobs();
    void RegisterCancellation(AppJobHandle handle, Action cancel);
    void UnregisterCancellation(AppJobHandle handle);
    void NotifyJobsChanged();
    bool Cancel(AppJobHandle handle);
    bool Retry(AppJobHandle handle);
    bool Skip(AppJobHandle handle);
    bool UpdateStatus(AppJobHandle handle, string status, string? errorMessage = null);
    AppJobPreflightResult Preflight(
        PersistedBatchJob job,
        AppJobPreflightContext? context = null);
}

/// <summary>
/// App-scoped ownership layer over the existing durable queue store. Pages may
/// still render their specialized queue controls, but cancellation, restart
/// recovery, retry, skip, and preflight state have one source of truth.
/// </summary>
public sealed class AppJobCoordinator : IAppJobCoordinator
{
    private readonly IBatchQueueStore _store;
    private readonly object _gate = new();
    private readonly Dictionary<string, Action> _cancellationActions = new(StringComparer.Ordinal);

    public AppJobCoordinator(IBatchQueueStore store)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        RecoverInterruptedJobs();
    }

    public event EventHandler? JobsChanged;

    public IReadOnlyList<AppJobCenterItem> GetJobs(string? search = null)
    {
        var jobs = _store.LoadAll()
            .SelectMany(queue => queue.Jobs.Select(job => new AppJobCenterItem(
                new AppJobHandle(queue.QueueKey, job.Id),
                queue.PageName,
                job)))
            .Where(item => BatchQueueOperations.Matches(item.Job, search))
            .OrderByDescending(item => StatusRank(item.Job.Status))
            .ThenByDescending(item => item.Job.Id, StringComparer.Ordinal)
            .ToList();
        return jobs;
    }

    public void RecoverInterruptedJobs()
    {
        var changed = false;
        foreach (var queue in _store.LoadAll())
        {
            var queueChanged = false;
            var jobs = queue.Jobs
                .Select(job =>
                {
                    if (!IsInFlight(job.Status))
                        return job;

                    queueChanged = true;
                    changed = true;
                    return job with
                    {
                        Status = "Interrupted",
                        ErrorMessage = "The application exited before this job finished; it is ready to retry.",
                    };
                })
                .ToList();

            if (queueChanged)
                _store.Save(queue with { Jobs = jobs });
        }

        if (changed)
            RaiseJobsChanged();
    }

    public void RegisterCancellation(AppJobHandle handle, Action cancel)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(handle.QueueKey);
        ArgumentException.ThrowIfNullOrWhiteSpace(handle.JobId);
        ArgumentNullException.ThrowIfNull(cancel);
        lock (_gate)
            _cancellationActions[handle.Key] = cancel;
    }

    public void UnregisterCancellation(AppJobHandle handle)
    {
        lock (_gate)
            _cancellationActions.Remove(handle.Key);
    }

    public void NotifyJobsChanged() => RaiseJobsChanged();

    public bool Cancel(AppJobHandle handle)
    {
        var item = Find(handle);
        if (item is null || !item.CanCancel)
            return false;

        Action? cancel;
        lock (_gate)
            _cancellationActions.TryGetValue(handle.Key, out cancel);

        if (cancel is not null)
        {
            try { cancel(); }
            catch { return false; }
            UpdateStatus(handle, "Cancelling", "Cancellation requested.");
            return true;
        }

        // A queued job has no child process to stop. Mark it cancelled so a
        // restart cannot silently start it; in-flight jobs require their page
        // to register a real cancellation action.
        return item.Job.Status.Equals("Queued", StringComparison.OrdinalIgnoreCase)
            && UpdateStatus(handle, "Cancelled", "Cancelled before execution.");
    }

    public bool Retry(AppJobHandle handle)
    {
        var item = Find(handle);
        if (item is null || !item.CanRetry)
            return false;

        lock (_gate)
            _cancellationActions.Remove(handle.Key);
        return UpdateStatus(handle, "Queued");
    }

    public bool Skip(AppJobHandle handle)
    {
        var item = Find(handle);
        if (item is null || !item.CanSkip)
            return false;

        lock (_gate)
            _cancellationActions.Remove(handle.Key);
        return UpdateStatus(handle, "Skipped", "Skipped from the Job Center.");
    }

    public bool UpdateStatus(AppJobHandle handle, string status, string? errorMessage = null)
    {
        if (string.IsNullOrWhiteSpace(status))
            return false;

        var queue = _store.Load(handle.QueueKey);
        if (queue is null)
            return false;

        var index = queue.Jobs.FindIndex(job => job.Id.Equals(handle.JobId, StringComparison.Ordinal));
        if (index < 0)
            return false;

        var current = queue.Jobs[index];
        var updated = current with
        {
            Status = status.Trim(),
            ErrorMessage = errorMessage,
        };
        if (updated == current)
            return true;

        var jobs = queue.Jobs.ToList();
        jobs[index] = updated;
        _store.Save(queue with { Jobs = jobs });
        RaiseJobsChanged();
        return true;
    }

    public AppJobPreflightResult Preflight(
        PersistedBatchJob job,
        AppJobPreflightContext? context = null)
    {
        ArgumentNullException.ThrowIfNull(job);
        context ??= new AppJobPreflightContext();

        var blockers = new List<string>();
        var warnings = new List<string>();

        if (string.IsNullOrWhiteSpace(job.SourcePath))
            blockers.Add("The source path is missing.");
        else if (!File.Exists(job.SourcePath))
            blockers.Add($"The source file is missing: {job.SourcePath}");

        if (string.IsNullOrWhiteSpace(job.Engine))
            blockers.Add("No engine is recorded for this job.");

        if (context.RequireOutputPath && string.IsNullOrWhiteSpace(job.OutputPath))
            blockers.Add("The output path is missing.");

        if (!string.IsNullOrWhiteSpace(job.OutputPath))
        {
            try
            {
                var outputPath = Path.GetFullPath(job.OutputPath);
                var outputDirectory = Path.GetDirectoryName(outputPath);
                if (string.IsNullOrWhiteSpace(outputDirectory))
                    blockers.Add("The output directory is invalid.");
                else if (!Directory.Exists(outputDirectory))
                    warnings.Add("The output directory will be created when the job starts.");
                else if (File.Exists(outputPath))
                    warnings.Add("The output file already exists and needs an overwrite decision.");

                if (context.EstimatedOutputBytes is > 0
                    && outputDirectory is not null
                    && Directory.Exists(outputDirectory))
                {
                    var root = Path.GetPathRoot(outputDirectory);
                    if (!string.IsNullOrWhiteSpace(root))
                    {
                        var freeBytes = new DriveInfo(root).AvailableFreeSpace;
                        if (freeBytes < context.EstimatedOutputBytes.Value)
                        {
                            blockers.Add(
                                $"The destination has {freeBytes:N0} bytes free, below the estimated {context.EstimatedOutputBytes.Value:N0} bytes required.");
                        }
                    }
                }
            }
            catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException)
            {
                blockers.Add($"The output path is not usable: {ex.Message}");
            }
        }

        if (!string.IsNullOrWhiteSpace(context.ToolsDirectory)
            && !Directory.Exists(context.ToolsDirectory))
        {
            warnings.Add($"The configured tools directory is not present: {context.ToolsDirectory}");
        }

        if (context.CapabilityAvailable == false)
            blockers.Add(context.CapabilityMessage ?? "A required local capability is unavailable.");
        else if (context.CapabilityAvailable is null)
            warnings.Add("Engine capability has not been probed yet.");

        return new AppJobPreflightResult(blockers, warnings);
    }

    private AppJobCenterItem? Find(AppJobHandle handle) =>
        GetJobs().FirstOrDefault(item => item.Handle.Equals(handle));

    private static bool IsInFlight(string? status) =>
        status is not null
        && (status.Equals("Running", StringComparison.OrdinalIgnoreCase)
            || status.Equals("Converting", StringComparison.OrdinalIgnoreCase)
            || status.Equals("Cancelling", StringComparison.OrdinalIgnoreCase));

    private static int StatusRank(string? status) => status?.ToLowerInvariant() switch
    {
        "running" or "converting" or "cancelling" => 5,
        "queued" => 4,
        "interrupted" => 3,
        "failed" or "cancelled" => 2,
        "skipped" => 1,
        "completed" or "done" => 0,
        _ => 1,
    };

    private void RaiseJobsChanged() => JobsChanged?.Invoke(this, EventArgs.Empty);
}
