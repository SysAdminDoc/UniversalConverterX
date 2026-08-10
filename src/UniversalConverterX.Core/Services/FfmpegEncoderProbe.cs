using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.RegularExpressions;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// A hardware video encoder exposed by the local FFmpeg build.
/// </summary>
public sealed record HardwareEncoder(string Name, string Codec, HardwareAcceleration Vendor);

/// <summary>
/// Detects which video encoders (especially hardware encoders beyond NVENC —
/// AMD AMF, Intel Quick Sync, VAAPI, etc.) the local FFmpeg build actually
/// exposes, by parsing <c>ffmpeg -encoders</c>. Parsing is pure and unit-tested;
/// the live probe is a thin, cached shell-out.
/// </summary>
public static partial class FfmpegEncoderProbe
{
    [GeneratedRegex(@"^\s*[VASFXBD.]{6}\s+(\S+)", RegexOptions.CultureInvariant)]
    private static partial Regex EncoderLine();

    private static readonly (string Suffix, HardwareAcceleration Vendor)[] VendorSuffixes =
    [
        ("_nvenc", HardwareAcceleration.Nvenc),
        ("_amf", HardwareAcceleration.Amf),
        ("_qsv", HardwareAcceleration.Qsv),
        ("_vaapi", HardwareAcceleration.Vaapi),
        ("_videotoolbox", HardwareAcceleration.VideoToolbox),
        ("_vulkan", HardwareAcceleration.Vulkan),
    ];

    private static readonly string[] D3d12EncoderSuffixes = ["_d3d12va"];

    private static readonly IReadOnlyDictionary<string, string[]> AccelerationSuffixes =
        new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["nvenc"] = ["_nvenc"],
            ["amf"] = ["_amf"],
            ["qsv"] = ["_qsv"],
            ["vaapi"] = ["_vaapi"],
            ["videotoolbox"] = ["_videotoolbox"],
            ["vulkan"] = ["_vulkan"],
            ["d3d12"] = D3d12EncoderSuffixes,
        };

    private static readonly ConcurrentDictionary<string, IReadOnlyList<HardwareEncoder>> LiveCache = new();
    private static readonly ConcurrentDictionary<string, IReadOnlySet<string>> EncoderNameCache = new();

    /// <summary>Extract every encoder name from <c>ffmpeg -encoders</c> output.</summary>
    public static IReadOnlySet<string> ParseEncoderNames(string ffmpegEncodersOutput)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        if (string.IsNullOrEmpty(ffmpegEncodersOutput))
            return names;

        foreach (var rawLine in ffmpegEncodersOutput.Split('\n'))
        {
            var match = EncoderLine().Match(rawLine);
            if (match.Success)
                names.Add(match.Groups[1].Value);
        }

        return names;
    }

    /// <summary>Classify the hardware video encoders in a set of encoder names.</summary>
    public static IReadOnlyList<HardwareEncoder> GetHardwareEncoders(IEnumerable<string> encoderNames)
    {
        var result = new List<HardwareEncoder>();
        foreach (var name in encoderNames)
        {
            foreach (var (suffix, vendor) in VendorSuffixes)
            {
                if (!name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
                    continue;

                var codec = name[..^suffix.Length];
                if (codec.Length > 0)
                    result.Add(new HardwareEncoder(name, codec, vendor));
                break;
            }
        }

        return result
            .OrderBy(encoder => encoder.Vendor)
            .ThenBy(encoder => encoder.Codec, StringComparer.Ordinal)
            .ToList();
    }

    /// <summary>Parse and classify in one step.</summary>
    public static IReadOnlyList<HardwareEncoder> DetectHardwareEncoders(string ffmpegEncodersOutput) =>
        GetHardwareEncoders(ParseEncoderNames(ffmpegEncodersOutput));

    /// <summary>
    /// Run <c>ffmpeg -hide_banner -encoders</c> at the given executable and return
    /// the detected hardware encoders, cached per executable path + last-write
    /// time. Returns an empty list when FFmpeg cannot be run.
    /// </summary>
    public static IReadOnlyList<HardwareEncoder> Probe(string ffmpegExecutablePath)
    {
        var names = ProbeEncoderNames(ffmpegExecutablePath);
        var cacheKey = BuildCacheKey(ffmpegExecutablePath);
        return LiveCache.GetOrAdd(cacheKey, _ => GetHardwareEncoders(names));
    }

    /// <summary>
    /// Run <c>ffmpeg -hide_banner -encoders</c> and return the complete encoder
    /// name set. This includes software encoders and newer vendor suffixes such
    /// as <c>_d3d12va</c> that do not map to the core acceleration enum.
    /// </summary>
    public static IReadOnlySet<string> ProbeEncoderNames(string ffmpegExecutablePath)
    {
        if (string.IsNullOrEmpty(ffmpegExecutablePath) || !File.Exists(ffmpegExecutablePath))
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        var cacheKey = BuildCacheKey(ffmpegExecutablePath);
        return EncoderNameCache.GetOrAdd(cacheKey, _ =>
        {
            var output = RunEncodersCommand(ffmpegExecutablePath);
            return output is null
                ? new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                : new HashSet<string>(ParseEncoderNames(output), StringComparer.OrdinalIgnoreCase);
        });
    }

    /// <summary>
    /// Return whether the probed encoder set contains at least one encoder for
    /// the requested UI/backend tag. The software option is always available;
    /// hardware options are enabled only when the configured FFmpeg build
    /// exposes a matching encoder.
    /// </summary>
    public static bool SupportsAcceleration(
        string? acceleration,
        IEnumerable<string> encoderNames)
    {
        if (string.IsNullOrWhiteSpace(acceleration)
            || acceleration.Equals("none", StringComparison.OrdinalIgnoreCase)
            || acceleration.Equals("software", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var names = encoderNames as IReadOnlyCollection<string>
            ?? encoderNames.ToArray();
        if (acceleration.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            return names.Any(name => IsKnownHardwareEncoder(name));
        }

        return AccelerationSuffixes.TryGetValue(acceleration, out var suffixes)
            && names.Any(name => suffixes.Any(suffix =>
                name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)));
    }

    /// <summary>
    /// Give the UI a useful disabled-state explanation instead of making a
    /// missing driver, FFmpeg build, or VRAM requirement look like a dead
    /// control.
    /// </summary>
    public static string DescribeUnavailable(
        string acceleration,
        bool ffmpegFound,
        IEnumerable<string> encoderNames)
    {
        if (!ffmpegFound)
        {
            return "Unavailable: the configured FFmpeg executable was not found. "
                + "Install/download FFmpeg in Settings > Tools.";
        }

        var expected = acceleration.ToLowerInvariant() switch
        {
            "nvenc" => "h264_nvenc, hevc_nvenc, or av1_nvenc",
            "amf" => "h264_amf, hevc_amf, or av1_amf",
            "qsv" => "h264_qsv, hevc_qsv, or av1_qsv",
            "d3d12" => "h264_d3d12va, hevc_d3d12va, or av1_d3d12va",
            "vaapi" => "a *_vaapi encoder",
            "videotoolbox" => "a *_videotoolbox encoder",
            "vulkan" => "a *_vulkan encoder",
            _ => "a compatible hardware encoder",
        };
        return $"Unavailable: this FFmpeg build exposes no {expected}. "
            + "Install a build with that encoder and verify the GPU driver and available VRAM.";
    }

    private static bool IsKnownHardwareEncoder(string name) =>
        AccelerationSuffixes.Values
            .SelectMany(suffixes => suffixes)
            .Any(suffix => name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase));

    private static string BuildCacheKey(string executablePath)
    {
        try
        {
            return executablePath + "|" + File.GetLastWriteTimeUtc(executablePath).Ticks;
        }
        catch
        {
            return executablePath;
        }
    }

    private static string? RunEncodersCommand(string executable)
    {
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = executable,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            startInfo.ArgumentList.Add("-hide_banner");
            startInfo.ArgumentList.Add("-encoders");

            using var process = Process.Start(startInfo);
            if (process is null)
                return null;

            var stdout = process.StandardOutput.ReadToEnd();
            if (!process.WaitForExit(TimeSpan.FromSeconds(5)))
            {
                try { process.Kill(entireProcessTree: true); } catch { /* best effort */ }
                return null;
            }

            return stdout;
        }
        catch
        {
            return null;
        }
    }
}
