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
    /// Additional custom arguments to pass to the converter
    /// </summary>
    public List<string> CustomArguments { get; set; } = [];

    /// <summary>
    /// Timeout for the conversion
    /// </summary>
    public TimeSpan? Timeout { get; set; }

    /// <summary>
    /// Delete source file after successful conversion
    /// </summary>
    public bool DeleteSourceOnSuccess { get; set; } = false;

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
