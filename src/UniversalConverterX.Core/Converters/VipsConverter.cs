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
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Collect the per-format save options (Q=, compression=, lossless=,
        // effort=, strip=, interlace=) once. These are honored two ways by the
        // vips CLI: as trailing named arguments to a *save operation
        // (jpegsave in out Q=80), or embedded in the output filename brackets
        // for operations like `thumbnail` (out.jpg[Q=80,strip=true]).
        var saveOptions = BuildSaveOptions(outputExt, options);

        // Resize takes a different operation (`thumbnail`) that both scales and
        // saves. Its saver is chosen from the output extension, so the same
        // save options must ride along in the filename suffix — otherwise every
        // resized output silently reverts to default quality with metadata
        // intact, ignoring the user's settings.
        if (options.Image.Width.HasValue || options.Image.Height.HasValue)
        {
            var args = new List<string>
            {
                "thumbnail",
                job.InputPath,
                AppendSaveOptions(job.OutputPath, saveOptions),
            };

            if (options.Image.Width.HasValue && options.Image.Height.HasValue)
                args.Add($"{options.Image.Width}x{options.Image.Height}");
            else if (options.Image.Width.HasValue)
                args.Add($"{options.Image.Width}");
            else if (options.Image.Height.HasValue)
                args.Add($"x{options.Image.Height}");

            // Add crop mode
            if (!options.Image.MaintainAspectRatio)
                args.Add("crop=centre");

            return [.. args];
        }

        // No resize: use the format-specific save operation with the options as
        // trailing named arguments.
        var saveArgs = new List<string>
        {
            GetVipsOperation(outputExt),
            job.InputPath,
            job.OutputPath,
        };
        saveArgs.AddRange(saveOptions);
        return [.. saveArgs];
    }

    /// <summary>
    /// Builds the ordered list of vips save options (e.g. "Q=80", "strip=true")
    /// for the target format. Shared by the save-operation and thumbnail paths
    /// so a resized image keeps the same quality/compression/strip settings.
    /// </summary>
    private static List<string> BuildSaveOptions(string outputExt, ConversionOptions options)
    {
        var opts = new List<string>();
        var quality = GetQualityValue(options.Quality, outputExt);

        switch (outputExt)
        {
            case "jpg" or "jpeg":
                opts.Add($"Q={quality}");
                if (options.Image.Progressive)
                    opts.Add("interlace=true");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
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
                opts.Add($"compression={compression}");
                if (options.Image.Interlace)
                    opts.Add("interlace=true");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "webp":
                opts.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    opts.Add("lossless=true");
                opts.Add("effort=4");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "avif":
                opts.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    opts.Add("lossless=true");
                opts.Add("effort=4");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "heif" or "heic":
                opts.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    opts.Add("lossless=true");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "jxl":
                opts.Add($"Q={quality}");
                if (options.Quality == QualityPreset.Lossless)
                    opts.Add("lossless=true");
                opts.Add("effort=7");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "tiff" or "tif":
                // TIFF compression
                var tiffCompression = options.Quality switch
                {
                    QualityPreset.Lossless => "none",
                    QualityPreset.Highest => "lzw",
                    _ => "jpeg"
                };
                opts.Add($"compression={tiffCompression}");
                if (tiffCompression == "jpeg")
                    opts.Add($"Q={quality}");
                if (options.Image.StripMetadata)
                    opts.Add("strip=true");
                break;

            case "gif":
                // GIF options
                opts.Add("effort=7");
                break;
        }

        return opts;
    }

    /// <summary>
    /// Encodes vips save options into the output filename as a bracketed
    /// suffix, e.g. <c>out.jpg</c> + [Q=80,strip=true] → <c>out.jpg[Q=80,strip=true]</c>.
    /// This is the only way `thumbnail` (and other load/save ops) accept saver
    /// options. Returns the path unchanged when there are no options.
    /// </summary>
    private static string AppendSaveOptions(string outputPath, IReadOnlyList<string> saveOptions)
    {
        if (saveOptions.Count == 0)
            return outputPath;

        return $"{outputPath}[{string.Join(",", saveOptions)}]";
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
