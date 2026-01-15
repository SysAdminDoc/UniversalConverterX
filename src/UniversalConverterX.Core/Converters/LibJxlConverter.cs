using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// libjxl converter for JPEG XL image format.
/// JPEG XL offers excellent compression with both lossy and lossless modes,
/// and can losslessly recompress existing JPEG files.
/// </summary>
public partial class LibJxlConverter : BaseConverterStrategy
{
    public LibJxlConverter(string toolsBasePath, ILogger<LibJxlConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "libjxl";
    public override string Name => "libjxl";
    public override int Priority => 94; // High priority for JXL-specific operations
    public override string ExecutableName => "cjxl"; // JPEG XL encoder

    [GeneratedRegex(@"(\d+(?:\.\d+)?)%", RegexOptions.Compiled)]
    private static partial Regex PercentRegex();

    [GeneratedRegex(@"(\d+)/(\d+)\s+MB", RegexOptions.Compiled)]
    private static partial Regex SizeProgressRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => _formatMappings;

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // For encoding (cjxl)
        "jpg", "jpeg", "png", "apng", "gif", "exr", "ppm", "pfm", "pgm",
        
        // For decoding (djxl)
        "jxl"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Encode to JXL
        "jxl",
        
        // Decode JXL to standard formats
        "jpg", "jpeg", "png", "apng", "ppm", "pfm", "pgm", "npy"
    ];

    private static readonly Dictionary<string, HashSet<string>> _formatMappings = new()
    {
        // Standard formats to JXL
        ["jpg"] = ["jxl"],
        ["jpeg"] = ["jxl"],
        ["png"] = ["jxl"],
        ["apng"] = ["jxl"],
        ["gif"] = ["jxl"],
        ["exr"] = ["jxl"],
        ["ppm"] = ["jxl"],
        ["pfm"] = ["jxl"],
        ["pgm"] = ["jxl"],
        
        // JXL to standard formats
        ["jxl"] = ["jpg", "jpeg", "png", "apng", "ppm", "pfm", "pgm", "npy"]
    };

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var inputExt = job.InputExtension.ToLowerInvariant();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        var isEncoding = outputExt == "jxl";

        if (isEncoding)
        {
            // cjxl encoding options

            // Quality/Distance setting
            // JPEG XL uses distance (0-15) where 0 is lossless, 1.0 is visually lossless
            var distance = GetDistanceValue(options.Quality);
            args.AddRange(["-d", distance.ToString("F1")]);

            // Effort level (1-9, higher = slower but better compression)
            var effort = GetEffortValue(options.Quality);
            args.AddRange(["-e", effort.ToString()]);

            // Lossless mode for appropriate inputs
            if (options.Quality == QualityPreset.Lossless)
            {
                args.Add("--lossless_jpeg=1"); // Lossless JPEG recompression if input is JPEG
            }

            // Progressive decoding
            args.Add("--progressive");

            // Keep EXIF data unless stripping
            if (!options.Image.StripMetadata)
            {
                args.Add("--keep_exif");
                args.Add("--keep_xmp");
            }

            // Responsive encoding (better progressive preview)
            if (options.Quality >= QualityPreset.High)
            {
                args.Add("--responsive");
            }

            // Parallel encoding
            var threads = Environment.ProcessorCount;
            args.AddRange(["--num_threads", threads.ToString()]);

            // Input and output
            args.Add(job.InputPath);
            args.Add(job.OutputPath);
        }
        else
        {
            // djxl decoding options
            
            // Output format specific options
            if (outputExt is "jpg" or "jpeg")
            {
                var quality = GetJpegQuality(options.Quality);
                args.AddRange(["-q", quality.ToString()]);
            }

            // Number of threads
            var threads = Environment.ProcessorCount;
            args.AddRange(["--num_threads", threads.ToString()]);

            // Input and output
            args.Add(job.InputPath);
            args.Add(job.OutputPath);
        }

        return [.. args];
    }

    protected override string GetExecutablePath()
    {
        // Need to determine encoder vs decoder based on job
        // Default to encoder for path detection
        var baseName = ExecutableName;
        var exeName = OperatingSystem.IsWindows() ? $"{baseName}.exe" : baseName;

        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", exeName);
        if (File.Exists(toolPath))
            return toolPath;

        // Check common installation paths
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var jxlPath = Path.Combine(programFiles, "libjxl", "bin", exeName);
            if (File.Exists(jxlPath))
                return jxlPath;

            // Check for standalone distribution
            var standalonePath = Path.Combine(programFiles, "jxl", exeName);
            if (File.Exists(standalonePath))
                return standalonePath;
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

    public override async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var outputExt = job.OutputExtension.ToLowerInvariant();
        var isDecoding = outputExt != "jxl" && job.InputExtension.ToLowerInvariant() == "jxl";

        if (isDecoding)
        {
            // Use djxl for decoding
            return await ConvertWithDecoderAsync(job, progress, cancellationToken);
        }

        // Use cjxl for encoding (default)
        return await base.ConvertAsync(job, progress, cancellationToken);
    }

    private async Task<ConversionResult> ConvertWithDecoderAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        var decoderName = OperatingSystem.IsWindows() ? "djxl.exe" : "djxl";
        var decoderPath = Path.Combine(ToolsBasePath, "bin", decoderName);

        // Try to find decoder in PATH if not in tools
        if (!File.Exists(decoderPath))
        {
            var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
            foreach (var dir in pathDirs)
            {
                var fullPath = Path.Combine(dir, decoderName);
                if (File.Exists(fullPath))
                {
                    decoderPath = fullPath;
                    break;
                }
            }
        }

        if (!File.Exists(decoderPath))
        {
            return ConversionResult.Failed(job,
                "djxl decoder not found. Please install libjxl tools.",
                TimeSpan.Zero);
        }

        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var warnings = new List<string>();

        try
        {
            progress?.Report(ConversionProgress.Indeterminate("Decoding JPEG XL...", ConversionStage.Initializing));

            var args = BuildArguments(job, job.Options);
            var result = await ExecuteProcessAsync(
                decoderPath,
                args,
                job,
                progress,
                warnings,
                cancellationToken);

            stopwatch.Stop();

            if (result.Success)
            {
                job.Status = ConversionStatus.Completed;
                job.OutputFileSize = File.Exists(job.OutputPath) ? new FileInfo(job.OutputPath).Length : 0;

                return ConversionResult.Succeeded(job, job.OutputPath, stopwatch.Elapsed, Id);
            }

            return ConversionResult.Failed(job,
                result.ErrorMessage ?? "JPEG XL decoding failed",
                stopwatch.Elapsed);
        }
        catch (OperationCanceledException)
        {
            return ConversionResult.Cancelled(job, stopwatch.Elapsed);
        }
        catch (Exception ex)
        {
            return ConversionResult.Failed(job, ex.Message, stopwatch.Elapsed);
        }
    }

    private static double GetDistanceValue(QualityPreset preset) => preset switch
    {
        QualityPreset.Lowest => 4.0,      // Quite lossy
        QualityPreset.Low => 2.5,         // Noticeable artifacts
        QualityPreset.Medium => 1.5,      // Slight artifacts
        QualityPreset.High => 1.0,        // Visually lossless
        QualityPreset.Highest => 0.5,     // High quality
        QualityPreset.Lossless => 0.0,    // Mathematically lossless
        _ => 1.0
    };

    private static int GetEffortValue(QualityPreset preset) => preset switch
    {
        QualityPreset.Lowest => 3,
        QualityPreset.Low => 5,
        QualityPreset.Medium => 7,
        QualityPreset.High => 8,
        QualityPreset.Highest => 9,
        QualityPreset.Lossless => 9,
        _ => 7
    };

    private static int GetJpegQuality(QualityPreset preset) => preset switch
    {
        QualityPreset.Lowest => 50,
        QualityPreset.Low => 65,
        QualityPreset.Medium => 80,
        QualityPreset.High => 90,
        QualityPreset.Highest => 98,
        QualityPreset.Lossless => 100,
        _ => 85
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // Try percentage format
        var percentMatch = PercentRegex().Match(line);
        if (percentMatch.Success)
        {
            var percent = double.Parse(percentMatch.Groups[1].Value);
            return new ConversionProgress
            {
                Percent = Math.Min(percent, 100),
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing... {percent:F0}%",
                RawOutput = line
            };
        }

        // Try size progress format (MB processed)
        var sizeMatch = SizeProgressRegex().Match(line);
        if (sizeMatch.Success)
        {
            var current = int.Parse(sizeMatch.Groups[1].Value);
            var total = int.Parse(sizeMatch.Groups[2].Value);
            var percent = total > 0 ? (double)current / total * 100 : 0;

            return new ConversionProgress
            {
                Percent = percent,
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processed {current}/{total} MB",
                OutputSize = current * 1024 * 1024,
                RawOutput = line
            };
        }

        // Check for completion messages
        if (line.Contains("Compressed", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Decoded", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 100,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Finalizing...",
                RawOutput = line
            };
        }

        return null;
    }
}
