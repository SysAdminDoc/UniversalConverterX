using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// resvg converter for high-quality SVG rendering to raster formats.
/// resvg is a fast, memory-safe SVG rendering library with excellent CSS support.
/// Produces higher quality output than many other SVG renderers.
/// </summary>
public partial class ResvgConverter : BaseConverterStrategy
{
    public ResvgConverter(string toolsBasePath, ILogger<ResvgConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "resvg";
    public override string Name => "resvg";
    public override int Priority => 97; // Very high priority for SVG rendering
    public override string ExecutableName => "resvg";

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        "svg", "svgz" // SVG and compressed SVG
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        "png", "pdf", "eps", "svg" // PNG, PDF, EPS, and optimized SVG output
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Size/Scale options
        if (options.Image.Width.HasValue && options.Image.Height.HasValue)
        {
            // Specific dimensions
            args.AddRange(["--width", options.Image.Width.Value.ToString()]);
            args.AddRange(["--height", options.Image.Height.Value.ToString()]);
        }
        else if (options.Image.Width.HasValue)
        {
            // Width only, maintain aspect ratio
            args.AddRange(["--width", options.Image.Width.Value.ToString()]);
        }
        else if (options.Image.Height.HasValue)
        {
            // Height only, maintain aspect ratio
            args.AddRange(["--height", options.Image.Height.Value.ToString()]);
        }
        else if (options.Image.Dpi.HasValue)
        {
            // DPI-based sizing
            args.AddRange(["--dpi", options.Image.Dpi.Value.ToString()]);
        }
        else
        {
            // Default DPI based on quality
            var dpi = GetDefaultDpi(options.Quality);
            args.AddRange(["--dpi", dpi.ToString()]);
        }

        // Background color
        if (!string.IsNullOrEmpty(options.Image.Background))
        {
            var bg = options.Image.Background.TrimStart('#');
            args.AddRange(["--background", bg]);
        }

        // Quality/rendering options
        switch (options.Quality)
        {
            case QualityPreset.Lowest:
            case QualityPreset.Low:
                // Fast rendering, lower quality
                args.Add("--shape-rendering=optimizeSpeed");
                args.Add("--text-rendering=optimizeSpeed");
                args.Add("--image-rendering=optimizeSpeed");
                break;

            case QualityPreset.Medium:
                // Balanced
                args.Add("--shape-rendering=auto");
                args.Add("--text-rendering=auto");
                break;

            case QualityPreset.High:
            case QualityPreset.Highest:
            case QualityPreset.Lossless:
                // High quality rendering
                args.Add("--shape-rendering=geometricPrecision");
                args.Add("--text-rendering=geometricPrecision");
                args.Add("--image-rendering=optimizeQuality");
                break;
        }

        // Font configuration
        // Use system fonts by default
        args.Add("--use-fonts-dir");
        
        if (OperatingSystem.IsWindows())
        {
            var fontsDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Fonts));
            args.Add(fontsDir);
        }
        else if (OperatingSystem.IsLinux())
        {
            args.Add("/usr/share/fonts");
        }
        else if (OperatingSystem.IsMacOS())
        {
            args.Add("/System/Library/Fonts");
        }

        // Default font family (fallback)
        args.AddRange(["--font-family", "Arial"]);
        args.AddRange(["--serif-family", "Times New Roman"]);
        args.AddRange(["--sans-serif-family", "Arial"]);
        args.AddRange(["--cursive-family", "Comic Sans MS"]);
        args.AddRange(["--fantasy-family", "Impact"]);
        args.AddRange(["--monospace-family", "Consolas"]);

        // Language for text shaping
        args.AddRange(["--languages", "en"]);

        // Output format specific options
        switch (outputExt)
        {
            case "png":
                // PNG is the default output
                break;

            case "pdf":
                args.Add("--export-pdf");
                break;

            case "eps":
                args.Add("--export-eps");
                break;

            case "svg":
                // Export simplified/optimized SVG
                args.Add("--export-svg");
                break;
        }

        // Skip invalid elements instead of failing
        args.Add("--skip-system-fonts");

        // Input file
        args.Add(job.InputPath);

        // Output file
        args.Add(job.OutputPath);

        return [.. args];
    }

    private static int GetDefaultDpi(QualityPreset quality) => quality switch
    {
        QualityPreset.Lowest => 72,
        QualityPreset.Low => 96,
        QualityPreset.Medium => 150,
        QualityPreset.High => 300,
        QualityPreset.Highest => 600,
        QualityPreset.Lossless => 600,
        _ => 150
    };

    public override ValidationResult ValidateJob(ConversionJob job)
    {
        var baseResult = base.ValidateJob(job);
        if (!baseResult.IsValid)
            return baseResult;

        var inputExt = job.InputExtension.ToLowerInvariant();
        
        // Validate SVG file
        if (inputExt == "svg")
        {
            try
            {
                // Quick check for valid XML/SVG structure
                var firstBytes = new byte[1024];
                using var stream = File.OpenRead(job.InputPath);
                var bytesRead = stream.Read(firstBytes, 0, firstBytes.Length);
                var header = System.Text.Encoding.UTF8.GetString(firstBytes, 0, bytesRead);

                if (!header.Contains("<svg", StringComparison.OrdinalIgnoreCase) &&
                    !header.Contains("<?xml", StringComparison.OrdinalIgnoreCase))
                {
                    return ValidationResult.Fail("File does not appear to be a valid SVG document");
                }
            }
            catch (Exception ex)
            {
                return ValidationResult.Fail($"Could not validate SVG file: {ex.Message}");
            }
        }
        else if (inputExt == "svgz")
        {
            // SVGZ is gzip-compressed SVG
            try
            {
                using var stream = File.OpenRead(job.InputPath);
                var magic = new byte[2];
                stream.Read(magic, 0, 2);
                
                // Check for gzip magic number
                if (magic[0] != 0x1f || magic[1] != 0x8b)
                {
                    return ValidationResult.Fail("File does not appear to be a valid SVGZ (gzip-compressed SVG)");
                }
            }
            catch (Exception ex)
            {
                return ValidationResult.Fail($"Could not validate SVGZ file: {ex.Message}");
            }
        }

        return ValidationResult.Success;
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // resvg is typically fast and doesn't output progress
        // but we can parse status messages

        if (line.Contains("Loading", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 10,
                Stage = ConversionStage.Initializing,
                StatusMessage = "Loading SVG...",
                RawOutput = line
            };
        }

        if (line.Contains("Parsing", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 30,
                Stage = ConversionStage.Initializing,
                StatusMessage = "Parsing document...",
                RawOutput = line
            };
        }

        if (line.Contains("Rendering", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 60,
                Stage = ConversionStage.Encoding,
                StatusMessage = "Rendering...",
                RawOutput = line
            };
        }

        if (line.Contains("Saving", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Writing", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 90,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Saving output...",
                RawOutput = line
            };
        }

        // Check for warnings about missing fonts
        if (line.Contains("font", StringComparison.OrdinalIgnoreCase) &&
            line.Contains("not found", StringComparison.OrdinalIgnoreCase))
        {
            Logger?.LogWarning("Font warning: {Line}", line.Trim());
            return new ConversionProgress
            {
                Stage = ConversionStage.Encoding,
                StatusMessage = "Warning: Some fonts not found",
                RawOutput = line
            };
        }

        return null;
    }

    protected override string GetExecutablePath()
    {
        var exeName = OperatingSystem.IsWindows() ? "resvg.exe" : "resvg";

        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", exeName);
        if (File.Exists(toolPath))
            return toolPath;

        // Check common installation paths
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var resvgPath = Path.Combine(programFiles, "resvg", exeName);
            if (File.Exists(resvgPath))
                return resvgPath;

            // Check cargo installation
            var cargoPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".cargo", "bin", exeName);
            if (File.Exists(cargoPath))
                return cargoPath;
        }
        else
        {
            // Unix: check cargo path
            var cargoPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".cargo", "bin", exeName);
            if (File.Exists(cargoPath))
                return cargoPath;
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

    /// <summary>
    /// Gets SVG metadata without full conversion
    /// </summary>
    public async Task<SvgMetadata?> GetSvgMetadataAsync(string svgPath, CancellationToken cancellationToken = default)
    {
        if (!File.Exists(svgPath))
            return null;

        try
        {
            var executablePath = GetExecutablePath();
            if (!File.Exists(executablePath))
                return null;

            // Use resvg to query SVG size
            using var process = new System.Diagnostics.Process
            {
                StartInfo = new System.Diagnostics.ProcessStartInfo
                {
                    FileName = executablePath,
                    Arguments = $"--query-all \"{svgPath}\"",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                }
            };

            process.Start();
            var output = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken);

            if (process.ExitCode != 0)
                return null;

            // Parse output for dimensions
            var lines = output.Split('\n');
            foreach (var line in lines)
            {
                if (line.Contains("svg") && line.Contains(','))
                {
                    var parts = line.Split(',');
                    if (parts.Length >= 4 &&
                        double.TryParse(parts[2].Trim(), out var width) &&
                        double.TryParse(parts[3].Trim(), out var height))
                    {
                        return new SvgMetadata(width, height);
                    }
                }
            }

            // Fallback: parse SVG directly
            return await ParseSvgDirectlyAsync(svgPath, cancellationToken);
        }
        catch
        {
            return null;
        }
    }

    private static async Task<SvgMetadata?> ParseSvgDirectlyAsync(string svgPath, CancellationToken cancellationToken)
    {
        try
        {
            var content = await File.ReadAllTextAsync(svgPath, cancellationToken);
            
            // Try to find width/height attributes
            var widthMatch = Regex.Match(content, @"width\s*=\s*""(\d+(?:\.\d+)?)\s*(px|pt|mm|cm|in)?""", RegexOptions.IgnoreCase);
            var heightMatch = Regex.Match(content, @"height\s*=\s*""(\d+(?:\.\d+)?)\s*(px|pt|mm|cm|in)?""", RegexOptions.IgnoreCase);

            if (widthMatch.Success && heightMatch.Success)
            {
                var width = double.Parse(widthMatch.Groups[1].Value);
                var height = double.Parse(heightMatch.Groups[1].Value);
                
                // Convert to pixels if needed
                var widthUnit = widthMatch.Groups[2].Value.ToLowerInvariant();
                var heightUnit = heightMatch.Groups[2].Value.ToLowerInvariant();
                
                width = ConvertToPixels(width, widthUnit);
                height = ConvertToPixels(height, heightUnit);
                
                return new SvgMetadata(width, height);
            }

            // Try viewBox
            var viewBoxMatch = Regex.Match(content, @"viewBox\s*=\s*""[\d.\s]+\s+[\d.\s]+\s+([\d.]+)\s+([\d.]+)""");
            if (viewBoxMatch.Success)
            {
                var width = double.Parse(viewBoxMatch.Groups[1].Value);
                var height = double.Parse(viewBoxMatch.Groups[2].Value);
                return new SvgMetadata(width, height);
            }

            return null;
        }
        catch
        {
            return null;
        }
    }

    private static double ConvertToPixels(double value, string unit) => unit switch
    {
        "pt" => value * 1.33333,
        "mm" => value * 3.7795,
        "cm" => value * 37.795,
        "in" => value * 96,
        _ => value // px or no unit
    };

    public record SvgMetadata(double Width, double Height);
}
