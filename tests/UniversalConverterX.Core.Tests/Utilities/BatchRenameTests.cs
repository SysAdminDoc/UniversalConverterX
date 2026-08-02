using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

/// <summary>
/// Transactional, undoable batch rename (ROADMAP Item 159). The page performed
/// sequential moves behind a comment claiming a two-pass algorithm, so a swap
/// failed outright and a mid-run failure left the set half-renamed.
/// </summary>
public sealed class BatchRenameTests : IDisposable
{
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(), "ucx-rename-" + Guid.NewGuid().ToString("N"));

    public BatchRenameTests() => Directory.CreateDirectory(_directory);

    public void Dispose()
    {
        try { Directory.Delete(_directory, recursive: true); } catch { }
    }

    private string Write(string name, string content = "x")
    {
        var path = Path.Combine(_directory, name);
        File.WriteAllText(path, content);
        return path;
    }

    private string[] NamesOnDisk() =>
        [.. Directory.EnumerateFiles(_directory).Select(Path.GetFileName).Order()!];

    [Fact]
    public void ASimpleRenameProducesOneStep()
    {
        var source = Write("a.txt");
        var plan = BatchRenamePlanner.Plan([new RenameRequest(source, "b.txt")]);

        plan.IsExecutable.Should().BeTrue();
        plan.Steps.Should().ContainSingle();
        BatchRenameExecutor.Execute(plan).Succeeded.Should().BeTrue();
        NamesOnDisk().Should().Equal("b.txt");
    }

    [Fact]
    public void ASwapIsStagedThroughATemporaryNameAndCompletes()
    {
        var a = Write("a.txt", "content-a");
        var b = Write("b.txt", "content-b");

        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "b.txt"),
            new RenameRequest(b, "a.txt"),
        ]);

        plan.IsExecutable.Should().BeTrue();
        plan.Steps.Should().Contain(step => step.IsTemporary,
            "a two-file swap cannot complete without a staging move");

        var result = BatchRenameExecutor.Execute(plan);

        result.Succeeded.Should().BeTrue(result.Error);
        result.RenamedCount.Should().Be(2, "staging moves are bookkeeping, not results");
        NamesOnDisk().Should().Equal("a.txt", "b.txt");
        File.ReadAllText(Path.Combine(_directory, "a.txt")).Should().Be("content-b");
        File.ReadAllText(Path.Combine(_directory, "b.txt")).Should().Be("content-a");
    }

    [Fact]
    public void AThreeFileCycleCompletes()
    {
        var a = Write("a.txt", "1");
        var b = Write("b.txt", "2");
        var c = Write("c.txt", "3");

        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "b.txt"),
            new RenameRequest(b, "c.txt"),
            new RenameRequest(c, "a.txt"),
        ]);

        BatchRenameExecutor.Execute(plan).Succeeded.Should().BeTrue();

        NamesOnDisk().Should().Equal("a.txt", "b.txt", "c.txt");
        File.ReadAllText(Path.Combine(_directory, "b.txt")).Should().Be("1");
        File.ReadAllText(Path.Combine(_directory, "c.txt")).Should().Be("2");
        File.ReadAllText(Path.Combine(_directory, "a.txt")).Should().Be("3");
    }

    [Fact]
    public void AShiftChainRenamesInDependencyOrder()
    {
        var a = Write("1.txt", "one");
        var b = Write("2.txt", "two");

        // 2 -> 3 must happen before 1 -> 2, or the second move collides.
        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "2.txt"),
            new RenameRequest(b, "3.txt"),
        ]);

        plan.Steps.Should().NotContain(step => step.IsTemporary,
            "an open chain needs no staging, only ordering");
        BatchRenameExecutor.Execute(plan).Succeeded.Should().BeTrue();

        File.ReadAllText(Path.Combine(_directory, "2.txt")).Should().Be("one");
        File.ReadAllText(Path.Combine(_directory, "3.txt")).Should().Be("two");
    }

    [Fact]
    public void CollidingWithAnUntouchedExistingFileIsRefusedBeforeAnythingMoves()
    {
        var source = Write("a.txt", "source");
        Write("taken.txt", "bystander");

        var plan = BatchRenamePlanner.Plan([new RenameRequest(source, "taken.txt")]);

        plan.IsExecutable.Should().BeFalse();
        plan.Problems.Should().ContainSingle()
            .Which.Reason.Should().Contain("already exists");
        File.ReadAllText(Path.Combine(_directory, "taken.txt")).Should().Be("bystander");
    }

    [Fact]
    public void TwoFilesRenamedToTheSameNameIsRefused()
    {
        var a = Write("a.txt");
        var b = Write("b.txt");

        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "same.txt"),
            new RenameRequest(b, "same.txt"),
        ]);

        plan.IsExecutable.Should().BeFalse();
        plan.Problems.Should().ContainSingle()
            .Which.Reason.Should().Contain("same name");
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("sub/dir.txt")]
    [InlineData("sub\\dir.txt")]
    public void AnUnusableNewNameIsRefused(string newName)
    {
        var source = Write("a.txt");
        var plan = BatchRenamePlanner.Plan([new RenameRequest(source, newName)]);

        plan.IsExecutable.Should().BeFalse();
        plan.Problems.Should().NotBeEmpty();
    }

    [Fact]
    public void AnUnchangedNameIsNotAStep()
    {
        var source = Write("a.txt");
        BatchRenamePlanner.Plan([new RenameRequest(source, "a.txt")])
            .Steps.Should().BeEmpty();
    }

    [Fact]
    public void AFailurePartWayThroughRollsTheWholeSetBack()
    {
        var a = Write("a.txt", "one");
        var b = Write("b.txt", "two");
        var c = Write("c.txt", "three");

        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "a-new.txt"),
            new RenameRequest(b, "b-new.txt"),
            new RenameRequest(c, "c-new.txt"),
        ]);

        // Hold the third file open so its move fails after the first two have
        // already succeeded — the exact case that used to leave a mixed set.
        using (var handle = new FileStream(c, FileMode.Open, FileAccess.Read, FileShare.None))
        {
            var result = BatchRenameExecutor.Execute(plan);

            result.Succeeded.Should().BeFalse();
            result.RolledBack.Should().BeTrue(result.Error);
            result.FailedFrom.Should().Be(c);
        }

        NamesOnDisk().Should().Equal("a.txt", "b.txt", "c.txt");
        File.ReadAllText(Path.Combine(_directory, "a.txt")).Should().Be("one");
        File.ReadAllText(Path.Combine(_directory, "b.txt")).Should().Be("two");
    }

    [Fact]
    public void ACompletedRunCanBeUndoneInOneStep()
    {
        var a = Write("a.txt", "one");
        var b = Write("b.txt", "two");
        var journalPath = Path.Combine(_directory, "journal.json");

        var plan = BatchRenamePlanner.Plan([
            new RenameRequest(a, "b.txt"),
            new RenameRequest(b, "a.txt"),
        ]);
        BatchRenameExecutor.Execute(plan, journalPath).Succeeded.Should().BeTrue();
        File.ReadAllText(Path.Combine(_directory, "a.txt")).Should().Be("two");

        var journal = BatchRenameJournal.Load(journalPath);
        journal.Should().NotBeNull();
        journal!.Completed.Should().BeTrue();

        BatchRenameExecutor.Undo(journal).Should().BeTrue();

        File.ReadAllText(Path.Combine(_directory, "a.txt")).Should().Be("one");
        File.ReadAllText(Path.Combine(_directory, "b.txt")).Should().Be("two");
    }

    [Fact]
    public void TheJournalSurvivesForRestartRecovery()
    {
        var a = Write("a.txt", "one");
        var journalPath = Path.Combine(_directory, "journal.json");

        var plan = BatchRenamePlanner.Plan([new RenameRequest(a, "renamed.txt")]);
        BatchRenameExecutor.Execute(plan, journalPath);

        // Simulates the next launch finding a journal on disk.
        var recovered = BatchRenameJournal.Load(journalPath);

        recovered.Should().NotBeNull();
        recovered!.Applied.Should().ContainSingle();
        recovered.Applied[0].To.Should().EndWith("renamed.txt");

        BatchRenameExecutor.Undo(recovered).Should().BeTrue();
        NamesOnDisk().Should().Contain("a.txt");
    }

    [Fact]
    public void ACorruptOrForeignJournalIsIgnoredRatherThanReplayed()
    {
        var path = Path.Combine(_directory, "bad.json");
        File.WriteAllText(path, "{ not json");
        BatchRenameJournal.Load(path).Should().BeNull();

        File.WriteAllText(path, "{\"schemaVersion\":99,\"applied\":[]}");
        BatchRenameJournal.Load(path).Should().BeNull();

        BatchRenameJournal.Load(Path.Combine(_directory, "missing.json")).Should().BeNull();
    }

    [Fact]
    public void SourceTimestampsAreCarriedAcrossTheRename()
    {
        var source = Write("a.txt");
        var stamp = new DateTime(2024, 3, 4, 5, 6, 7, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(source, stamp);

        var plan = BatchRenamePlanner.Plan([new RenameRequest(source, "b.txt")]);
        BatchRenameExecutor.Execute(plan).Succeeded.Should().BeTrue();

        File.GetLastWriteTimeUtc(Path.Combine(_directory, "b.txt"))
            .Should().BeCloseTo(stamp, TimeSpan.FromSeconds(2),
                "a rename must not look like a modification to backup tooling");
    }
}
