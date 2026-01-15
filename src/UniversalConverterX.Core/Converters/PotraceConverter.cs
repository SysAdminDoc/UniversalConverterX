using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Potrace converter for tracing raster images to vector formats.
/// Converts bitmap images (PBM, PGM, PPM, BMP) into scalable vector graphics.
/// </summary>
public partial class PotraceConverter : BaseConverterStrategy
{
    public PotraceConverter(string toolsBasePath, ILogger<PotraceConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "potrace";
    public override string Name => "Potrace";
    public override int Priority => 88; // Good for raster-to-vector specifically
    public override string ExecutableName => "potrace";

    [GeneratedRegex(@"Page\s+(\d+)", RegexOptions.Compiled)]
    private static partial Regex PageRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    // Potrace primarily works with PBM (bitmap) format
    // mkbitmap can preprocess other formats
    private static readonly HashSet<string> _inputFormats =
    [
        // Native potrace formats
        "pbm", "pgm", "ppm", "pnm",
        
        // BMP support
        "bmp",
        
        // With mkbitmap preprocessing
        "png", "jpg", "jpeg", "gif", "tiff", "tif"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Vector formats
        "svg", "eps", "ps", "pdf",
        
        // DXF for CAD
        "dxf",
        
        // GeoJSON for mapping
        "geojson",
        
        // PGM grayscale (for intermediate processing)
        "pgm",
        
        // XFig format
        "fig"
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Output format backend
        var backend = GetBackendFlag(outputExt);
        if (!string.IsNullOrEmpty(backend))
            args.Add(backend);

        // Tracing algorithm options
        args.AddRange(GetTracingOptions(options));

        // Output options based on format
        switch (outputExt)
        {
            case "svg":
                // SVG-specific options
                if (options.Image.Width.HasValue && options.Image.Height.HasValue)
                {
                    args.AddRange(["--width", $"{options.Image.Width}pt"]);
                    args.AddRange(["--height", $"{options.Image.Height}pt"]);
                }
                args.Add("--flat"); // Flat SVG without groups
                args.Add("--tight"); // Tight bounding box
                break;

            case "eps" or "ps":
                // PostScript options
                if (options.Image.Width.HasValue && options.Image.Height.HasValue)
                {
                    args.AddRange(["--width", $"{options.Image.Width}pt"]);
                    args.AddRange(["--height", $"{options.Image.Height}pt"]);
                }
                break;

            case "pdf":
                // PDF options
                if (options.Document.PageSize != null)
                {
                    args.AddRange(["--pagesize", options.Document.PageSize.ToLowerInvariant()]);
                }
                break;

            case "dxf":
                // DXF for CAD applications
                break;

            case "geojson":
                // GeoJSON for mapping applications
                break;
        }

        // Color handling
        if (!string.IsNullOrEmpty(options.Image.Background))
        {
            // Potrace uses hexadecimal color values
            var colorHex = options.Image.Background.TrimStart('#');
            args.AddRange(["--fillcolor", $"#{colorHex}"]);
        }

        // Output file
        args.AddRange(["-o", job.OutputPath]);

        // Input file (must be last)
        args.Add(job.InputPath);

        return [.. args];
    }

    private static string GetBackendFlag(string outputExt) => outputExt switch
    {
        "svg" => "-s",
        "eps" => "-e",
        "ps" => "-p",
        "pdf" => "-b", // PDF backend
        "dxf" => "-b", // DXF backend
        "geojson" => "-b", // GeoJSON backend
        "pgm" => "-g",
        "fig" => "-b", // XFig backend
        _ => "-s" // Default to SVG
    };

    private static string[] GetTracingOptions(ConversionOptions options)
    {
        var args = new List<string>();

        // Turnpolicy - how to resolve ambiguous pixels
        args.AddRange(["-z", "black"]); // Default: prefer black over white

        // Turd size - suppress speckles of this size
        var turdSize = options.Quality switch
        {
            QualityPreset.Lowest => 10,
            QualityPreset.Low => 5,
            QualityPreset.Medium => 2,
            QualityPreset.High => 1,
            QualityPreset.Highest => 0,
            QualityPreset.Lossless => 0,
            _ => 2
        };
        args.AddRange(["-t", turdSize.ToString()]);

        // Alpha max - corner threshold parameter
        var alphaMax = options.Quality switch
        {
            QualityPreset.Lowest => 0.0,   // More corners
            QualityPreset.Low => 0.5,
            QualityPreset.Medium => 1.0,
            QualityPreset.High => 1.2,
            QualityPreset.Highest => 1.34,  // Smoother curves
            QualityPreset.Lossless => 1.34,
            _ => 1.0
        };
        args.AddRange(["-a", alphaMax.ToString("F2")]);

        // Optimize curves
        if (options.Quality >= QualityPreset.Medium)
        {
            args.Add("-O"); // Enable curve optimization
            
            // Tolerance for optimization
            var tolerance = options.Quality switch
            {
                QualityPreset.High => 0.1,
                QualityPreset.Highest => 0.05,
                QualityPreset.Lossless => 0.02,
                _ => 0.2
            };
            args.AddRange(["-T", tolerance.ToString("F2")]);
        }
        else
        {
            args.Add("-n"); // Disable curve optimization for speed
        }

        // Resolution
        if (options.Image.Dpi.HasValue)
        {
            args.AddRange(["-r", options.Image.Dpi.Value.ToString()]);
        }
        else
        {
            args.AddRange(["-r", "72"]); // Default 72 DPI
        }

        return [.. args];
    }

    public override async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var inputExt = job.InputExtension.ToLowerInvariant();

        // If input is not a native potrace format, preprocess with mkbitmap
        if (!IsNativeFormat(inputExt))
        {
            return await ConvertWithPreprocessingAsync(job, progress, cancellationToken);
        }

        return await base.ConvertAsync(job, progress, cancellationToken);
    }

    private async Task<ConversionResult> ConvertWithPreprocessingAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var warnings = new List<string>();
        string? tempPbmFile = null;

        try
        {
            // Step 1: Convert to PBM using mkbitmap
            progress?.Report(ConversionProgress.Indeterminate("Preprocessing image...", ConversionStage.Initializing));

            var mkbitmapName = OperatingSystem.IsWindows() ? "mkbitmap.exe" : "mkbitmap";
            var mkbitmapPath = FindExecutable(mkbitmapName);

            if (mkbitmapPath == null)
            {
                // Try using ImageMagick as fallback for preprocessing
                return await ConvertWithImageMagickPreprocessAsync(job, progress, cancellationToken);
            }

            tempPbmFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid()}.pbm");

            // mkbitmap arguments
            var mkbitmapArgs = new[]
            {
                "-f", "4",      // Highpass filter
                "-s", "2",      // Scale up 2x for better tracing
                "-t", "0.48",   // Threshold
                "-o", tempPbmFile,
                job.InputPath
            };

            var preprocessResult = await ExecuteProcessAsync(
                mkbitmapPath,
                mkbitmapArgs,
                job,
                null,
                warnings,
                cancellationToken);

            if (!preprocessResult.Success)
            {
                return ConversionResult.Failed(job,
                    $"Preprocessing failed: {preprocessResult.ErrorMessage}",
                    stopwatch.Elapsed);
            }

            // Step 2: Run potrace on the preprocessed PBM
            progress?.Report(new ConversionProgress
            {
                Percent = 50,
                Stage = ConversionStage.Encoding,
                StatusMessage = "Tracing image..."
            });

            // Create a temporary job with the PBM input
            var tracingJob = new ConversionJob
            {
                InputPath = tempPbmFile,
                OutputPath = job.OutputPath,
                Options = job.Options
            };

            var potraceArgs = BuildArguments(tracingJob, job.Options);
            var executablePath = GetExecutablePath();

            var traceResult = await ExecuteProcessAsync(
                executablePath,
                potraceArgs,
                job,
                progress,
                warnings,
                cancellationToken);

            stopwatch.Stop();

            if (traceResult.Success)
            {
                job.Status = ConversionStatus.Completed;
                job.OutputFileSize = File.Exists(job.OutputPath) ? new FileInfo(job.OutputPath).Length : 0;

                return ConversionResult.Succeeded(job, job.OutputPath, stopwatch.Elapsed, Id,
                    warnings: warnings);
            }

            return ConversionResult.Failed(job,
                traceResult.ErrorMessage ?? "Tracing failed",
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
        finally
        {
            // Clean up temp file
            if (tempPbmFile != null && File.Exists(tempPbmFile))
            {
                try { File.Delete(tempPbmFile); } catch { }
            }
        }
    }

    private async Task<ConversionResult> ConvertWithImageMagickPreprocessAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        // Fallback: use ImageMagick to convert to PBM first
        var magickName = OperatingSystem.IsWindows() ? "magick.exe" : "magick";
        var magickPath = FindExecutable(magickName);

        if (magickPath == null)
        {
            return ConversionResult.Failed(job,
                "Neither mkbitmap nor ImageMagick found. Please install one of these tools.",
                TimeSpan.Zero);
        }

        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var warnings = new List<string>();
        string? tempPbmFile = null;

        try
        {
            progress?.Report(ConversionProgress.Indeterminate("Converting to bitmap...", ConversionStage.Initializing));

            tempPbmFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid()}.pbm");

            // ImageMagick conversion to PBM
            var magickArgs = new[]
            {
                job.InputPath,
                "-colorspace", "Gray",
                "-threshold", "50%",
                tempPbmFile
            };

            var preprocessResult = await ExecuteProcessAsync(
                magickPath,
                magickArgs,
                job,
                null,
                warnings,
                cancellationToken);

            if (!preprocessResult.Success)
            {
                return ConversionResult.Failed(job,
                    $"Image preprocessing failed: {preprocessResult.ErrorMessage}",
                    stopwatch.Elapsed);
            }

            // Run potrace
            progress?.Report(new ConversionProgress
            {
                Percent = 50,
                Stage = ConversionStage.Encoding,
                StatusMessage = "Tracing vectors..."
            });

            var tracingJob = new ConversionJob
            {
                InputPath = tempPbmFile,
                OutputPath = job.OutputPath,
                Options = job.Options
            };

            var potraceArgs = BuildArguments(tracingJob, job.Options);
            var executablePath = GetExecutablePath();

            var traceResult = await ExecuteProcessAsync(
                executablePath,
                potraceArgs,
                job,
                progress,
                warnings,
                cancellationToken);

            stopwatch.Stop();

            if (traceResult.Success)
            {
                job.Status = ConversionStatus.Completed;
                job.OutputFileSize = File.Exists(job.OutputPath) ? new FileInfo(job.OutputPath).Length : 0;

                return ConversionResult.Succeeded(job, job.OutputPath, stopwatch.Elapsed, Id,
                    warnings: warnings);
            }

            return ConversionResult.Failed(job,
                traceResult.ErrorMessage ?? "Tracing failed",
                stopwatch.Elapsed);
        }
        finally
        {
            if (tempPbmFile != null && File.Exists(tempPbmFile))
            {
                try { File.Delete(tempPbmFile); } catch { }
            }
        }
    }

    private string? FindExecutable(string name)
    {
        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", name);
        if (File.Exists(toolPath))
            return toolPath;

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, name);
            if (File.Exists(fullPath))
                return fullPath;
        }

        return null;
    }

    private static bool IsNativeFormat(string ext) => ext switch
    {
        "pbm" or "pgm" or "ppm" or "pnm" or "bmp" => true,
        _ => false
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // Potrace outputs page progress for multi-page documents
        var pageMatch = PageRegex().Match(line);
        if (pageMatch.Success)
        {
            var page = int.Parse(pageMatch.Groups[1].Value);
            return new ConversionProgress
            {
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing page {page}...",
                RawOutput = line
            };
        }

        // Check for completion
        if (line.Contains("wrote", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 100,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Completed",
                RawOutput = line
            };
        }

        return null;
    }
}
