using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// ImageMagick converter for image formats
/// </summary>
public partial class ImageMagickConverter : BaseConverterStrategy
{
    public ImageMagickConverter(string toolsBasePath, ILogger<ImageMagickConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "imagemagick";
    public override string Name => "ImageMagick";
    public override int Priority => 90;
    public override string ExecutableName => "magick";

    [GeneratedRegex(@"(\d+)%", RegexOptions.Compiled)]
    private static partial Regex PercentRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Common formats
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "ico", "svg",
        
        // Raw formats
        "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2", "pef", "srw", "raf",
        
        // Professional formats
        "psd", "psb", "xcf", "ai", "eps", "pdf",
        
        // Other formats
        "heic", "heif", "avif", "jxl", "jp2", "j2k", "jpf", "jpm", "mj2",
        "pcx", "ppm", "pgm", "pbm", "pnm", "tga", "dds", "hdr", "exr", "dpx",
        "cin", "sgi", "rgbe", "pic", "pict", "pct", "palm", "xpm", "xbm",
        "wbmp", "jbig", "jbig2", "mng", "apng", "cur", "ani", "fax", "fits",
        "dcm", "dicom", "mat", "miff", "otb", "pdb", "pfm", "pix", "plasma",
        "pwp", "rla", "sct", "sfw", "sun", "tim", "viff", "vicar", "vst",
        "xc", "ycbcr", "yuv"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Common formats
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "ico", "pdf",
        
        // Modern formats
        "avif", "jxl", "heic",
        
        // Other formats  
        "psd", "eps", "svg", "pcx", "ppm", "pgm", "pbm", "pnm", "tga", "dds",
        "hdr", "exr", "dpx", "jp2", "mng", "apng", "xpm", "xbm"
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var image = options.Image;

        // Input file
        args.Add(job.InputPath);

        // Auto-orient based on EXIF
        args.Add("-auto-orient");

        // Resize
        if (image.Width.HasValue || image.Height.HasValue)
        {
            var geometry = BuildResizeGeometry(image);
            args.AddRange(["-resize", geometry]);
        }

        // Quality
        var quality = image.Quality ?? GetDefaultQuality(options.Quality, job.OutputExtension);
        args.AddRange(["-quality", quality.ToString()]);

        // Strip metadata if requested
        if (image.StripMetadata)
        {
            args.Add("-strip");
        }
        else if (options.PreserveMetadata)
        {
            // Preserve all profiles
            args.AddRange(["-define", "preserve-profile=true"]);
        }

        // DPI
        if (image.Dpi.HasValue)
        {
            args.AddRange(["-density", $"{image.Dpi}x{image.Dpi}"]);
            args.AddRange(["-units", "PixelsPerInch"]);
        }

        // Color space
        if (!string.IsNullOrEmpty(image.ColorSpace))
        {
            args.AddRange(["-colorspace", image.ColorSpace]);
        }

        // Bit depth
        if (image.BitDepth.HasValue)
        {
            args.AddRange(["-depth", image.BitDepth.Value.ToString()]);
        }

        // Progressive JPEG
        if (image.Progressive && (job.OutputExtension == "jpg" || job.OutputExtension == "jpeg"))
        {
            args.Add("-interlace");
            args.Add("Plane");
        }

        // Interlace for PNG
        if (image.Interlace && job.OutputExtension == "png")
        {
            args.Add("-interlace");
            args.Add("PNG");
        }

        // Background color (for transparent to non-transparent conversion)
        if (!string.IsNullOrEmpty(image.Background))
        {
            args.AddRange(["-background", image.Background]);
            args.Add("-flatten");
        }
        else if (NeedsBackgroundFlatten(job.InputExtension, job.OutputExtension))
        {
            args.AddRange(["-background", "white"]);
            args.Add("-flatten");
        }

        // Format-specific options
        AddFormatSpecificOptions(args, job.OutputExtension, options);

        // Custom arguments
        args.AddRange(options.CustomArguments);

        // Output file
        args.Add(job.OutputPath);

        return [.. args];
    }

    private static string BuildResizeGeometry(ImageOptions image)
    {
        if (image.Width.HasValue && image.Height.HasValue)
        {
            var flag = image.MaintainAspectRatio ? "" : "!";
            return $"{image.Width}x{image.Height}{flag}";
        }
        else if (image.Width.HasValue)
        {
            return $"{image.Width}x";
        }
        else if (image.Height.HasValue)
        {
            return $"x{image.Height}";
        }
        return "";
    }

    private static int GetDefaultQuality(QualityPreset preset, string outputExt)
    {
        // Different defaults for different formats
        var baseQuality = preset switch
        {
            QualityPreset.Lowest => 30,
            QualityPreset.Low => 50,
            QualityPreset.Medium => 75,
            QualityPreset.High => 85,
            QualityPreset.Highest => 95,
            QualityPreset.Lossless => 100,
            _ => 85
        };

        // Adjust for format
        return outputExt switch
        {
            "webp" => Math.Min(baseQuality, 90), // WebP quality works differently
            "avif" => Math.Min(baseQuality - 10, 80), // AVIF is more efficient
            "jxl" => baseQuality, // JXL handles quality well
            _ => baseQuality
        };
    }

    private static bool NeedsBackgroundFlatten(string input, string output)
    {
        // If converting from format with transparency to one without
        var hasTransparency = input is "png" or "gif" or "webp" or "tiff" or "tif" or "psd";
        var supportsTransparency = output is "png" or "gif" or "webp" or "tiff" or "tif" or "psd" or "ico";
        
        return hasTransparency && !supportsTransparency;
    }

    private static void AddFormatSpecificOptions(List<string> args, string outputExt, ConversionOptions options)
    {
        switch (outputExt)
        {
            case "webp":
                args.AddRange(["-define", "webp:lossless=false"]);
                args.AddRange(["-define", "webp:method=6"]);
                break;

            case "avif":
                args.AddRange(["-define", "heic:speed=6"]);
                break;

            case "png":
                if (options.Quality == QualityPreset.Lossless)
                {
                    args.AddRange(["-define", "png:compression-level=9"]);
                    args.AddRange(["-define", "png:compression-filter=5"]);
                }
                break;

            case "gif":
                args.AddRange(["-layers", "optimize"]);
                break;

            case "ico":
                // Create multi-resolution ICO
                args.AddRange(["-define", "icon:auto-resize=256,128,64,48,32,16"]);
                break;

            case "pdf":
                args.AddRange(["-compress", "jpeg"]);
                break;

            case "tiff" or "tif":
                args.AddRange(["-compress", "lzw"]);
                break;
        }
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // ImageMagick doesn't output detailed progress by default
        // We look for percentage indicators
        var match = PercentRegex().Match(line);
        if (match.Success)
        {
            var percent = int.Parse(match.Groups[1].Value);
            return ConversionProgress.FromPercent(percent);
        }

        // Check for processing stages
        if (line.Contains("Loading", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Loading image...", ConversionStage.Analyzing);
        }
        if (line.Contains("Resizing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Resizing...", ConversionStage.Converting);
        }
        if (line.Contains("Writing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Writing output...", ConversionStage.Finalizing);
        }

        return null;
    }
}
