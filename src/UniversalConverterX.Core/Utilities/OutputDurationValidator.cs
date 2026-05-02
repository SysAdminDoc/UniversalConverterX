using System.Diagnostics;
using System.Text.Json;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Outcome of a post-encode duration check (ROADMAP Item 72). Targets the
/// HandBrake #7828 class of bug where an encode reports success but the
/// output video silently truncates relative to the source audio.
/// </summary>
public sealed record DurationValidationResult(
    bool IsValid,
    double InputSeconds,
    double OutputSeconds,
    double DeltaSeconds,
    string? Reason)
{
    /// <summary>Human-readable status tag for surfacing in History / toasts.</summary>
    public string StatusTag => IsValid ? "OK" : "PARTIAL / TRUNCATED";
}

/// <summary>
/// Probes input/output media durations via FFprobe and compares them. Pure
/// utility — caller decides where to source the FFprobe binary and how to
/// react to the result (toast, History flag, file-rename quarantine, …).
/// </summary>
public static class OutputDurationValidator
{
    private static readonly HashSet<string> _mediaExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mp4", ".mkv", ".mov", ".m4v", ".webm", ".avi", ".ts", ".m2ts", ".mts",
        ".mxf", ".vob", ".flv", ".3gp", ".3g2", ".ogv", ".wmv",
        ".mp3", ".aac", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".wma", ".aiff",
    };

    /// <summary>
    /// Quick predicate: does this path look like a duration-bearing media file
    /// the validator should probe? Used by callers to gate the probe.
    /// </summary>
    public static bool LooksLikeMedia(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        try
        {
            var ext = Path.GetExtension(path);
            return !string.IsNullOrEmpty(ext) && _mediaExtensions.Contains(ext);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Probe a single media file's duration in seconds via FFprobe. Returns
    /// <c>null</c> when the binary is missing, the file doesn't exist, or the
    /// probe didn't surface a duration field.
    /// </summary>
    public static async Task<double?> ProbeDurationSecondsAsync(
        string ffprobePath, string mediaPath, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(ffprobePath) || !File.Exists(ffprobePath)) return null;
        if (string.IsNullOrWhiteSpace(mediaPath) || !File.Exists(mediaPath)) return null;

        var psi = new ProcessStartInfo
        {
            FileName = ffprobePath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.ArgumentList.Add("-v");
        psi.ArgumentList.Add("quiet");
        psi.ArgumentList.Add("-print_format");
        psi.ArgumentList.Add("json");
        psi.ArgumentList.Add("-show_format");
        psi.ArgumentList.Add(mediaPath);

        try
        {
            using var proc = Process.Start(psi);
            if (proc is null) return null;
            var stdoutTask = proc.StandardOutput.ReadToEndAsync(ct);
            var stderrTask = proc.StandardError.ReadToEndAsync(ct);
            await proc.WaitForExitAsync(ct).ConfigureAwait(false);
            if (proc.ExitCode != 0) return null;
            var json = await stdoutTask.ConfigureAwait(false);
            _ = await stderrTask.ConfigureAwait(false);
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("format", out var format)) return null;
            if (!format.TryGetProperty("duration", out var dur)) return null;
            var raw = dur.ValueKind == JsonValueKind.String ? dur.GetString() : dur.ToString();
            if (string.IsNullOrWhiteSpace(raw)) return null;
            return double.TryParse(raw,
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out var seconds) ? seconds : null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Probe both files, compute the delta, and decide whether the encode
    /// should be flagged as truncated. The threshold is the smaller of
    /// <paramref name="minDeltaSeconds"/> (default 2) and 1 % of the input
    /// duration. Probe failures yield <see cref="DurationValidationResult"/>
    /// with <c>IsValid=true</c> and a Reason explaining why no comparison
    /// happened — i.e. the validator never falsely flags a job when the
    /// data isn't there.
    /// </summary>
    public static async Task<DurationValidationResult> ValidateAsync(
        string ffprobePath,
        string inputPath,
        string outputPath,
        double minDeltaSeconds = 2.0,
        CancellationToken ct = default)
    {
        var input = await ProbeDurationSecondsAsync(ffprobePath, inputPath, ct).ConfigureAwait(false);
        var output = await ProbeDurationSecondsAsync(ffprobePath, outputPath, ct).ConfigureAwait(false);
        if (input is null || output is null)
        {
            return new DurationValidationResult(
                IsValid: true,
                InputSeconds: input ?? 0.0,
                OutputSeconds: output ?? 0.0,
                DeltaSeconds: 0.0,
                Reason: input is null
                    ? "input duration probe failed (skipping validation)"
                    : "output duration probe failed (skipping validation)");
        }

        var delta = Math.Abs(input.Value - output.Value);
        var threshold = Math.Min(Math.Max(minDeltaSeconds, 0.0), Math.Max(input.Value * 0.01, 0.0));
        if (threshold <= 0) threshold = minDeltaSeconds;

        var truncated = delta > threshold;
        return new DurationValidationResult(
            IsValid: !truncated,
            InputSeconds: input.Value,
            OutputSeconds: output.Value,
            DeltaSeconds: delta,
            Reason: truncated
                ? $"output {output.Value:F2}s vs. input {input.Value:F2}s (Δ {delta:F2}s > {threshold:F2}s threshold)"
                : null);
    }
}
