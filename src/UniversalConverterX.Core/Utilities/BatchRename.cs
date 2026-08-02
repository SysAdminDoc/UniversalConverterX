using System.Text.Json;
using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Utilities;

/// <summary>One requested rename, as the user sees it.</summary>
public sealed record RenameRequest(string SourcePath, string TargetName);

/// <summary>
/// One filesystem move in the executable plan. <paramref name="IsTemporary"/>
/// marks the staging half of a cycle-breaking pair, which exists only so a swap
/// can complete and is never a destination the user asked for.
/// </summary>
public sealed record RenameStep(string From, string To, bool IsTemporary = false);

/// <summary>Why a plan could not be built.</summary>
public sealed record RenamePlanProblem(string SourcePath, string Reason);

/// <summary>
/// An ordered, collision-free plan, or the reasons one could not be produced.
/// </summary>
public sealed record BatchRenamePlan(
    IReadOnlyList<RenameStep> Steps,
    IReadOnlyList<RenamePlanProblem> Problems)
{
    public bool IsExecutable => Problems.Count == 0 && Steps.Count > 0;
}

/// <summary>
/// Builds a rename plan that survives swaps and cycles.
///
/// The page previously performed sequential <c>File.Move</c> calls behind a
/// comment claiming a two-pass algorithm. Renaming A→B while B→A therefore
/// failed on the first move, and any failure part-way through left the set
/// half-renamed with nothing to undo it.
/// </summary>
public static class BatchRenamePlanner
{
    private static readonly StringComparer PathComparer = OperatingSystem.IsWindows()
        ? StringComparer.OrdinalIgnoreCase
        : StringComparer.Ordinal;

    public static BatchRenamePlan Plan(IEnumerable<RenameRequest> requests)
    {
        ArgumentNullException.ThrowIfNull(requests);

        var problems = new List<RenamePlanProblem>();
        var pending = new Dictionary<string, string>(PathComparer);
        var sources = new HashSet<string>(PathComparer);
        var targets = new Dictionary<string, string>(PathComparer);

        foreach (var request in requests)
        {
            if (string.IsNullOrWhiteSpace(request.SourcePath))
            {
                problems.Add(new RenamePlanProblem(request.SourcePath ?? "", "The source path is empty."));
                continue;
            }

            string source;
            string directory;
            try
            {
                source = Path.GetFullPath(request.SourcePath);
                directory = Path.GetDirectoryName(source) ?? "";
            }
            catch (Exception exception) when (
                exception is ArgumentException or PathTooLongException or NotSupportedException)
            {
                problems.Add(new RenamePlanProblem(request.SourcePath, exception.Message));
                continue;
            }

            var name = request.TargetName;
            if (string.IsNullOrWhiteSpace(name))
            {
                problems.Add(new RenamePlanProblem(source, "The new name is empty."));
                continue;
            }
            if (name.IndexOfAny([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar]) >= 0
                || Path.IsPathRooted(name))
            {
                problems.Add(new RenamePlanProblem(
                    source, "A new name may not contain a path separator."));
                continue;
            }
            if (name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            {
                problems.Add(new RenamePlanProblem(source, "The new name contains invalid characters."));
                continue;
            }

            var target = Path.Combine(directory, name);
            if (PathComparer.Equals(source, target))
            {
                continue;
            }
            if (!sources.Add(source))
            {
                problems.Add(new RenamePlanProblem(source, "The same file is listed twice."));
                continue;
            }
            if (targets.TryGetValue(target, out var other))
            {
                problems.Add(new RenamePlanProblem(
                    source,
                    $"Two files would be renamed to the same name as {Path.GetFileName(other)}."));
                continue;
            }

            targets.Add(target, source);
            pending.Add(source, target);
        }

        // A target that already exists and is not itself being renamed away
        // would silently overwrite an untouched file.
        foreach (var (source, target) in pending)
        {
            if (File.Exists(target) && !pending.ContainsKey(target))
            {
                problems.Add(new RenamePlanProblem(
                    source, $"{Path.GetFileName(target)} already exists."));
            }
        }

        if (problems.Count > 0)
        {
            return new BatchRenamePlan([], problems);
        }

        return new BatchRenamePlan(Order(pending), []);
    }

    private static List<RenameStep> Order(Dictionary<string, string> pending)
    {
        var steps = new List<RenameStep>();
        // Paths currently holding a file that something else may want.
        var occupied = new HashSet<string>(pending.Keys, PathComparer);
        var remaining = new Dictionary<string, string>(pending, PathComparer);

        while (remaining.Count > 0)
        {
            var movedThisPass = new List<string>();
            foreach (var (from, to) in remaining)
            {
                if (occupied.Contains(to))
                {
                    continue;
                }

                steps.Add(new RenameStep(from, to));
                occupied.Remove(from);
                occupied.Add(to);
                movedThisPass.Add(from);
            }

            foreach (var from in movedThisPass)
            {
                remaining.Remove(from);
            }

            if (movedThisPass.Count > 0 || remaining.Count == 0)
            {
                continue;
            }

            // Everything left is in a cycle (the simplest being a two-file
            // swap). Park one member under a temporary name so the cycle opens,
            // then let the normal passes drain it.
            var (cycleFrom, cycleTo) = remaining.First();
            var staging = TemporaryPathFor(cycleFrom, occupied);
            steps.Add(new RenameStep(cycleFrom, staging, IsTemporary: true));
            occupied.Remove(cycleFrom);
            occupied.Add(staging);
            remaining.Remove(cycleFrom);
            remaining.Add(staging, cycleTo);
        }

        return steps;
    }

    private static string TemporaryPathFor(string source, HashSet<string> occupied)
    {
        var directory = Path.GetDirectoryName(source) ?? "";
        for (var attempt = 0; ; attempt++)
        {
            var candidate = Path.Combine(
                directory,
                $".ucx-rename-{Guid.NewGuid():N}{(attempt == 0 ? "" : attempt.ToString())}.tmp");
            if (!occupied.Contains(candidate) && !File.Exists(candidate))
            {
                return candidate;
            }
        }
    }
}

/// <summary>Outcome of executing a plan.</summary>
public sealed record BatchRenameResult(
    bool Succeeded,
    int RenamedCount,
    string? FailedFrom,
    string? Error,
    bool RolledBack,
    string? JournalPath);

/// <summary>
/// Durable record of the moves a run has already performed, so a failure or a
/// crash can be undone rather than left half-applied.
/// </summary>
public sealed class BatchRenameJournal
{
    public const int CurrentSchemaVersion = 1;

    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; set; } = CurrentSchemaVersion;

    public DateTime StartedUtc { get; set; } = DateTime.UtcNow;

    public bool Completed { get; set; }

    /// <summary>Moves already applied, in the order they happened.</summary>
    public List<RenameStep> Applied { get; set; } = [];

    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };

    public void Save(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        // Temp-then-replace: a journal truncated by a crash mid-write would be
        // worse than no journal, because recovery would trust it.
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(this, Options));
        File.Move(temporary, path, overwrite: true);
    }

    public static BatchRenameJournal? Load(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return null;
            }
            var journal = JsonSerializer.Deserialize<BatchRenameJournal>(
                File.ReadAllText(path), Options);
            return journal?.SchemaVersion == CurrentSchemaVersion ? journal : null;
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }
}

/// <summary>
/// Applies a <see cref="BatchRenamePlan"/> as a transaction: either every file
/// ends up with its new name, or none of them do.
/// </summary>
public static class BatchRenameExecutor
{
    /// <summary>
    /// Executes the plan, journalling each completed move. A failure rolls the
    /// whole set back before returning.
    /// </summary>
    public static BatchRenameResult Execute(BatchRenamePlan plan, string? journalPath = null)
    {
        ArgumentNullException.ThrowIfNull(plan);
        if (!plan.IsExecutable)
        {
            return new BatchRenameResult(
                false, 0, null,
                plan.Problems.Count > 0 ? plan.Problems[0].Reason : "Nothing to rename.",
                false, null);
        }

        var journal = new BatchRenameJournal();
        foreach (var step in plan.Steps)
        {
            try
            {
                File.Move(step.From, step.To);
                journal.Applied.Add(step);
                if (journalPath is not null)
                {
                    journal.Save(journalPath);
                }
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException or ArgumentException)
            {
                var rolledBack = Rollback(journal);
                if (journalPath is not null)
                {
                    TryDelete(journalPath);
                }

                return new BatchRenameResult(
                    Succeeded: false,
                    RenamedCount: 0,
                    FailedFrom: step.From,
                    Error: exception.Message,
                    RolledBack: rolledBack,
                    JournalPath: null);
            }
        }

        journal.Completed = true;
        if (journalPath is not null)
        {
            journal.Save(journalPath);
        }

        return new BatchRenameResult(
            Succeeded: true,
            // Staging moves are bookkeeping, not results the user asked for.
            RenamedCount: plan.Steps.Count(step => !step.IsTemporary),
            FailedFrom: null,
            Error: null,
            RolledBack: false,
            JournalPath: journalPath);
    }

    /// <summary>
    /// Reverses a completed or interrupted run. Used both for the one-click
    /// undo and for recovering a journal left behind by a crash.
    /// </summary>
    public static bool Undo(BatchRenameJournal journal)
    {
        ArgumentNullException.ThrowIfNull(journal);
        return Rollback(journal);
    }

    private static bool Rollback(BatchRenameJournal journal)
    {
        var complete = true;
        // Reverse order, so a cycle unwinds through the same staging path it
        // was opened with.
        for (var index = journal.Applied.Count - 1; index >= 0; index--)
        {
            var step = journal.Applied[index];
            try
            {
                if (File.Exists(step.To) && !File.Exists(step.From))
                {
                    File.Move(step.To, step.From);
                }
                else if (!File.Exists(step.To))
                {
                    // Already reverted, or the file moved out from under us.
                    continue;
                }
                else
                {
                    complete = false;
                }
            }
            catch (Exception exception) when (
                exception is IOException or UnauthorizedAccessException or ArgumentException)
            {
                complete = false;
            }
        }

        journal.Applied.Clear();
        return complete;
    }

    private static void TryDelete(string path)
    {
        try { File.Delete(path); }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException) { }
    }
}
