using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Localization;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Security;
using UniversalConverterX.Core.Utilities;

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

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Video
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg",
        "3gp", "3g2", "mts", "m2ts", "ts", "vob", "ogv", "dv", "mxf", "nut",
        "rm", "rmvb", "asf", "divx", "f4v", "swf", "m2v", "mpv", "mp2", "mpe",
        // VVC / H.266 raw bitstreams — decode-only (FFmpeg 8.1 ships a native
        // vvc decoder + vvc_qsv). No VVC encode output; see RESEARCH.md.
        "vvc", "h266", "266",

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
        if (options.FfmpegArgumentOverride is { Count: > 0 } commandOverride)
        {
            if (!FfmpegCommandTemplate.ValidateMaterialized(
                    commandOverride,
                    job.InputPath,
                    job.OutputPath,
                    out var error))
            {
                throw new InvalidDataException(error);
            }

            return [.. commandOverride];
        }

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

        // Explicit per-track stream selection applies only to video output
        // (an audio-container output is inherently audio-only).
        var useExplicitMaps = isVideoOutput && HasTrackSelection(options);

        if (options.StreamCopy && isVideoOutput)
        {
            // Remux: copy the selected streams into the new container, no re-encode.
            args.AddRange(useExplicitMaps ? BuildStreamMapArgs(options) : ["-map", "0"]);
            args.AddRange(["-c", "copy"]);
        }
        else if (options.StreamCopy && isAudioOutput)
        {
            // Remux to an audio container: copy audio streams only, drop video.
            args.AddRange(["-map", "0:a?", "-c:a", "copy", "-vn"]);
        }
        else if (isVideoOutput)
        {
            if (useExplicitMaps)
                args.AddRange(BuildStreamMapArgs(options));
            BuildVideoArgs(args, options, job.OutputExtension);
        }
        else if (isAudioOutput)
        {
            BuildAudioArgs(args, options, job.OutputExtension);
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

    internal static bool HasTrackSelection(ConversionOptions options) =>
        options.AudioTrackSelection is not null || options.SubtitleTrackSelection is not null;

    /// <summary>
    /// Build explicit <c>-map</c> directives from the per-track selection. All
    /// video streams are always kept. A null audio/subtitle selection keeps every
    /// track of that kind; a list keeps exactly the listed zero-based indices; an
    /// empty list drops that kind entirely. The <c>?</c> suffix makes each map
    /// optional so a missing stream never fails the job.
    /// </summary>
    internal static string[] BuildStreamMapArgs(ConversionOptions options)
    {
        var maps = new List<string> { "-map", "0:v?" };

        if (options.AudioTrackSelection is null)
            maps.AddRange(["-map", "0:a?"]);
        else
            foreach (var index in options.AudioTrackSelection)
                maps.AddRange(["-map", $"0:a:{index}?"]);

        if (options.SubtitleTrackSelection is null)
            maps.AddRange(["-map", "0:s?"]);
        else
            foreach (var index in options.SubtitleTrackSelection)
                maps.AddRange(["-map", $"0:s:{index}?"]);

        return [.. maps];
    }

    /// <summary>
    /// True when the job asks for genuine average-bitrate two-pass encoding on the
    /// native path. Two-pass only helps with an explicit target bitrate; in CRF
    /// mode (or with a raw command override) it is a no-op, so those fall through
    /// to the single-pass base implementation.
    /// </summary>
    internal bool ShouldRunNativeTwoPass(ConversionJob job)
    {
        var video = job.Options.Video;
        return video.TwoPass == true
            && video.Bitrate.HasValue
            && !video.Crf.HasValue
            && !job.Options.StreamCopy
            && job.Options.FfmpegArgumentOverride is not { Count: > 0 }
            && IsVideoFormat(job.OutputExtension);
    }

    /// <summary>
    /// Derive the pass-1 or pass-2 command line from the single-pass arguments.
    /// Pass 1 analyses to the OS null sink with audio disabled; pass 2 writes the
    /// real output. Both carry <c>-pass N -passlogfile &lt;prefix&gt;</c>.
    /// </summary>
    internal string[] BuildPassArguments(ConversionJob job, ConversionOptions options, int pass, string passLogPrefix)
    {
        var args = BuildArguments(job, options).ToList();

        // Strip the trailing "-progress pipe:1 -stats_period 0.1" tail; the token
        // immediately before it is the output path.
        var progressIndex = args.LastIndexOf("-progress");
        if (progressIndex >= 0)
            args.RemoveRange(progressIndex, args.Count - progressIndex);

        var outputPath = args[^1];
        args.RemoveAt(args.Count - 1);

        args.AddRange(["-pass", pass.ToString(System.Globalization.CultureInfo.InvariantCulture), "-passlogfile", passLogPrefix]);

        if (pass == 1)
        {
            // Analysis pass: no audio, no muxed output.
            var nullSink = OperatingSystem.IsWindows() ? "NUL" : "/dev/null";
            args.AddRange(["-an", "-f", "null", nullSink]);
        }
        else
        {
            args.Add(outputPath);
            args.AddRange(["-progress", "pipe:1", "-stats_period", "0.1"]);
        }

        return [.. args];
    }

    public override async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var capability = CaptureCapability(job);
        var result = await ConvertOnceAsync(job, progress, cancellationToken);

        if (!capability.RequestedHardware)
            return AttachCapability(result, capability, fellBack: false, reason: null);

        if (!ShouldFallbackToSoftware(job, result))
            return AttachCapability(result, capability, fellBack: false, reason: null);

        var diagnostic = ArgumentRedactor.RedactMessage(
            string.Join(
                " | ",
                new[] { result.ErrorMessage, result.StandardError, result.StandardOutput }
                    .Where(value => !string.IsNullOrWhiteSpace(value)))
            .Trim());
        if (string.IsNullOrWhiteSpace(diagnostic))
            diagnostic = "The hardware encoder failed to initialize.";
        if (!TryDeletePartialOutput(job.OutputPath))
        {
            return AttachCapability(
                result,
                capability,
                fellBack: false,
                reason: $"Hardware encoding failed ({diagnostic}), and the partial output could not be replaced.");
        }

        var originalUseHardware = job.Options.UseHardwareAcceleration;
        var originalHardwareAcceleration = job.Options.HardwareAccel;
        var originalVideoCodec = job.Options.Video.Codec;
        try
        {
            // Keep the visible job request intact after the retry. History and
            // rerun parameters should continue to show what the user asked for,
            // while Capability records what actually produced this output.
            job.Options.UseHardwareAcceleration = false;
            job.Options.HardwareAccel = HardwareAcceleration.None;
            if (IsHardwareEncoder(originalVideoCodec))
                job.Options.Video.Codec = SoftwareCodecFor(originalVideoCodec) ?? "libx264";

            var fallback = await ConvertOnceAsync(job, progress, cancellationToken);
            return AttachCapability(
                fallback,
                capability,
                fellBack: true,
                reason: diagnostic);
        }
        finally
        {
            job.Options.UseHardwareAcceleration = originalUseHardware;
            job.Options.HardwareAccel = originalHardwareAcceleration;
            job.Options.Video.Codec = originalVideoCodec;
        }
    }

    private async Task<ConversionResult> ConvertOnceAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        if (!ShouldRunNativeTwoPass(job))
            return await base.ConvertAsync(job, progress, cancellationToken);

        return await ConvertTwoPassAsync(job, progress, cancellationToken);
    }

    private async Task<ConversionResult> ConvertTwoPassAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {

        var stopwatch = Stopwatch.StartNew();
        var warnings = new List<string>();
        using var timeoutCts = job.Options.Timeout is TimeSpan timeout && timeout > TimeSpan.Zero
            ? new CancellationTokenSource(timeout)
            : null;
        using var linkedCts = timeoutCts is null
            ? null
            : CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);
        var ct = linkedCts?.Token ?? cancellationToken;

        try
        {
            var validation = ValidateJob(job);
            if (!validation.IsValid)
                return ConversionResult.Failed(job, validation.ErrorMessage!, stopwatch.Elapsed);

            job.InputFileSize = new FileInfo(job.InputPath).Length;
            job.Status = ConversionStatus.Running;
            job.StartedAt = DateTime.UtcNow;

            var executablePath = GetExecutablePath();
            if (!File.Exists(executablePath))
                return ConversionResult.Failed(
                    job,
                    LocalizedText.Format(
                        "Core_ConverterExecutableNotFound",
                        "Converter executable was not found: {0}", executablePath),
                    stopwatch.Elapsed);

            var outputDir = Path.GetDirectoryName(job.OutputPath);
            if (!string.IsNullOrEmpty(outputDir) && !Directory.Exists(outputDir))
                Directory.CreateDirectory(outputDir);

            var passLogPrefix = Path.Combine(
                Path.GetTempPath(), "ucx-2pass-" + Guid.NewGuid().ToString("N"));

            try
            {
                // Pass 1 — analysis.
                progress?.Report(ConversionProgress.Indeterminate(
                    LocalizedText.Get("Core_TwoPassAnalyzing", "Analyzing (pass 1 of 2)..."),
                    ConversionStage.Initializing));

                var pass1Args = BuildPassArguments(job, job.Options, 1, passLogPrefix);
                var pass1 = await ExecuteProcessAsync(executablePath, pass1Args, job, null, warnings, ct);
                if (!pass1.Success)
                {
                    job.Status = ConversionStatus.Failed;
                    return ConversionResult.Failed(
                        job,
                        pass1.ErrorMessage ?? LocalizedText.Get(
                            "Core_TwoPassAnalysisFailed", "Two-pass analysis (pass 1) failed."),
                        stopwatch.Elapsed,
                        pass1.ExitCode,
                        pass1.StandardOutput,
                        pass1.StandardError,
                        Id,
                        FormatCommandLine(executablePath, pass1Args),
                        warnings);
                }

                // Pass 2 — real encode.
                var pass2Args = BuildPassArguments(job, job.Options, 2, passLogPrefix);
                var commandLine = FormatCommandLine(executablePath, pass2Args);
                var pass2 = await ExecuteProcessAsync(executablePath, pass2Args, job, progress, warnings, ct);

                stopwatch.Stop();
                job.CompletedAt = DateTime.UtcNow;

                if (pass2.Success)
                {
                    var outputFailure = ValidateSuccessfulOutput(
                        job, stopwatch.Elapsed, pass2.ExitCode,
                        pass2.StandardOutput, pass2.StandardError, Id, commandLine, warnings);
                    if (outputFailure != null)
                        return outputFailure;

                    job.Status = ConversionStatus.Completed;
                    return ConversionResult.Succeeded(
                        job, job.OutputPath, stopwatch.Elapsed, Id, commandLine, warnings);
                }

                job.Status = ConversionStatus.Failed;
                return ConversionResult.Failed(
                    job,
                    pass2.ErrorMessage ?? LocalizedText.Get("Core_UnknownError", "Unknown error"),
                    stopwatch.Elapsed, pass2.ExitCode, pass2.StandardOutput, pass2.StandardError,
                    Id, commandLine, warnings);
            }
            finally
            {
                CleanupPassLogs(passLogPrefix);
            }
        }
        catch (OperationCanceledException) when (timeoutCts?.IsCancellationRequested == true && !cancellationToken.IsCancellationRequested)
        {
            job.Status = ConversionStatus.Failed;
            job.CompletedAt = DateTime.UtcNow;
            if (File.Exists(job.OutputPath))
            {
                try { File.Delete(job.OutputPath); } catch { }
            }
            return ConversionResult.Failed(
                job,
                LocalizedText.Format("Core_ConversionTimedOut", "Conversion timed out after {0}.", job.Options.Timeout!.Value),
                stopwatch.Elapsed, exitCode: -1, converter: Id);
        }
        catch (OperationCanceledException)
        {
            job.Status = ConversionStatus.Cancelled;
            job.CompletedAt = DateTime.UtcNow;
            if (File.Exists(job.OutputPath))
            {
                try { File.Delete(job.OutputPath); } catch { }
            }
            return ConversionResult.Cancelled(job, stopwatch.Elapsed);
        }
        catch (Exception ex)
        {
            job.Status = ConversionStatus.Failed;
            job.CompletedAt = DateTime.UtcNow;
            Logger?.LogError(ex, "Two-pass conversion failed for {Input}", job.InputPath);
            return ConversionResult.Failed(job, ex.Message, stopwatch.Elapsed);
        }
    }

    internal static bool IsHardwareEncoder(string? codec)
    {
        if (string.IsNullOrWhiteSpace(codec))
            return false;

        var lowered = codec.ToLowerInvariant();
        return lowered.EndsWith("_nvenc", StringComparison.Ordinal)
            || lowered.EndsWith("_amf", StringComparison.Ordinal)
            || lowered.EndsWith("_qsv", StringComparison.Ordinal)
            || lowered.EndsWith("_vaapi", StringComparison.Ordinal)
            || lowered.EndsWith("_videotoolbox", StringComparison.Ordinal)
            || lowered.EndsWith("_vulkan", StringComparison.Ordinal)
            || lowered.EndsWith("_d3d12va", StringComparison.Ordinal);
    }

    internal static string? SoftwareCodecFor(string? codec)
    {
        if (!IsHardwareEncoder(codec))
            return codec;

        var name = codec!.ToLowerInvariant();
        if (name.StartsWith("h264_", StringComparison.Ordinal))
            return "libx264";
        if (name.StartsWith("hevc_", StringComparison.Ordinal))
            return "libx265";
        if (name.StartsWith("av1_", StringComparison.Ordinal))
            return "libsvtav1";
        if (name.StartsWith("vp9_", StringComparison.Ordinal))
            return "libvpx-vp9";
        return null;
    }

    private static CapabilityRequest CaptureCapability(ConversionJob job)
    {
        var requestedEncoder = ResolveRequestedVideoEncoder(job);
        var explicitHardwareEncoder = IsHardwareEncoder(job.Options.Video.Codec);
        var requestedHardware = IsVideoFormatForCapability(job.OutputExtension)
            && !job.Options.StreamCopy
            && job.Options.FfmpegArgumentOverride is not { Count: > 0 }
            && (explicitHardwareEncoder
                || (job.Options.UseHardwareAcceleration
                    && job.Options.HardwareAccel != HardwareAcceleration.None));

        var requested = explicitHardwareEncoder
            && (!job.Options.UseHardwareAcceleration
                || job.Options.HardwareAccel == HardwareAcceleration.None)
            ? "explicit hardware encoder"
            : job.Options.HardwareAccel.ToString();
        if (!requestedHardware)
            requested = "software";

        return new CapabilityRequest(requested, requestedEncoder, requestedHardware);
    }

    private static string ResolveRequestedVideoEncoder(ConversionJob job)
    {
        if (!IsVideoFormatForCapability(job.OutputExtension))
            return "software";
        if (!string.IsNullOrWhiteSpace(job.Options.Video.Codec))
            return job.Options.Video.Codec!;
        return job.Options.Quality == QualityPreset.Lossless
            ? "libx264"
            : GetDefaultVideoCodec(job.Options.HardwareAccel);
    }

    private static bool IsVideoFormatForCapability(string extension) => extension.ToLowerInvariant() switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "ogv" or "gif" => true,
        _ => false,
    };

    internal static bool ShouldFallbackToSoftware(ConversionJob job, ConversionResult result)
    {
        if (!job.Options.AllowHardwareFallback
            || result.Success
            || result.WasCancelled
            || result.WasSkipped
            || result.CommandLine is null)
        {
            return false;
        }

        var diagnostic = string.Join(
            "\n",
            new[] { result.ErrorMessage, result.StandardError, result.StandardOutput }
                .Where(value => !string.IsNullOrWhiteSpace(value)));
        if (string.IsNullOrWhiteSpace(diagnostic))
            return false;

        // Only retry failures that point at hardware initialization or the
        // selected hardware encoder. Codec/format mistakes and missing input
        // files must remain visible instead of being hidden by a CPU retry.
        var hardwareMarkers = new[]
        {
            "unknown encoder", "error while opening encoder", "no capable devices",
            "cannot load", "device setup failed", "failed to initialize",
            "failed to initialise", "hardware", "hwaccel", "d3d12", "nvenc",
            "amf", "qsv", "vaapi", "videotoolbox", "vulkan",
        };
        return hardwareMarkers.Any(marker =>
            diagnostic.Contains(marker, StringComparison.OrdinalIgnoreCase));
    }

    private static bool TryDeletePartialOutput(string outputPath)
    {
        if (!File.Exists(outputPath))
            return true;

        try
        {
            File.Delete(outputPath);
            return !File.Exists(outputPath);
        }
        catch
        {
            return false;
        }
    }

    private static ConversionResult AttachCapability(
        ConversionResult result,
        CapabilityRequest request,
        bool fellBack,
        string? reason)
    {
        if (result.CommandLine is null && !fellBack)
            return result;

        var selected = fellBack
            ? SoftwareCodecFor(request.Encoder) ?? "software"
            : request.Encoder;
        result.Capability = new CapabilityDecision(
            request.Requested,
            selected,
            fellBack,
            reason);
        return result;
    }

    private sealed record CapabilityRequest(
        string Requested,
        string Encoder,
        bool RequestedHardware);

    private static void CleanupPassLogs(string passLogPrefix)
    {
        try
        {
            var directory = Path.GetDirectoryName(passLogPrefix);
            var prefix = Path.GetFileName(passLogPrefix);
            if (string.IsNullOrEmpty(directory) || !Directory.Exists(directory))
                return;

            // ffmpeg writes "<prefix>-0.log" and "<prefix>-0.log.mbtree".
            foreach (var file in Directory.EnumerateFiles(directory, prefix + "*"))
            {
                try { File.Delete(file); } catch { /* best effort */ }
            }
        }
        catch { /* best effort cleanup */ }
    }

    private void BuildVideoArgs(
        List<string> args,
        ConversionOptions options,
        string outputExtension)
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
            args.AddRange(["-r", video.Fps.Value.ToString("F2", CultureInfo.InvariantCulture)]);

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

        // Two-pass encoding is handled by the ConvertAsync override (it runs
        // ffmpeg twice with -pass 1/-pass 2 + -passlogfile). BuildArguments here
        // always produces the single-invocation form; BuildPassArguments derives
        // the per-pass command lines from it. See ShouldRunNativeTwoPass.

        // Audio handling
        if (video.RemoveAudio || outputExtension == "gif")
        {
            args.Add("-an");
        }
        else
        {
            BuildAudioArgs(args, options, outputExtension);
        }
    }

    private static void BuildAudioArgs(
        List<string> args,
        ConversionOptions options,
        string outputExtension)
    {
        var audio = options.Audio;

        // Audio codec
        if (!string.IsNullOrEmpty(audio.Codec))
        {
            args.AddRange(["-c:a", audio.Codec]);
        }
        else
        {
            args.AddRange(["-c:a", DefaultAudioCodec(outputExtension)]);
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
            args.AddRange(["-af", FormattableString.Invariant($"volume={audio.Volume.Value:F2}")]);

        // Normalization
        if (audio.Normalize)
            args.AddRange(["-af", "loudnorm"]);
    }

    private static string DefaultAudioCodec(string outputExtension) =>
        outputExtension.ToLowerInvariant() switch
        {
            "mp3" => "libmp3lame",
            "wav" or "caf" => "pcm_s16le",
            "aiff" or "au" => "pcm_s16be",
            "flac" => "flac",
            "ogg" or "ogv" => "libvorbis",
            "opus" or "webm" => "libopus",
            "wma" => "wmav2",
            "ac3" => "ac3",
            _ => "aac",
        };

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
        TimeSpan? totalDuration;
        lock (job)
        {
            if (durationMatch.Success)
            {
                job.DetectedProgressDuration = new TimeSpan(
                    0,
                    int.Parse(durationMatch.Groups[1].Value),
                    int.Parse(durationMatch.Groups[2].Value),
                    int.Parse(durationMatch.Groups[3].Value),
                    int.Parse(durationMatch.Groups[4].Value) * 10);
            }

            totalDuration = job.DetectedProgressDuration;
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
        if (currentTime.HasValue && totalDuration.HasValue && totalDuration.Value.TotalSeconds > 0)
        {
            percent = currentTime.Value.TotalSeconds / totalDuration.Value.TotalSeconds * 100;
        }

        double? speed = speedMatch.Success ? double.Parse(speedMatch.Groups[1].Value, CultureInfo.InvariantCulture) : null;
        double? fps = fpsMatch.Success ? double.Parse(fpsMatch.Groups[1].Value, CultureInfo.InvariantCulture) : null;
        long? frame = frameMatch.Success ? long.Parse(frameMatch.Groups[1].Value) : null;
        long? size = sizeMatch.Success ? long.Parse(sizeMatch.Groups[1].Value) * 1024 : null;
        string? bitrate = bitrateMatch.Success ? $"{bitrateMatch.Groups[1].Value} kbits/s" : null;

        TimeSpan? eta = null;
        if (currentTime.HasValue && totalDuration.HasValue && speed.HasValue && speed.Value > 0)
        {
            var remaining = totalDuration.Value - currentTime.Value;
            eta = TimeSpan.FromSeconds(remaining.TotalSeconds / speed.Value);
        }

        return new ConversionProgress
        {
            Percent = Math.Clamp(percent, 0, 100),
            CurrentTime = currentTime,
            TotalDuration = totalDuration,
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
