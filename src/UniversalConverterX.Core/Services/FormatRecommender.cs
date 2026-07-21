using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Intended delivery target for a converted file. Drives a fully offline,
/// deterministic format recommendation — no cloud, no telemetry.
/// </summary>
public enum RecommendationTarget
{
    /// Broadest browser/device playback.
    Web,
    /// Apple devices (iPhone/iPad/Mac).
    Apple,
    /// Android devices.
    Android,
    /// Discord upload (small, universally playable).
    Discord,
    /// Email attachment (small, universally openable).
    Email,
    /// Long-term archival (lossless, open formats).
    Archive,
    /// Editing round-trip (intra-frame, high quality).
    Editing,
}

public sealed record FormatRecommendation(
    string Container,
    string? VideoCodec,
    string? AudioCodec,
    string Rationale,
    bool Lossless = false);

/// <summary>
/// Rule-based "best format for this file and target" advisor. Deterministic and
/// offline: it maps the source's media category and the delivery target to a
/// concrete container/codec choice with a short rationale. It never touches the
/// network and never phones home.
/// </summary>
public static class FormatRecommender
{
    public static FormatRecommendation Recommend(FormatCategory sourceCategory, RecommendationTarget target)
        => sourceCategory switch
        {
            FormatCategory.Video => RecommendVideo(target),
            FormatCategory.Audio => RecommendAudio(target),
            FormatCategory.Image => RecommendImage(target),
            _ => new FormatRecommendation(
                Container: "mp4",
                VideoCodec: null,
                AudioCodec: null,
                Rationale: "No media-specific recommendation for this file type; convert to a container appropriate for its contents.",
                Lossless: false),
        };

    /// <summary>Convenience overload that classifies by file extension first.</summary>
    public static FormatRecommendation Recommend(string sourcePathOrExtension, RecommendationTarget target)
    {
        var ext = NormalizeExtension(sourcePathOrExtension);
        return Recommend(CategoryForExtension(ext), target);
    }

    private static FormatRecommendation RecommendVideo(RecommendationTarget target) => target switch
    {
        RecommendationTarget.Web => new("mp4", "h264", "aac",
            "H.264/AAC in MP4 plays in every browser and on every device without plugins."),
        RecommendationTarget.Apple => new("mp4", "hevc", "aac",
            "Apple devices hardware-decode HEVC/AAC in MP4 for smaller files than H.264 at the same quality."),
        RecommendationTarget.Android => new("mp4", "h264", "aac",
            "H.264/AAC in MP4 is the most broadly hardware-decoded combination across Android versions."),
        RecommendationTarget.Discord => new("mp4", "h264", "aac",
            "MP4 with H.264/AAC previews inline on Discord; pair with a size-target preset to fit the upload cap."),
        RecommendationTarget.Email => new("mp4", "h264", "aac",
            "MP4/H.264/AAC opens in every mail client and player; keep the bitrate low for a small attachment."),
        RecommendationTarget.Archive => new("mkv", "ffv1", "flac",
            "FFV1 video and FLAC audio in Matroska are lossless, open, and checksummed for long-term preservation.",
            Lossless: true),
        RecommendationTarget.Editing => new("mov", "prores", "pcm_s16le",
            "ProRes with PCM audio in MOV is an intra-frame mezzanine that edits smoothly in NLEs."),
        _ => new("mp4", "h264", "aac", "H.264/AAC in MP4 is the safe default."),
    };

    private static FormatRecommendation RecommendAudio(RecommendationTarget target) => target switch
    {
        RecommendationTarget.Web => new("opus", null, "libopus",
            "Opus offers the best quality-per-byte for web audio and is supported by all modern browsers."),
        RecommendationTarget.Apple => new("m4a", null, "aac",
            "AAC in an M4A container is the native Apple audio format across iOS and macOS."),
        RecommendationTarget.Android => new("m4a", null, "aac",
            "AAC in M4A is universally supported on Android and small at a given quality."),
        RecommendationTarget.Discord => new("mp3", null, "libmp3lame",
            "MP3 previews inline on Discord and plays everywhere."),
        RecommendationTarget.Email => new("mp3", null, "libmp3lame",
            "MP3 opens in every mail client and media player."),
        RecommendationTarget.Archive => new("flac", null, "flac",
            "FLAC is lossless and open — the standard for audio archival.",
            Lossless: true),
        RecommendationTarget.Editing => new("wav", null, "pcm_s16le",
            "Uncompressed PCM in WAV avoids generational loss during editing."),
        _ => new("mp3", null, "libmp3lame", "MP3 is the safe default."),
    };

    private static FormatRecommendation RecommendImage(RecommendationTarget target) => target switch
    {
        RecommendationTarget.Web => new("webp", null, null,
            "WebP is broadly supported and markedly smaller than JPEG/PNG at equal quality."),
        RecommendationTarget.Apple => new("heic", null, null,
            "HEIC is the native Apple photo format with strong compression and HDR support."),
        RecommendationTarget.Android => new("webp", null, null,
            "WebP is natively supported on Android and smaller than JPEG/PNG."),
        RecommendationTarget.Discord => new("png", null, null,
            "PNG renders inline on Discord without recompression artifacts; use JPEG/WebP for photos to save size."),
        RecommendationTarget.Email => new("jpg", null, null,
            "JPEG opens in every client and keeps photo attachments small."),
        RecommendationTarget.Archive => new("png", null, null,
            "PNG is lossless and universally readable; consider JPEG XL for smaller lossless archives.",
            Lossless: true),
        RecommendationTarget.Editing => new("tiff", null, null,
            "TIFF preserves full-quality raster data for editing round-trips.",
            Lossless: true),
        _ => new("webp", null, null, "WebP is the safe default."),
    };

    private static string NormalizeExtension(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return string.Empty;

        var trimmed = value.Trim();
        var ext = Path.HasExtension(trimmed)
            ? Path.GetExtension(trimmed)
            : trimmed;
        return ext.TrimStart('.').ToLowerInvariant();
    }

    private static FormatCategory CategoryForExtension(string ext) => ext switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "mts" => FormatCategory.Video,

        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or
        "opus" or "aiff" or "ape" or "ac3" => FormatCategory.Audio,

        "jpg" or "jpeg" or "png" or "gif" or "bmp" or "tiff" or "tif" or
        "webp" or "ico" or "heic" or "heif" or "avif" or "jxl" => FormatCategory.Image,

        _ => FormatCategory.Unknown,
    };
}
