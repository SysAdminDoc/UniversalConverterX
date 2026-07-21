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

    private static readonly ConcurrentDictionary<string, IReadOnlyList<HardwareEncoder>> LiveCache = new();

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
                if (!name.EndsWith(suffix, StringComparison.Ordinal))
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
        if (string.IsNullOrEmpty(ffmpegExecutablePath) || !File.Exists(ffmpegExecutablePath))
            return [];

        string cacheKey;
        try
        {
            cacheKey = ffmpegExecutablePath + "|" + File.GetLastWriteTimeUtc(ffmpegExecutablePath).Ticks;
        }
        catch
        {
            cacheKey = ffmpegExecutablePath;
        }

        return LiveCache.GetOrAdd(cacheKey, _ =>
        {
            var output = RunEncodersCommand(ffmpegExecutablePath);
            return output is null ? [] : DetectHardwareEncoders(output);
        });
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
