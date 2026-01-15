namespace UniversalConverterX.Core.Models;

/// <summary>
/// Progress information for an ongoing conversion
/// </summary>
public class ConversionProgress
{
    /// <summary>
    /// Percentage complete (0-100)
    /// </summary>
    public double Percent { get; init; }

    /// <summary>
    /// Current frame being processed (video)
    /// </summary>
    public long? CurrentFrame { get; init; }

    /// <summary>
    /// Total frames to process (video)
    /// </summary>
    public long? TotalFrames { get; init; }

    /// <summary>
    /// Current time position (video/audio)
    /// </summary>
    public TimeSpan? CurrentTime { get; init; }

    /// <summary>
    /// Total duration (video/audio)
    /// </summary>
    public TimeSpan? TotalDuration { get; init; }

    /// <summary>
    /// Processing speed (e.g., "2.5x" for 2.5x realtime)
    /// </summary>
    public double? Speed { get; init; }

    /// <summary>
    /// Processing speed in FPS
    /// </summary>
    public double? Fps { get; init; }

    /// <summary>
    /// Current bitrate
    /// </summary>
    public string? Bitrate { get; init; }

    /// <summary>
    /// Output file size so far
    /// </summary>
    public long? OutputSize { get; init; }

    /// <summary>
    /// Estimated time remaining
    /// </summary>
    public TimeSpan? EstimatedTimeRemaining { get; init; }

    /// <summary>
    /// Raw output line from the converter
    /// </summary>
    public string? RawOutput { get; init; }

    /// <summary>
    /// Current stage of processing
    /// </summary>
    public ConversionStage Stage { get; init; } = ConversionStage.Converting;

    /// <summary>
    /// Additional status message
    /// </summary>
    public string? StatusMessage { get; init; }

    /// <summary>
    /// Bytes processed so far
    /// </summary>
    public long? BytesProcessed { get; init; }

    /// <summary>
    /// Total bytes to process
    /// </summary>
    public long? TotalBytes { get; init; }

    /// <summary>
    /// Create progress from percentage
    /// </summary>
    public static ConversionProgress FromPercent(double percent, string? message = null)
    {
        return new ConversionProgress
        {
            Percent = Math.Clamp(percent, 0, 100),
            StatusMessage = message
        };
    }

    /// <summary>
    /// Create progress from frame count
    /// </summary>
    public static ConversionProgress FromFrames(long current, long total, double? fps = null, double? speed = null)
    {
        var percent = total > 0 ? (double)current / total * 100 : 0;
        TimeSpan? eta = null;
        
        if (fps.HasValue && fps.Value > 0 && total > current)
        {
            var framesRemaining = total - current;
            eta = TimeSpan.FromSeconds(framesRemaining / fps.Value);
        }

        return new ConversionProgress
        {
            Percent = percent,
            CurrentFrame = current,
            TotalFrames = total,
            Fps = fps,
            Speed = speed,
            EstimatedTimeRemaining = eta
        };
    }

    /// <summary>
    /// Create progress from time position
    /// </summary>
    public static ConversionProgress FromTime(TimeSpan current, TimeSpan total, double? speed = null)
    {
        var percent = total.TotalSeconds > 0 ? current.TotalSeconds / total.TotalSeconds * 100 : 0;
        TimeSpan? eta = null;

        if (speed.HasValue && speed.Value > 0)
        {
            var remaining = total - current;
            eta = TimeSpan.FromSeconds(remaining.TotalSeconds / speed.Value);
        }

        return new ConversionProgress
        {
            Percent = percent,
            CurrentTime = current,
            TotalDuration = total,
            Speed = speed,
            EstimatedTimeRemaining = eta
        };
    }

    /// <summary>
    /// Create indeterminate progress
    /// </summary>
    public static ConversionProgress Indeterminate(string message, ConversionStage stage = ConversionStage.Converting)
    {
        return new ConversionProgress
        {
            Percent = -1,
            StatusMessage = message,
            Stage = stage
        };
    }

    /// <summary>
    /// Check if progress is indeterminate
    /// </summary>
    public bool IsIndeterminate => Percent < 0;
}

/// <summary>
/// Stage of the conversion process
/// </summary>
public enum ConversionStage
{
    Initializing,
    Analyzing,
    Converting,
    Encoding,
    Finalizing,
    Verifying
}
