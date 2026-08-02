namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// A normalized progress reading: a finite percentage in 0..100 and an ETA that
/// is only present when it is fresh enough to be believed.
/// </summary>
public readonly record struct NormalizedProgress(double Percent, string Stage, int? EtaSeconds);

/// <summary>
/// Turns whatever an engine writes into its <c>progress</c> event into a value
/// the UI can display without each page re-deriving the rules.
///
/// The runner previously forwarded the reported number verbatim, so a sidecar
/// could emit NaN, 0.87 meaning 87%, 250, or a percentage that walked backwards
/// as it re-planned, and every consuming page inherited it. Five pages clamped;
/// the rest did not. A stale ETA is worse than no ETA: it keeps counting down
/// long after the engine stopped updating it.
/// </summary>
public sealed class JobProgressTracker
{
    /// <summary>An ETA not refreshed within this window is dropped.</summary>
    public static readonly TimeSpan DefaultEtaFreshness = TimeSpan.FromSeconds(90);

    private readonly TimeSpan _etaFreshness;
    private readonly Func<DateTime> _clock;
    private readonly object _sync = new();

    private double _percent;
    private string _stage = string.Empty;
    private int? _eta;
    private DateTime _etaObservedUtc;
    private bool _completed;

    public JobProgressTracker(TimeSpan? etaFreshness = null, Func<DateTime>? clock = null)
    {
        _etaFreshness = etaFreshness ?? DefaultEtaFreshness;
        _clock = clock ?? (() => DateTime.UtcNow);
    }

    /// <summary>The most recent normalized reading.</summary>
    public NormalizedProgress Current
    {
        get
        {
            lock (_sync)
            {
                return new NormalizedProgress(_percent, _stage, CurrentEta());
            }
        }
    }

    /// <summary>
    /// Folds one raw reading in and returns the normalized result.
    /// </summary>
    /// <param name="rawPercent">
    /// The engine's number. Non-finite values are ignored; a value in 0..1 is
    /// treated as a percentage, not a fraction: an engine that reports 0.5 and
    /// later 87 means half a percent, and guessing otherwise makes the bar jump.
    /// </param>
    /// <param name="stage">Human-readable stage label; blank keeps the last one.</param>
    /// <param name="rawEtaSeconds">Engine ETA; negative or absent leaves it unchanged.</param>
    public NormalizedProgress Report(double rawPercent, string? stage, int? rawEtaSeconds)
    {
        lock (_sync)
        {
            if (!_completed && double.IsFinite(rawPercent))
            {
                var candidate = Math.Clamp(rawPercent, 0, 100);

                // Progress that walks backwards reads as a stall or a restart to
                // a user watching a bar. Hold the high-water mark instead.
                if (candidate > _percent)
                {
                    _percent = candidate;
                }
            }

            if (!string.IsNullOrWhiteSpace(stage))
            {
                _stage = stage;
            }

            if (rawEtaSeconds is int eta && eta >= 0)
            {
                _eta = eta;
                _etaObservedUtc = _clock();
            }

            return new NormalizedProgress(_percent, _stage, CurrentEta());
        }
    }

    /// <summary>
    /// Marks the job finished. A verified success pins the bar at 100 and drops
    /// the ETA; a failure leaves the bar where it stopped, because claiming 100%
    /// on a job that produced nothing is a lie.
    /// </summary>
    public NormalizedProgress Complete(bool succeeded, string? stage = null)
    {
        lock (_sync)
        {
            _completed = true;
            _eta = null;
            if (succeeded)
            {
                _percent = 100;
            }
            if (!string.IsNullOrWhiteSpace(stage))
            {
                _stage = stage;
            }

            return new NormalizedProgress(_percent, _stage, null);
        }
    }

    /// <summary>
    /// Maps a per-item reading into a slice of an overall run, so a batch of N
    /// files sweeps 0..100 once rather than once per file.
    /// </summary>
    public static double Scale(double itemPercent, int itemIndex, int itemCount)
    {
        if (itemCount <= 0)
        {
            return Math.Clamp(itemPercent, 0, 100);
        }

        var index = Math.Clamp(itemIndex, 0, itemCount - 1);
        var within = double.IsFinite(itemPercent) ? Math.Clamp(itemPercent, 0, 100) : 0;
        return Math.Clamp((index * 100.0 + within) / itemCount, 0, 100);
    }

    private int? CurrentEta()
    {
        if (_eta is not int eta)
        {
            return null;
        }
        if (_clock() - _etaObservedUtc > _etaFreshness)
        {
            // The engine stopped updating it. A countdown that keeps running on
            // its own is a worse answer than admitting we do not know.
            return null;
        }

        return eta;
    }
}
