using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// FFmpeg converter for video and audio formats
/// </summary>
public partial class FFmpegConverter : BaseConverterStrategy
{
    public FFmpegConverter(string toolsBasePath, ILogger<FFmpegConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "ffmpeg";
    public override string Name => "FFmpeg";
    public override int Priority => 100;
    public override string ExecutableName => "ffmpeg";

    // Progress parsing regex
    [GeneratedRegex(@"frame=\s*(\d+)", RegexOptions.Compiled)]
    private static partial Regex FrameRegex();

    [GeneratedRegex(@"fps=\s*([\d.]+)", RegexOptions.Compiled)]
    private static partial Regex FpsRegex();

    [GeneratedRegex(@"time=\s*(\d+):(\d+):(\d+)\.(\d+)", RegexOptions.Compiled)]
    private static partial Regex TimeRegex();

    [GeneratedRegex(@"speed=\s*([\d.]+)x", RegexOptions.Compiled)]
    private static partial Regex SpeedRegex();

    [GeneratedRegex(@"size=\s*(\d+)kB", RegexOptions.Compiled)]
    private static partial Regex SizeRegex();

    [GeneratedRegex(@"bitrate=\s*([\d.]+)kbits/s", RegexOptions.Compiled)]
    private static partial Regex BitrateRegex();

    [GeneratedRegex(@"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", RegexOptions.Compiled)]
    private static partial Regex DurationRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    private TimeSpan? _totalDuration;

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Video
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg",
        "3gp", "3g2", "mts", "m2ts", "ts", "vob", "ogv", "dv", "mxf", "nut",
        "rm", "rmvb", "asf", "divx", "f4v", "swf", "m2v", "mpv", "mp2", "mpe",
        
        // Audio
        "mp3", "wav", "flac", "aac", "ogg", "wma", "m4a", "opus", "aiff", "ape",
        "ac3", "dts", "eac3", "mka", "mpa", "ra", "tta", "wv", "au", "amr",
        "gsm", "sln", "voc", "caf", "w64", "tak",
        
        // Images (for video creation)
        "jpg", "jpeg", "png", "bmp", "gif", "tiff", "tif", "webp"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Video
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg",
        "3gp", "ts", "ogv", "mxf", "nut", "asf", "gif",
        
        // Audio
        "mp3", "wav", "flac", "aac", "ogg", "wma", "m4a", "opus", "aiff",
        "ac3", "mka", "au", "caf"
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();

        // Always overwrite and hide banner
        args.AddRange(["-y", "-hide_banner"]);

        // Hardware acceleration
        if (options.UseHardwareAcceleration && options.HardwareAccel != HardwareAcceleration.None)
        {
            var hwaccel = GetHardwareAccelArgs(options.HardwareAccel);
            if (hwaccel.Length > 0)
                args.AddRange(hwaccel);
        }

        // Input
        args.AddRange(["-i", job.InputPath]);

        // Time range
        if (options.Video.StartTime.HasValue)
            args.AddRange(["-ss", options.Video.StartTime.Value.ToString(@"hh\:mm\:ss\.fff")]);

        if (options.Video.Duration.HasValue)
            args.AddRange(["-t", options.Video.Duration.Value.ToString(@"hh\:mm\:ss\.fff")]);

        // Determine if output is video or audio
        var isVideoOutput = IsVideoFormat(job.OutputExtension);
        var isAudioOutput = IsAudioFormat(job.OutputExtension);

        if (isVideoOutput)
        {
            BuildVideoArgs(args, options);
        }
        else if (isAudioOutput)
        {
            BuildAudioArgs(args, options);
            args.Add("-vn"); // No video
        }

        // Metadata
        if (options.PreserveMetadata)
            args.AddRange(["-map_metadata", "0"]);

        // Custom arguments
        args.AddRange(options.CustomArguments);

        // Output
        args.Add(job.OutputPath);

        // Progress output
        args.AddRange(["-progress", "pipe:1", "-stats_period", "0.1"]);

        return [.. args];
    }

    private void BuildVideoArgs(List<string> args, ConversionOptions options)
    {
        var video = options.Video;

        // Video codec
        if (!string.IsNullOrEmpty(video.Codec))
        {
            args.AddRange(["-c:v", video.Codec]);
        }
        else
        {
            // Default codec based on quality preset
            var codec = options.Quality switch
            {
                QualityPreset.Lossless => "libx264",
                _ => GetDefaultVideoCodec(options.HardwareAccel)
            };
            args.AddRange(["-c:v", codec]);
        }

        // Resolution
        if (video.Width.HasValue && video.Height.HasValue)
        {
            args.AddRange(["-s", $"{video.Width}x{video.Height}"]);
        }
        else if (video.Width.HasValue || video.Height.HasValue)
        {
            var w = video.Width?.ToString() ?? "-1";
            var h = video.Height?.ToString() ?? "-1";
            args.AddRange(["-vf", $"scale={w}:{h}"]);
        }

        // Frame rate
        if (video.Fps.HasValue)
            args.AddRange(["-r", video.Fps.Value.ToString("F2")]);

        // Quality (CRF or bitrate)
        if (video.Crf.HasValue)
        {
            args.AddRange(["-crf", video.Crf.Value.ToString()]);
        }
        else if (video.Bitrate.HasValue)
        {
            args.AddRange(["-b:v", $"{video.Bitrate}k"]);
        }
        else
        {
            // Default CRF based on quality preset
            var crf = options.Quality switch
            {
                QualityPreset.Lowest => 32,
                QualityPreset.Low => 28,
                QualityPreset.Medium => 23,
                QualityPreset.High => 18,
                QualityPreset.Highest => 14,
                QualityPreset.Lossless => 0,
                _ => 23
            };
            args.AddRange(["-crf", crf.ToString()]);
        }

        // Preset
        if (!string.IsNullOrEmpty(video.Preset))
        {
            args.AddRange(["-preset", video.Preset]);
        }
        else
        {
            var preset = options.Quality switch
            {
                QualityPreset.Lowest or QualityPreset.Low => "veryfast",
                QualityPreset.Medium => "medium",
                QualityPreset.High => "slow",
                QualityPreset.Highest or QualityPreset.Lossless => "veryslow",
                _ => "medium"
            };
            args.AddRange(["-preset", preset]);
        }

        // Pixel format
        if (!string.IsNullOrEmpty(video.PixelFormat))
            args.AddRange(["-pix_fmt", video.PixelFormat]);

        // Two-pass encoding
        if (video.TwoPass == true)
        {
            // Note: Two-pass requires running ffmpeg twice, not implemented here
            Logger?.LogWarning("Two-pass encoding requested but not implemented in single-pass mode");
        }

        // Audio handling
        if (video.RemoveAudio)
        {
            args.Add("-an");
        }
        else
        {
            BuildAudioArgs(args, options);
        }
    }

    private void BuildAudioArgs(List<string> args, ConversionOptions options)
    {
        var audio = options.Audio;

        // Audio codec
        if (!string.IsNullOrEmpty(audio.Codec))
        {
            args.AddRange(["-c:a", audio.Codec]);
        }
        else
        {
            args.AddRange(["-c:a", "aac"]);
        }

        // Bitrate
        if (audio.Bitrate.HasValue)
        {
            args.AddRange(["-b:a", $"{audio.Bitrate}k"]);
        }
        else
        {
            var bitrate = options.Quality switch
            {
                QualityPreset.Lowest => 64,
                QualityPreset.Low => 96,
                QualityPreset.Medium => 128,
                QualityPreset.High => 192,
                QualityPreset.Highest => 256,
                QualityPreset.Lossless => 320,
                _ => 192
            };
            args.AddRange(["-b:a", $"{bitrate}k"]);
        }

        // Sample rate
        if (audio.SampleRate.HasValue)
            args.AddRange(["-ar", audio.SampleRate.Value.ToString()]);

        // Channels
        if (audio.Channels.HasValue)
            args.AddRange(["-ac", audio.Channels.Value.ToString()]);

        // Volume
        if (audio.Volume.HasValue && Math.Abs(audio.Volume.Value - 1.0) > 0.001)
            args.AddRange(["-af", $"volume={audio.Volume:F2}"]);

        // Normalization
        if (audio.Normalize)
            args.AddRange(["-af", "loudnorm"]);
    }

    private static string[] GetHardwareAccelArgs(HardwareAcceleration accel) => accel switch
    {
        HardwareAcceleration.Cuda => ["-hwaccel", "cuda"],
        HardwareAcceleration.Nvenc => ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
        HardwareAcceleration.Qsv => ["-hwaccel", "qsv"],
        HardwareAcceleration.Amf => ["-hwaccel", "d3d11va"],
        HardwareAcceleration.VideoToolbox => ["-hwaccel", "videotoolbox"],
        HardwareAcceleration.Vaapi => ["-hwaccel", "vaapi"],
        HardwareAcceleration.Auto => ["-hwaccel", "auto"],
        _ => []
    };

    private static string GetDefaultVideoCodec(HardwareAcceleration accel) => accel switch
    {
        HardwareAcceleration.Nvenc => "h264_nvenc",
        HardwareAcceleration.Qsv => "h264_qsv",
        HardwareAcceleration.Amf => "h264_amf",
        HardwareAcceleration.VideoToolbox => "h264_videotoolbox",
        HardwareAcceleration.Vaapi => "h264_vaapi",
        _ => "libx264"
    };

    private static bool IsVideoFormat(string ext) => ext switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "ogv" or "gif" => true,
        _ => false
    };

    private static bool IsAudioFormat(string ext) => ext switch
    {
        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or
        "opus" or "aiff" or "ac3" or "mka" or "au" or "caf" => true,
        _ => false
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // Try to extract duration first
        var durationMatch = DurationRegex().Match(line);
        if (durationMatch.Success)
        {
            _totalDuration = new TimeSpan(
                0,
                int.Parse(durationMatch.Groups[1].Value),
                int.Parse(durationMatch.Groups[2].Value),
                int.Parse(durationMatch.Groups[3].Value),
                int.Parse(durationMatch.Groups[4].Value) * 10);
        }

        // Parse progress line
        var frameMatch = FrameRegex().Match(line);
        var fpsMatch = FpsRegex().Match(line);
        var timeMatch = TimeRegex().Match(line);
        var speedMatch = SpeedRegex().Match(line);
        var sizeMatch = SizeRegex().Match(line);
        var bitrateMatch = BitrateRegex().Match(line);

        if (!timeMatch.Success && !frameMatch.Success)
            return null;

        TimeSpan? currentTime = null;
        if (timeMatch.Success)
        {
            currentTime = new TimeSpan(
                0,
                int.Parse(timeMatch.Groups[1].Value),
                int.Parse(timeMatch.Groups[2].Value),
                int.Parse(timeMatch.Groups[3].Value),
                int.Parse(timeMatch.Groups[4].Value) * 10);
        }

        double percent = 0;
        if (currentTime.HasValue && _totalDuration.HasValue && _totalDuration.Value.TotalSeconds > 0)
        {
            percent = currentTime.Value.TotalSeconds / _totalDuration.Value.TotalSeconds * 100;
        }

        double? speed = speedMatch.Success ? double.Parse(speedMatch.Groups[1].Value) : null;
        double? fps = fpsMatch.Success ? double.Parse(fpsMatch.Groups[1].Value) : null;
        long? frame = frameMatch.Success ? long.Parse(frameMatch.Groups[1].Value) : null;
        long? size = sizeMatch.Success ? long.Parse(sizeMatch.Groups[1].Value) * 1024 : null;
        string? bitrate = bitrateMatch.Success ? $"{bitrateMatch.Groups[1].Value} kbits/s" : null;

        TimeSpan? eta = null;
        if (currentTime.HasValue && _totalDuration.HasValue && speed.HasValue && speed.Value > 0)
        {
            var remaining = _totalDuration.Value - currentTime.Value;
            eta = TimeSpan.FromSeconds(remaining.TotalSeconds / speed.Value);
        }

        return new ConversionProgress
        {
            Percent = Math.Clamp(percent, 0, 100),
            CurrentTime = currentTime,
            TotalDuration = _totalDuration,
            CurrentFrame = frame,
            Fps = fps,
            Speed = speed,
            OutputSize = size,
            Bitrate = bitrate,
            EstimatedTimeRemaining = eta,
            Stage = ConversionStage.Encoding,
            RawOutput = line
        };
    }
}
