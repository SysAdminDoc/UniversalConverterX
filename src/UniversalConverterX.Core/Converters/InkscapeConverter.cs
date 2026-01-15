using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Inkscape converter for vector graphics (7 input → 17 output formats)
/// </summary>
public class InkscapeConverter : BaseConverterStrategy
{
    public InkscapeConverter(string toolsBasePath, ILogger<InkscapeConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "inkscape";
    public override string Name => "Inkscape";
    public override int Priority => 95; // High priority for vector formats
    public override string ExecutableName => "inkscape";

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        "svg", "svgz", "ai", "cdr", "vsd", "wmf", "emf", "eps", "pdf", "dxf"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Vector outputs
        "svg", "svgz", "eps", "pdf", "emf", "wmf", "dxf",
        
        // Raster outputs
        "png", "jpg", "jpeg", "tiff", "bmp", "gif", "webp", "ico"
    ];

    #endregion

    protected override string GetExecutablePath()
    {
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var paths = new[]
            {
                Path.Combine(programFiles, "Inkscape", "bin", "inkscape.exe"),
                Path.Combine(programFiles + " (x86)", "Inkscape", "bin", "inkscape.exe"),
                Path.Combine(ToolsBasePath, "bin", "inkscape.exe"),
            };

            foreach (var path in paths)
            {
                if (File.Exists(path))
                    return path;
            }
        }
        else if (OperatingSystem.IsMacOS())
        {
            var paths = new[]
            {
                "/Applications/Inkscape.app/Contents/MacOS/inkscape",
                Path.Combine(ToolsBasePath, "bin", "inkscape")
            };

            foreach (var path in paths)
            {
                if (File.Exists(path))
                    return path;
            }
        }
        else
        {
            var paths = new[]
            {
                "/usr/bin/inkscape",
                Path.Combine(ToolsBasePath, "bin", "inkscape")
            };

            foreach (var path in paths)
            {
                if (File.Exists(path))
                    return path;
            }
        }

        return base.GetExecutablePath();
    }

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();

        // Input file
        args.Add(job.InputPath);

        // Output format and file
        var outputType = GetOutputType(job.OutputExtension);
        args.AddRange(["--export-type", outputType]);
        args.AddRange(["--export-filename", job.OutputPath]);

        // For raster outputs, add DPI and size options
        if (IsRasterFormat(job.OutputExtension))
        {
            var dpi = options.Image.Dpi ?? 96;
            args.AddRange(["--export-dpi", dpi.ToString()]);

            if (options.Image.Width.HasValue)
            {
                args.AddRange(["--export-width", options.Image.Width.Value.ToString()]);
            }

            if (options.Image.Height.HasValue)
            {
                args.AddRange(["--export-height", options.Image.Height.Value.ToString()]);
            }

            // Background color
            if (!string.IsNullOrEmpty(options.Image.Background))
            {
                args.AddRange(["--export-background", options.Image.Background]);
            }
            else if (job.OutputExtension is "jpg" or "jpeg")
            {
                // JPEG needs background
                args.AddRange(["--export-background", "white"]);
            }
        }

        // PDF-specific options
        if (job.OutputExtension == "pdf")
        {
            args.Add("--export-pdf-version=1.5");
        }

        // Custom arguments
        args.AddRange(options.CustomArguments);

        return [.. args];
    }

    private static string GetOutputType(string extension) => extension switch
    {
        "svg" => "svg",
        "svgz" => "svgz",
        "png" => "png",
        "jpg" or "jpeg" => "jpg",
        "pdf" => "pdf",
        "eps" => "eps",
        "emf" => "emf",
        "wmf" => "wmf",
        "dxf" => "dxf",
        "tiff" => "tiff",
        "bmp" => "bmp",
        "gif" => "gif",
        "webp" => "webp",
        "ico" => "ico",
        _ => extension
    };

    private static bool IsRasterFormat(string extension) => extension switch
    {
        "png" or "jpg" or "jpeg" or "tiff" or "bmp" or "gif" or "webp" or "ico" => true,
        _ => false
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        if (line.Contains("Background", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Rendering background...", ConversionStage.Converting);
        }

        if (line.Contains("Rendering", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Rendering...", ConversionStage.Converting);
        }

        if (line.Contains("Exporting", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Exporting...", ConversionStage.Finalizing);
        }

        return null;
    }
}
