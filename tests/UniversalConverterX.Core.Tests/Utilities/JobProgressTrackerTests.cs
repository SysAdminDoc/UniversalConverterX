using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

/// <summary>
/// Progress normalization (ROADMAP Item 154). The runner used to forward an
/// engine's reported number verbatim to ~49 handlers, five of which clamped.
/// </summary>
public sealed class JobProgressTrackerTests
{
    [Fact]
    public void PercentIsClampedIntoRange()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(250, "encoding", null).Percent.Should().Be(100);

        var falling = new JobProgressTracker();
        falling.Report(-40, "encoding", null).Percent.Should().Be(0);
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void NonFiniteReadingsAreIgnoredRatherThanDisplayed(double raw)
    {
        var tracker = new JobProgressTracker();
        tracker.Report(42, "encoding", null);

        tracker.Report(raw, "encoding", null).Percent.Should().Be(42);
    }

    [Fact]
    public void ProgressNeverWalksBackwards()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(60, "pass 1", null);

        // A two-pass encoder restarting its counter reads as a stall to a user.
        tracker.Report(5, "pass 2", null).Percent.Should().Be(60);
        tracker.Report(75, "pass 2", null).Percent.Should().Be(75);
    }

    [Fact]
    public void StageIsRetainedWhenAReportOmitsIt()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(10, "extracting frames", null);
        tracker.Report(20, null, null).Stage.Should().Be("extracting frames");
        tracker.Report(30, "   ", null).Stage.Should().Be("extracting frames");
    }

    [Fact]
    public void AStaleEtaExpiresInsteadOfCountingDownOnItsOwn()
    {
        var now = new DateTime(2026, 8, 2, 12, 0, 0, DateTimeKind.Utc);
        var tracker = new JobProgressTracker(
            etaFreshness: TimeSpan.FromSeconds(30),
            clock: () => now);

        tracker.Report(10, "encoding", 120).EtaSeconds.Should().Be(120);

        now = now.AddSeconds(20);
        tracker.Current.EtaSeconds.Should().Be(120, "the ETA is still fresh");

        now = now.AddSeconds(20);
        tracker.Current.EtaSeconds.Should().BeNull(
            "an ETA the engine stopped updating is worse than no ETA");
    }

    [Fact]
    public void ANegativeEtaIsIgnored()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(10, "encoding", 60);
        tracker.Report(20, "encoding", -1).EtaSeconds.Should().Be(60);
    }

    [Fact]
    public void VerifiedSuccessReachesOneHundredAndDropsTheEta()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(63, "encoding", 30);

        var final = tracker.Complete(succeeded: true);

        final.Percent.Should().Be(100);
        final.EtaSeconds.Should().BeNull();
    }

    [Fact]
    public void FailureLeavesTheBarWhereItStopped()
    {
        var tracker = new JobProgressTracker();
        tracker.Report(63, "encoding", 30);

        var final = tracker.Complete(succeeded: false);

        final.Percent.Should().Be(63,
            "claiming 100% for a job that produced nothing misleads the user");
        final.EtaSeconds.Should().BeNull();
    }

    [Fact]
    public void ReadingsAfterCompletionCannotMoveTheBar()
    {
        var tracker = new JobProgressTracker();
        tracker.Complete(succeeded: true);
        tracker.Report(12, "late event", 500).Percent.Should().Be(100);
    }

    [Theory]
    [InlineData(0, 0, 4, 0)]
    [InlineData(100, 0, 4, 25)]
    [InlineData(0, 2, 4, 50)]
    [InlineData(100, 3, 4, 100)]
    public void ScaleMapsAPerItemReadingIntoTheWholeRun(
        double itemPercent, int index, int count, double expected)
    {
        // A preset run over N files previously swept 0..100 once per file.
        JobProgressTracker.Scale(itemPercent, index, count).Should().Be(expected);
    }

    [Fact]
    public void ScaleToleratesAnEmptyOrOutOfRangeItemCount()
    {
        JobProgressTracker.Scale(50, 0, 0).Should().Be(50);
        JobProgressTracker.Scale(double.NaN, 1, 2).Should().Be(50);
        // An index past the end clamps to the last item, so a half-done final
        // item still reads as 75 of 100 rather than jumping the bar to full.
        JobProgressTracker.Scale(50, 99, 2).Should().Be(75);
    }
}
