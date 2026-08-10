using System.ComponentModel;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// A stream row shown by Converter preflight. FFmpeg addresses audio and
/// subtitle rows by their zero-based index within that stream kind, while the
/// global index is retained for diagnostics and user-facing detail.
/// </summary>
public sealed class ConverterTrackRow : INotifyPropertyChanged
{
    private bool _keep = true;

    public event PropertyChangedEventHandler? PropertyChanged;

    public int StreamIndex { get; init; }
    public int KindIndex { get; init; } = -1;
    public string StreamType { get; init; } = "";
    public string Codec { get; init; } = "unknown";
    public string? Language { get; init; }
    public string? Title { get; init; }
    public bool IsDefault { get; init; }
    public int? Channels { get; init; }
    public string? Dimensions { get; init; }

    public bool IsAudio => string.Equals(StreamType, "audio", StringComparison.OrdinalIgnoreCase);
    public bool IsSubtitle => string.Equals(StreamType, "subtitle", StringComparison.OrdinalIgnoreCase);
    public bool IsSelectable => IsAudio || IsSubtitle;

    public bool Keep
    {
        get => _keep;
        set
        {
            if (_keep == value)
                return;

            _keep = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Keep)));
        }
    }

    public string DisplayName
    {
        get
        {
            var label = !string.IsNullOrWhiteSpace(Title)
                ? Title!.Trim()
                : !string.IsNullOrWhiteSpace(Language)
                    ? Language!.Trim()
                    : $"{StreamType} {KindIndex + 1}";
            if (!string.IsNullOrWhiteSpace(Title)
                && !string.IsNullOrWhiteSpace(Language)
                && !label.Contains(Language!, StringComparison.OrdinalIgnoreCase))
            {
                label = $"{label} ({Language!.Trim()})";
            }

            return label;
        }
    }

    public string Detail
    {
        get
        {
            var parts = new List<string>
            {
                $"{StreamType} {KindIndex + 1}",
                Codec,
            };
            if (!string.IsNullOrWhiteSpace(Dimensions))
                parts.Add(Dimensions!);
            if (Channels is int channels)
                parts.Add($"{channels}ch");
            if (IsDefault)
                parts.Add("default");
            parts.Add($"stream {StreamIndex}");
            return string.Join(" · ", parts);
        }
    }

    public string AutomationName => $"Keep {StreamType} track {KindIndex + 1}: {DisplayName}";
}
