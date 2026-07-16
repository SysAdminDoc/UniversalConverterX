using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class ConversionBatchOutcomeTests
{
    [Fact]
    public void CancellationRequest_IsVisibleEvenWhenNoTaskThrows()
    {
        var outcome = new ConversionBatchOutcome(
            Succeeded: 2,
            Failed: 0,
            Cancelled: 0,
            CancellationRequested: true);

        outcome.WasCancelled.Should().BeTrue();
        outcome.Title.Should().Be("Cancelled");
        outcome.Status.Should().Be("2 succeeded, 0 failed, 0 cancelled");
    }

    [Fact]
    public void CancelledResult_MarksBatchAsCancelled()
    {
        var outcome = new ConversionBatchOutcome(
            Succeeded: 1,
            Failed: 0,
            Cancelled: 3,
            CancellationRequested: false);

        outcome.WasCancelled.Should().BeTrue();
        outcome.Title.Should().Be("Cancelled");
        outcome.Status.Should().Contain("3 cancelled");
    }

    [Theory]
    [InlineData(3, 0, "Complete")]
    [InlineData(2, 1, "Completed with errors")]
    public void CompletedBatch_UsesSuccessOrErrorTitle(int succeeded, int failed, string title)
    {
        var outcome = new ConversionBatchOutcome(succeeded, failed, 0, false);

        outcome.WasCancelled.Should().BeFalse();
        outcome.Title.Should().Be(title);
    }
}
