namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Scales the observed sample output and render time to the full source
/// duration. A preview is an estimate, never a promise: unknown durations or
/// invalid measurements return null rather than inventing a number.
/// </summary>
public sealed record RepresentativePreviewEstimate(
    double SampleDurationSeconds,
    long SampleOutputBytes,
    double FullDurationSeconds,
    double RenderSeconds)
{
    public long? EstimatedOutputBytes => IsUsable
        ? (long)Math.Ceiling(SampleOutputBytes * (FullDurationSeconds / SampleDurationSeconds))
        : null;

    public double? EstimatedRenderSeconds => IsUsable && RenderSeconds >= 0
        ? RenderSeconds * (FullDurationSeconds / SampleDurationSeconds)
        : null;

    private bool IsUsable => SampleDurationSeconds > 0
                              && double.IsFinite(SampleDurationSeconds)
                              && FullDurationSeconds > 0
                              && double.IsFinite(FullDurationSeconds)
                              && SampleOutputBytes > 0;
}
