using System.Globalization;
using System.Text.RegularExpressions;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// User-selectable audio encoder settings shared by the WinUI surface and
/// headless tests. Nullable encoder-specific values are omitted unless their
/// matching codec is active.
/// </summary>
public sealed record AudioConversionOptions
{
    public required string Format { get; init; }
    public required string OutputDirectory { get; init; }
    public bool UseVariableBitrate { get; init; }
    public int VariableBitrateQuality { get; init; } = 2;
    public string? Bitrate { get; init; }
    public int? SampleRate { get; init; }
    public int? Channels { get; init; }
    public string? OpusApplication { get; init; }
    public double? OpusFrameDuration { get; init; }
    public string? OpusAmbisonics { get; init; }
    public int? FdkCutoff { get; init; }
    public bool? FdkAfterburner { get; init; }
    public string? FdkProfile { get; init; }
    public bool VorbisManaged { get; init; }
}

/// <summary>
/// Builds a discrete argument vector for the audiopro sidecar. Validation is
/// deliberately strict because the same values can later be reused by CLI and
/// shell surfaces without passing through WinUI controls.
/// </summary>
public static partial class AudioConversionCommandBuilder
{
    private static readonly IReadOnlySet<string> Formats = new HashSet<string>(
        ["mp3", "aac", "fdk-aac", "opus", "vorbis", "flac", "wav", "alac", "wavpack", "ac3", "eac3", "wma"],
        StringComparer.Ordinal);

    private static readonly IReadOnlySet<string> VariableBitrateFormats = new HashSet<string>(
        ["mp3", "aac", "fdk-aac", "opus", "vorbis"],
        StringComparer.Ordinal);

    private static readonly IReadOnlySet<string> OpusApplications = new HashSet<string>(
        ["voip", "audio", "lowdelay"],
        StringComparer.Ordinal);

    private static readonly IReadOnlySet<string> FdkProfiles = new HashSet<string>(
        ["aac_low", "aac_he", "aac_he_v2", "aac_ld", "aac_eld"],
        StringComparer.Ordinal);

    private static readonly IReadOnlySet<double> OpusFrameDurations = new HashSet<double>
        { 2.5, 5, 10, 20, 40, 60 };

    private static readonly IReadOnlySet<string> OpusAmbisonicsModes = new HashSet<string>(
        ["off", "acn-sn3d"],
        StringComparer.Ordinal);

    public static IReadOnlyList<string> Build(
        IReadOnlyList<string> inputFiles,
        AudioConversionOptions options)
    {
        ArgumentNullException.ThrowIfNull(inputFiles);
        ArgumentNullException.ThrowIfNull(options);
        if (inputFiles.Count == 0 || inputFiles.Any(string.IsNullOrWhiteSpace))
            throw new ArgumentException("At least one non-empty input path is required.", nameof(inputFiles));

        var format = options.Format.Trim().ToLowerInvariant();
        if (!Formats.Contains(format))
            throw new ArgumentException($"Unsupported audio format: '{options.Format}'.", nameof(options));
        ArgumentException.ThrowIfNullOrWhiteSpace(options.OutputDirectory);

        var arguments = new List<string>
        {
            "convert",
            "--format", format,
            "--output-dir", Path.GetFullPath(options.OutputDirectory),
        };

        var managedVorbis = format == "vorbis" && options.VorbisManaged;
        if (managedVorbis)
        {
            arguments.Add("--vorbis-managed");
            AddBitrate(arguments, options.Bitrate ?? "192k");
        }
        else if (options.UseVariableBitrate && VariableBitrateFormats.Contains(format))
        {
            arguments.Add("--vbr-quality");
            arguments.Add(Math.Clamp(options.VariableBitrateQuality, 0, 9).ToString(CultureInfo.InvariantCulture));
        }
        else if (!string.IsNullOrWhiteSpace(options.Bitrate))
        {
            AddBitrate(arguments, options.Bitrate);
        }

        if (options.SampleRate is int sampleRate)
        {
            if (sampleRate is < 8_000 or > 384_000)
                throw new ArgumentOutOfRangeException(nameof(options), "Sample rate must be between 8000 and 384000 Hz.");
            arguments.Add("--sample-rate");
            arguments.Add(sampleRate.ToString(CultureInfo.InvariantCulture));
        }

        if (options.Channels is int channels)
        {
            if (channels is < 1 or > 32)
                throw new ArgumentOutOfRangeException(nameof(options), "Channel count must be between 1 and 32.");
            arguments.Add("--channels");
            arguments.Add(channels.ToString(CultureInfo.InvariantCulture));
        }

        if (format == "opus")
        {
            if (!string.IsNullOrWhiteSpace(options.OpusApplication))
            {
                var application = options.OpusApplication.Trim().ToLowerInvariant();
                if (!OpusApplications.Contains(application))
                    throw new ArgumentException($"Unsupported Opus application: '{application}'.", nameof(options));
                arguments.Add("--opus-application");
                arguments.Add(application);
            }

            if (options.OpusFrameDuration is double frameDuration)
            {
                if (!OpusFrameDurations.Contains(frameDuration))
                    throw new ArgumentException($"Unsupported Opus frame duration: '{frameDuration}'.", nameof(options));
                arguments.Add("--opus-frame-duration");
                arguments.Add(frameDuration.ToString("0.#", CultureInfo.InvariantCulture));
            }

            if (!string.IsNullOrWhiteSpace(options.OpusAmbisonics))
            {
                var ambisonics = options.OpusAmbisonics.Trim().ToLowerInvariant();
                if (!OpusAmbisonicsModes.Contains(ambisonics))
                    throw new ArgumentException($"Unsupported Opus ambisonics mode: '{ambisonics}'.", nameof(options));
                if (ambisonics != "off")
                {
                    arguments.Add("--opus-ambisonics");
                    arguments.Add(ambisonics);
                }
            }
        }

        if (format == "fdk-aac")
        {
            if (options.FdkCutoff is int cutoff)
            {
                if (cutoff is < 0 or > 24_000)
                    throw new ArgumentOutOfRangeException(nameof(options), "FDK-AAC cutoff must be between 0 and 24000 Hz.");
                arguments.Add("--fdk-cutoff");
                arguments.Add(cutoff.ToString(CultureInfo.InvariantCulture));
            }

            if (options.FdkAfterburner is bool afterburner)
            {
                arguments.Add("--fdk-afterburner");
                arguments.Add(afterburner ? "true" : "false");
            }

            if (!string.IsNullOrWhiteSpace(options.FdkProfile))
            {
                var profile = options.FdkProfile.Trim().ToLowerInvariant();
                if (!FdkProfiles.Contains(profile))
                    throw new ArgumentException($"Unsupported FDK-AAC profile: '{profile}'.", nameof(options));
                arguments.Add("--fdk-profile");
                arguments.Add(profile);
            }
        }

        arguments.Add("--input");
        arguments.AddRange(inputFiles);
        return arguments;
    }

    private static void AddBitrate(ICollection<string> arguments, string bitrate)
    {
        var normalized = bitrate.Trim().ToLowerInvariant();
        if (!BitratePattern().IsMatch(normalized))
            throw new ArgumentException($"Invalid audio bitrate: '{bitrate}'.", nameof(bitrate));
        arguments.Add("--bitrate");
        arguments.Add(normalized);
    }

    [GeneratedRegex(@"^[1-9][0-9]{0,5}(?:\.[0-9]+)?[km]$")]
    private static partial Regex BitratePattern();
}
