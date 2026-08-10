using System.Text.Json.Serialization;

namespace UniversalConverterX.Core.Models;

/// <summary>
/// Options for conversion operations
/// </summary>
public class ConversionOptions
{
    /// <summary>
    /// Quality preset
    /// </summary>
    public QualityPreset Quality { get; set; } = QualityPreset.High;

    /// <summary>
    /// Overwrite existing output file
    /// </summary>
    public bool OverwriteExisting { get; set; } = false;

    /// <summary>
    /// Preserve metadata from source file
    /// </summary>
    public bool PreserveMetadata { get; set; } = true;

    /// <summary>
    /// Use hardware acceleration if available
    /// </summary>
    public bool UseHardwareAcceleration { get; set; } = true;

    /// <summary>
    /// Preferred hardware acceleration method
    /// </summary>
    public HardwareAcceleration HardwareAccel { get; set; } = HardwareAcceleration.Auto;

    /// <summary>
    /// Retry a failed hardware encode with the equivalent software encoder.
    /// Scale, frame rate, stream selection, and other visible output options
    /// remain unchanged. The actual decision is recorded on the result.
    /// </summary>
    public bool AllowHardwareFallback { get; set; } = true;

    /// <summary>
    /// Force a specific converter
    /// </summary>
    public string? ForceConverter { get; set; }

    /// <summary>
    /// Video-specific options
    /// </summary>
    public VideoOptions Video { get; set; } = new();

    /// <summary>
    /// Audio-specific options
    /// </summary>
    public AudioOptions Audio { get; set; } = new();

    /// <summary>
    /// Image-specific options
    /// </summary>
    public ImageOptions Image { get; set; } = new();

    /// <summary>
    /// Document-specific options
    /// </summary>
    public DocumentOptions Document { get; set; } = new();

    /// <summary>
    /// Remux only: change the container without re-encoding any stream
    /// (FFmpeg <c>-c copy</c>). Skips codec/quality/two-pass planning. FFmpeg
    /// reports an error if a source codec is not allowed in the target
    /// container, which surfaces as a failed conversion.
    /// </summary>
    public bool StreamCopy { get; set; } = false;

    /// <summary>
    /// Per-track audio stream selection for FFmpeg video output. <c>null</c> keeps
    /// every audio track (default); an empty list drops all audio; a list of
    /// zero-based audio-stream indices keeps exactly those. Drives explicit
    /// <c>-map 0:a:&lt;i&gt;</c> mapping.
    /// </summary>
    public List<int>? AudioTrackSelection { get; set; }

    /// <summary>
    /// Per-track subtitle stream selection for FFmpeg video output. Same
    /// semantics as <see cref="AudioTrackSelection"/> but for subtitle streams.
    /// </summary>
    public List<int>? SubtitleTrackSelection { get; set; }

    /// <summary>
    /// Additional custom arguments to pass to the converter
    /// </summary>
    public List<string> CustomArguments { get; set; } = [];

    /// <summary>
    /// Validated, per-run FFmpeg argument vector supplied by Advanced Mode.
    /// It is never persisted; callers must materialize it from a command
    /// template for the current job's exact input and output paths.
    /// </summary>
    [JsonIgnore]
    public List<string>? FfmpegArgumentOverride { get; set; }

    /// <summary>
    /// Timeout for the conversion
    /// </summary>
    public TimeSpan? Timeout { get; set; }

    /// <summary>
    /// Delete source file after successful conversion.
    /// Deprecated — use <see cref="PostConversionAction"/> instead.
    /// Retained for backward compatibility with existing preset XML
    /// and JSON configs. When both are set, PostConversionAction wins.
    /// </summary>
    public bool DeleteSourceOnSuccess { get; set; } = false;

    /// <summary>
    /// Action to take on the source file after a successful conversion.
    /// </summary>
    public PostConversionAction PostConversionAction { get; set; } = PostConversionAction.Keep;

    /// <summary>
    /// Folder to move source files to when <see cref="PostConversionAction"/>
    /// is <see cref="Models.PostConversionAction.Move"/>. Absolute paths are
    /// used as-is; relative paths resolve from the source file's parent directory.
    /// </summary>
    public string? PostConversionArchiveFolder { get; set; }

    /// <summary>
    /// Output directory (if different from source)
    /// </summary>
    public string? OutputDirectory { get; set; }

    /// <summary>
    /// Output filename pattern (supports {name}, {ext}, {date})
    /// </summary>
    public string? OutputPattern { get; set; }
}

/// <summary>
/// Quality presets
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum QualityPreset
{
    Lowest,
    Low,
    Medium,
    High,
    Highest,
    Lossless
}

/// <summary>
/// Hardware acceleration methods
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum HardwareAcceleration
{
    Auto,
    None,
    Cuda,
    Nvenc,
    Qsv,
    Amf,
    VideoToolbox,
    Vaapi,
    Vulkan
}

/// <summary>
/// Video-specific conversion options
/// </summary>
public class VideoOptions
{
    public string? Codec { get; set; }
    public int? Width { get; set; }
    public int? Height { get; set; }
    public double? Fps { get; set; }
    public int? Bitrate { get; set; }
    public int? Crf { get; set; }
    public string? Preset { get; set; }
    public bool? TwoPass { get; set; }
    public TimeSpan? StartTime { get; set; }
    public TimeSpan? Duration { get; set; }
    public bool RemoveAudio { get; set; } = false;
    public string? AspectRatio { get; set; }
    public string? PixelFormat { get; set; }
}

/// <summary>
/// Audio-specific conversion options
/// </summary>
public class AudioOptions
{
    public string? Codec { get; set; }
    public int? Bitrate { get; set; }
    public int? SampleRate { get; set; }
    public int? Channels { get; set; }
    public double? Volume { get; set; }
    public bool Normalize { get; set; } = false;
    public TimeSpan? StartTime { get; set; }
    public TimeSpan? Duration { get; set; }
    public TimeSpan? FadeIn { get; set; }
    public TimeSpan? FadeOut { get; set; }
}

/// <summary>
/// Image-specific conversion options
/// </summary>
public class ImageOptions
{
    public int? Width { get; set; }
    public int? Height { get; set; }
    public int? Quality { get; set; }
    public bool MaintainAspectRatio { get; set; } = true;
    public string? ResizeFilter { get; set; }
    public bool StripMetadata { get; set; } = false;
    public bool Progressive { get; set; } = false;
    public int? Dpi { get; set; }
    public string? ColorSpace { get; set; }
    public int? BitDepth { get; set; }
    public bool Interlace { get; set; } = false;
    public string? Background { get; set; }
}

/// <summary>
/// Document-specific conversion options
/// </summary>
public class DocumentOptions
{
    public string? PageSize { get; set; }
    public string? Orientation { get; set; }
    public string? Margin { get; set; }
    public bool TableOfContents { get; set; } = false;
    public bool NumberSections { get; set; } = false;
    public string? CssFile { get; set; }
    public string? Template { get; set; }
    public bool Standalone { get; set; } = true;
    public string? PdfEngine { get; set; }
}

/// <summary>
/// Action to take on the source file after a successful conversion.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum PostConversionAction
{
    Keep,
    Move,
    Delete
}
