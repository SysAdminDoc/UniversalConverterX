using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// libheif converter for HEIC/HEIF image format support.
/// HEIC is Apple's preferred image format for iOS devices.
/// </summary>
public partial class LibHeifConverter : BaseConverterStrategy
{
    public LibHeifConverter(string toolsBasePath, ILogger<LibHeifConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "libheif";
    public override string Name => "libheif";
    public override int Priority => 96; // High priority for HEIC specifically
    public override string ExecutableName => "heif-convert";

    [GeneratedRegex(@"(\d+)/(\d+)", RegexOptions.Compiled)]
    private static partial Regex ProgressRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => _formatMappings;

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // HEIF/HEIC variants
        "heic", "heif", "heics", "heifs",
        "hif",  // Alternative extension
        "avif", // AV1 Image Format (supported by libheif)
        
        // Standard formats (for encoding to HEIF)
        "jpg", "jpeg", "png", "y4m"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Decode HEIF to standard formats
        "jpg", "jpeg", "png", "y4m",
        
        // Encode to HEIF
        "heic", "heif", "avif"
    ];

    private static readonly Dictionary<string, HashSet<string>> _formatMappings = new()
    {
        // HEIF decode
        ["heic"] = ["jpg", "jpeg", "png", "y4m"],
        ["heif"] = ["jpg", "jpeg", "png", "y4m"],
        ["heics"] = ["jpg", "jpeg", "png", "y4m"],
        ["heifs"] = ["jpg", "jpeg", "png", "y4m"],
        ["hif"] = ["jpg", "jpeg", "png", "y4m"],
        ["avif"] = ["jpg", "jpeg", "png", "y4m"],
        
        // Standard to HEIF encode
        ["jpg"] = ["heic", "heif", "avif"],
        ["jpeg"] = ["heic", "heif", "avif"],
        ["png"] = ["heic", "heif", "avif"],
        ["y4m"] = ["heic", "heif", "avif"]
    };

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var inputExt = job.InputExtension.ToLowerInvariant();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Determine if encoding or decoding
        var isDecoding = IsHeifFormat(inputExt) && !IsHeifFormat(outputExt);
        var isEncoding = !IsHeifFormat(inputExt) && IsHeifFormat(outputExt);

        if (isDecoding)
        {
            // heif-convert decodes HEIF to other formats
            // Quality for JPEG output
            if (outputExt is "jpg" or "jpeg")
            {
                var quality = GetJpegQuality(options.Quality);
                args.AddRange(["-q", quality.ToString()]);
            }

            // Input and output
            args.Add(job.InputPath);
            args.Add(job.OutputPath);
        }
        else if (isEncoding)
        {
            // heif-enc encodes to HEIF
            // We need to use heif-enc instead
            // Note: BuildArguments returns args for heif-enc when encoding

            // Quality
            var quality = GetHeifQuality(options.Quality);
            args.AddRange(["-q", quality.ToString()]);

            // Lossless mode
            if (options.Quality == QualityPreset.Lossless)
            {
                args.Add("-L");
            }

            // AVIF output
            if (outputExt == "avif")
            {
                args.AddRange(["-A"]); // Use AV1 encoder
            }

            // Thumbnail generation
            if (options.Image.Width.HasValue && options.Image.Width.Value <= 256)
            {
                args.Add("-t"); // Create thumbnail
            }

            // Output file
            args.AddRange(["-o", job.OutputPath]);

            // Input file
            args.Add(job.InputPath);
        }

        return [.. args];
    }

    protected override string GetExecutablePath()
    {
        var inputExt = ""; // We'll determine this dynamically
        
        // For encoding, use heif-enc; for decoding, use heif-convert
        // Default to heif-convert for detection
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
            var heifPath = Path.Combine(programFiles, "libheif", "bin", exeName);
            if (File.Exists(heifPath))
                return heifPath;
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
        // Override to use correct executable for encoding vs decoding
        var inputExt = job.InputExtension.ToLowerInvariant();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        if (!IsHeifFormat(inputExt) && IsHeifFormat(outputExt))
        {
            // Encoding - need to use heif-enc
            return await ConvertWithEncoderAsync(job, progress, cancellationToken);
        }

        // Decoding - use base implementation with heif-convert
        return await base.ConvertAsync(job, progress, cancellationToken);
    }

    private async Task<ConversionResult> ConvertWithEncoderAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        // Use heif-enc for encoding
        var originalExecutable = ExecutableName;
        
        var encoderName = OperatingSystem.IsWindows() ? "heif-enc.exe" : "heif-enc";
        var encoderPath = Path.Combine(ToolsBasePath, "bin", encoderName);
        
        // Try to find encoder in PATH if not in tools
        if (!File.Exists(encoderPath))
        {
            var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
            foreach (var dir in pathDirs)
            {
                var fullPath = Path.Combine(dir, encoderName);
                if (File.Exists(fullPath))
                {
                    encoderPath = fullPath;
                    break;
                }
            }
        }

        if (!File.Exists(encoderPath))
        {
            return ConversionResult.Failed(job, 
                "heif-enc not found. Please install libheif with encoding support.", 
                TimeSpan.Zero);
        }

        // Build encoder-specific arguments
        var args = BuildArguments(job, job.Options);
        
        // Execute with encoder
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var warnings = new List<string>();

        try
        {
            progress?.Report(ConversionProgress.Indeterminate("Encoding to HEIF...", ConversionStage.Initializing));

            var result = await ExecuteProcessAsync(
                encoderPath,
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
                result.ErrorMessage ?? "HEIF encoding failed", 
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

    private static bool IsHeifFormat(string ext) => ext switch
    {
        "heic" or "heif" or "heics" or "heifs" or "hif" or "avif" => true,
        _ => false
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

    private static int GetHeifQuality(QualityPreset preset) => preset switch
    {
        QualityPreset.Lowest => 30,
        QualityPreset.Low => 45,
        QualityPreset.Medium => 60,
        QualityPreset.High => 75,
        QualityPreset.Highest => 90,
        QualityPreset.Lossless => 100,
        _ => 75
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // libheif tools can output progress as fraction
        var match = ProgressRegex().Match(line);
        if (match.Success)
        {
            var current = int.Parse(match.Groups[1].Value);
            var total = int.Parse(match.Groups[2].Value);
            var percent = total > 0 ? (double)current / total * 100 : 0;

            return new ConversionProgress
            {
                Percent = percent,
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing frame {current}/{total}",
                RawOutput = line
            };
        }

        // Check for warnings
        if (line.Contains("warning", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Stage = ConversionStage.Encoding,
                StatusMessage = line.Trim(),
                RawOutput = line
            };
        }

        return null;
    }
}
