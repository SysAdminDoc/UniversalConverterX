namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Immutable final state for a parallel conversion batch.
/// </summary>
public readonly record struct ConversionBatchOutcome(
    int Succeeded,
    int Failed,
    int Cancelled,
    bool CancellationRequested)
{
    public bool WasCancelled => CancellationRequested || Cancelled > 0;

    public string Title => WasCancelled
        ? "Cancelled"
        : Failed == 0 ? "Complete" : "Completed with errors";

    public string Status => WasCancelled
        ? $"{Succeeded} succeeded, {Failed} failed, {Cancelled} cancelled"
        : $"{Succeeded} succeeded, {Failed} failed";
}
