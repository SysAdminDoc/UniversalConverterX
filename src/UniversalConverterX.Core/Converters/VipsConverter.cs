using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// libvips converter for high-performance image processing.
/// Significantly faster and more memory-efficient than ImageMagick for many operations.
/// </summary>
public partial class VipsConverter : BaseConverterStrategy
{
    public VipsConverter(string toolsBasePath, ILogger<VipsConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "vips";
    public override string Name => "libvips";
    public override int Priority => 92; // Higher than ImageMagick for supported formats
    public override string ExecutableName => "vips";

    [GeneratedRegex(@"(\d+)%", RegexOptions.Compiled)]
    private static partial Regex PercentRegex();

    [GeneratedRegex(@"vips-(\d+\.\d+\.\d+)", RegexOptions.Compiled)]
    private static partial Regex VersionRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Standard image formats
        "jpg", "jpeg", "png", "webp", "gif", "tiff", "tif", "bmp",
        "ppm", "pgm", "pbm", "pfm",
        
        // RAW formats (via libraw)
        "raw", "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2",
        
        // HDR formats
        "hdr", "exr", "fits", "fit",
        
        // Modern formats
        "heic", "heif", "avif", "jxl",
        
        // Vector (rasterization)
        "svg", "pdf",
        
        // Special formats
        "v", "vips", "mat", "npy"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Standard formats
        "jpg", "jpeg", "png", "webp", "gif", "tiff", "tif",
        "ppm", "pgm", "pbm", "pfm",
        
        // HDR formats
        "hdr", "exr", "fits", "fit",
        
        // Modern formats
        "heic", "heif", "avif", "jxl",
        
        // Special
        "v", "vips", "mat", "npy", "raw"
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Determine the vips operation based on output format
        var operation = GetVipsOperation(outputExt);

        // Main conversion command
        args.Add(operation);
        args.Add(job.InputPath);
        args.Add(job.OutputPath);

        // Quality settings
        var quality = GetQualityValue(options.Quality, outputExt);
        
        switch (outputExt)
        {
            case "jpg" or "jpeg":
                args.Add($"Q={quality}");
                if (options.Image.Progressive)
                    args.Add("interlace=true");
                if (options.Image.StripMetadata)
                    args.Add("strip=true");
                break;

            case "png":
                // PNG compression level (0-9)
                var compression = options.Quality switch
                {
                    QualityPreset.Lowest => 9,
                    QualityPreset.Low => 7,
                    QualityPreset.Medium => 5,
                    QualityPreset.High => 3,
                    QualityPreset.Highest => 1,
                    QualityPreset.Lossless => 0,
                    _ => 5
                };
                args.Add($"compression={compression}");
                if (options.Image.Interlace)
                    args.Add("interlace=true");
                break;

            case "webp":
                args.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    args.Add("lossless=true");
                args.Add("effort=4");
                break;

            case "avif":
                args.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    args.Add("lossless=true");
                args.Add("effort=4");
                break;

            case "heif" or "heic":
                args.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    args.Add("lossless=true");
                break;

            case "jxl":
                args.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    args.Add("lossless=true");
                args.Add("effort=7");
                break;

            case "tiff" or "tif":
                // TIFF compression
                var tiffCompression = options.Quality switch
                {
                    QualityPreset.Lossless => "none",
                    QualityPreset.Highest => "lzw",
                    _ => "jpeg"
                };
                args.Add($"compression={tiffCompression}");
                if (tiffCompression == "jpeg")
                    args.Add($"Q={quality}");
                break;

            case "gif":
                // GIF options
                args.Add("effort=7");
                break;
        }

        // Resize if dimensions specified
        if (options.Image.Width.HasValue || options.Image.Height.HasValue)
        {
            // For resize, we need to use thumbnail or resize operation
            // This requires a different command structure
            // We'll handle this by prepending resize args
            args.Clear();
            args.Add("thumbnail");
            args.Add(job.InputPath);
            args.Add(job.OutputPath);
            
            if (options.Image.Width.HasValue && options.Image.Height.HasValue)
            {
                args.Add($"{options.Image.Width}x{options.Image.Height}");
            }
            else if (options.Image.Width.HasValue)
            {
                args.Add($"{options.Image.Width}");
            }
            else if (options.Image.Height.HasValue)
            {
                args.Add($"x{options.Image.Height}");
            }

            // Add crop mode
            if (!options.Image.MaintainAspectRatio)
                args.Add("crop=centre");
        }

        return [.. args];
    }

    private static string GetVipsOperation(string outputExt) => outputExt switch
    {
        "jpg" or "jpeg" => "jpegsave",
        "png" => "pngsave",
        "webp" => "webpsave",
        "gif" => "gifsave",
        "tiff" or "tif" => "tiffsave",
        "heif" or "heic" => "heifsave",
        "avif" => "avifsave",
        "jxl" => "jxlsave",
        "fits" or "fit" => "fitssave",
        "ppm" or "pgm" or "pbm" => "ppmsave",
        "raw" => "rawsave",
        "v" or "vips" => "vipssave",
        "mat" => "matrixsave",
        "npy" => "numpysave",
        _ => "copy"
    };

    private static int GetQualityValue(QualityPreset preset, string format)
    {
        // Different formats have different quality scales
        return format switch
        {
            "jxl" => preset switch
            {
                QualityPreset.Lowest => 30,
                QualityPreset.Low => 50,
                QualityPreset.Medium => 70,
                QualityPreset.High => 85,
                QualityPreset.Highest => 95,
                QualityPreset.Lossless => 100,
                _ => 80
            },
            _ => preset switch
            {
                QualityPreset.Lowest => 40,
                QualityPreset.Low => 55,
                QualityPreset.Medium => 75,
                QualityPreset.High => 85,
                QualityPreset.Highest => 95,
                QualityPreset.Lossless => 100,
                _ => 85
            }
        };
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // vips outputs progress as percentage
        var match = PercentRegex().Match(line);
        if (match.Success && int.TryParse(match.Groups[1].Value, out var percent))
        {
            return new ConversionProgress
            {
                Percent = percent,
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing... {percent}%",
                RawOutput = line
            };
        }

        // Check for completion
        if (line.Contains("done", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 100,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Completing...",
                RawOutput = line
            };
        }

        return null;
    }

    protected override string GetExecutablePath()
    {
        var exeName = OperatingSystem.IsWindows() ? "vips.exe" : "vips";

        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", exeName);
        if (File.Exists(toolPath))
            return toolPath;

        // Check common installation paths
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var vipsPath = Path.Combine(programFiles, "vips", "bin", "vips.exe");
            if (File.Exists(vipsPath))
                return vipsPath;
        }

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, exeName);
            if (File.Exists(fullPath))
                return fullPath;
        }

        return toolPath;
    }
}
