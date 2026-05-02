namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// How the estimate was computed — drives whether the UI prefixes a
/// <c>~</c> tilde or shows an exact size, and whether to widen the
/// uncertainty band.
/// </summary>
public enum OutputSizeEstimateKind
{
    /// <summary>Stream-copy / lossless-copy job; output ≈ input size + small overhead.</summary>
    LosslessCopy,
    /// <summary>Constant bitrate encode; estimate is bitrate × duration + container overhead.</summary>
    ConstantBitrate,
    /// <summary>Variable bitrate encode; estimate is approximate to within roughly ±25%.</summary>
    VariableBitrate,
    /// <summary>Insufficient inputs — estimate is unavailable.</summary>
    Unavailable,
}

/// <summary>
/// Result of a pre-encode size estimate (ROADMAP Item 68). Bytes is
/// non-null whenever <see cref="Kind"/> is not <c>Unavailable</c>.
/// </summary>
public sealed record OutputSizeEstimate(
    OutputSizeEstimateKind Kind,
    long? Bytes,
    string DisplayLabel,
    string? Caveat = null);

/// <summary>
/// Pre-encode output-size estimator. Mirrors LosslessCut's per-segment
/// estimate UX (#2630) — exact for lossless copy, approximate for VBR
/// transcodes — without bringing in any new sidecar dependency.
/// Container overhead heuristic: 1% of the audio+video payload, with a
/// 32 KiB floor for very short clips.
/// </summary>
public static class OutputSizeEstimator
{
    private const long ContainerOverheadFloorBytes = 32 * 1024;

    /// <summary>
    /// Lossless / stream-copy estimate. The output is ≈ input size with a
    /// small container-rewrap overhead delta added.
    /// </summary>
    public static OutputSizeEstimate ForLosslessCopy(long inputBytes)
    {
        if (inputBytes <= 0)
            return new OutputSizeEstimate(OutputSizeEstimateKind.Unavailable,
                null, "—",
                "Source size unknown — open the file picker once so the queue can probe it.");

        var overhead = Math.Max((long)(inputBytes * 0.005), ContainerOverheadFloorBytes);
        var total = inputBytes + overhead;
        return new OutputSizeEstimate(OutputSizeEstimateKind.LosslessCopy,
            total, FormatBytes(total),
            "Lossless copy — actual output will land within a few KiB of this.");
    }

    /// <summary>
    /// CBR-style estimate: <c>(videoBitrate + audioBitrate) × duration / 8</c>
    /// plus container overhead. Bitrates passed in bits-per-second.
    /// </summary>
    public static OutputSizeEstimate ForConstantBitrate(
        long videoBitsPerSecond, long audioBitsPerSecond, double durationSeconds)
    {
        if (durationSeconds <= 0 || videoBitsPerSecond < 0 || audioBitsPerSecond < 0)
            return new OutputSizeEstimate(OutputSizeEstimateKind.Unavailable,
                null, "—",
                "Need a positive duration and bitrate to estimate output size.");

        var bitsPerSecond = videoBitsPerSecond + audioBitsPerSecond;
        if (bitsPerSecond <= 0)
            return new OutputSizeEstimate(OutputSizeEstimateKind.Unavailable,
                null, "—",
                "No bitrate information available — estimate skipped.");

        var payload = (long)Math.Round(bitsPerSecond * durationSeconds / 8.0);
        var overhead = Math.Max((long)(payload * 0.01), ContainerOverheadFloorBytes);
        var total = payload + overhead;
        return new OutputSizeEstimate(OutputSizeEstimateKind.ConstantBitrate,
            total, FormatBytes(total),
            "CBR target — actual output should match within ~5%.");
    }

    /// <summary>
    /// VBR-style estimate. Uses <paramref name="targetAverageBitsPerSecond"/>
    /// when supplied (preferred), or <c>quality × referenceBitsPerSecond</c>
    /// when only a quality knob is available. Output is prefixed with
    /// <c>~</c> in <see cref="OutputSizeEstimate.DisplayLabel"/> and tagged
    /// with a ±25% caveat.
    /// </summary>
    public static OutputSizeEstimate ForVariableBitrate(
        long? targetAverageBitsPerSecond,
        long audioBitsPerSecond,
        double durationSeconds,
        double? sceneComplexityFactor = null)
    {
        if (durationSeconds <= 0)
            return new OutputSizeEstimate(OutputSizeEstimateKind.Unavailable,
                null, "—",
                "Source duration unknown — estimate skipped.");

        if (targetAverageBitsPerSecond is null or <= 0)
            return new OutputSizeEstimate(OutputSizeEstimateKind.Unavailable,
                null, "—",
                "No target bitrate set — VBR estimate not available until the encoder is configured.");

        var multiplier = sceneComplexityFactor.HasValue
            ? Math.Clamp(sceneComplexityFactor.Value, 0.5, 1.8)
            : 1.0;
        var videoBits = (long)Math.Round(targetAverageBitsPerSecond.Value * multiplier);
        var bitsPerSecond = Math.Max(0, videoBits) + Math.Max(0, audioBitsPerSecond);
        var payload = (long)Math.Round(bitsPerSecond * durationSeconds / 8.0);
        var overhead = Math.Max((long)(payload * 0.01), ContainerOverheadFloorBytes);
        var total = payload + overhead;
        return new OutputSizeEstimate(OutputSizeEstimateKind.VariableBitrate,
            total, "~" + FormatBytes(total),
            "VBR estimate — actual output typically lands within ±25% depending on scene complexity.");
    }

    /// <summary>
    /// Default-target convenience: callers without bitrate information see
    /// a clearly-marked "unavailable" result rather than a null reference.
    /// </summary>
    public static OutputSizeEstimate Unavailable(string? reason = null) =>
        new(OutputSizeEstimateKind.Unavailable, null, "—",
            reason ?? "Insufficient information to estimate output size.");

    /// <summary>
    /// Format bytes with two decimals, escalating B → KiB → MiB → GiB → TiB.
    /// Mirrors the Windows shell convention (binary prefixes).
    /// </summary>
    public static string FormatBytes(long bytes)
    {
        if (bytes < 1024) return $"{bytes} B";
        double v = bytes;
        string[] units = ["KiB", "MiB", "GiB", "TiB", "PiB"];
        int u = 0;
        v /= 1024.0;
        while (v >= 1024.0 && u < units.Length - 1)
        {
            v /= 1024.0;
            u++;
        }
        return v >= 100 ? $"{v:0} {units[u]}" : $"{v:0.0} {units[u]}";
    }
}
