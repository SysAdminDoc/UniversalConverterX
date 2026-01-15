using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Ghostscript converter for PDF and PostScript processing
/// </summary>
public partial class GhostscriptConverter : BaseConverterStrategy
{
    public GhostscriptConverter(string toolsBasePath, ILogger<GhostscriptConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "ghostscript";
    public override string Name => "Ghostscript";
    public override int Priority => 75;
    public override string ExecutableName => OperatingSystem.IsWindows() ? "gswin64c" : "gs";

    [GeneratedRegex(@"Page\s+(\d+)", RegexOptions.Compiled)]
    private static partial Regex PageRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    private int _totalPages;

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        "pdf", "ps", "eps", "ai"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Document outputs
        "pdf",
        
        // Image outputs (rasterization)
        "png", "jpg", "jpeg", "tiff", "bmp", "ppm", "pgm", "pbm"
    ];

    #endregion

    protected override string GetExecutablePath()
    {
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            
            // Search for any Ghostscript version
            var gsDir = Path.Combine(programFiles, "gs");
            if (Directory.Exists(gsDir))
            {
                var versionDirs = Directory.GetDirectories(gsDir, "gs*")
                    .OrderByDescending(d => d)
                    .ToList();

                foreach (var dir in versionDirs)
                {
                    var exe64 = Path.Combine(dir, "bin", "gswin64c.exe");
                    if (File.Exists(exe64)) return exe64;

                    var exe32 = Path.Combine(dir, "bin", "gswin32c.exe");
                    if (File.Exists(exe32)) return exe32;
                }
            }

            // Check tools directory
            var toolPath = Path.Combine(ToolsBasePath, "bin", "gswin64c.exe");
            if (File.Exists(toolPath)) return toolPath;
        }
        else
        {
            var paths = new[]
            {
                "/usr/bin/gs",
                "/usr/local/bin/gs",
                Path.Combine(ToolsBasePath, "bin", "gs")
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

        // Quiet mode
        args.AddRange(["-q", "-dNOPAUSE", "-dBATCH"]);

        // Safety
        args.Add("-dSAFER");

        // Output device based on format
        var device = GetOutputDevice(job.OutputExtension, options);
        args.AddRange(["-sDEVICE=" + device]);

        // Resolution
        var dpi = options.Image.Dpi ?? 150;
        args.Add($"-r{dpi}");

        // PDF-specific options
        if (job.OutputExtension == "pdf")
        {
            // PDF quality/compression settings
            var pdfSettings = options.Quality switch
            {
                QualityPreset.Lowest => "/screen",
                QualityPreset.Low => "/ebook",
                QualityPreset.Medium => "/printer",
                QualityPreset.High or QualityPreset.Highest => "/prepress",
                QualityPreset.Lossless => "/default",
                _ => "/printer"
            };
            args.Add($"-dPDFSETTINGS={pdfSettings}");
            args.Add("-dCompatibilityLevel=1.5");
        }

        // Image-specific options
        if (IsImageFormat(job.OutputExtension))
        {
            // Anti-aliasing
            args.AddRange(["-dTextAlphaBits=4", "-dGraphicsAlphaBits=4"]);
        }

        // JPEG quality
        if (job.OutputExtension is "jpg" or "jpeg")
        {
            var quality = options.Image.Quality ?? 85;
            args.Add($"-dJPEGQ={quality}");
        }

        // Output file
        args.Add($"-sOutputFile={job.OutputPath}");

        // Custom arguments
        args.AddRange(options.CustomArguments);

        // Input file
        args.Add(job.InputPath);

        return [.. args];
    }

    private static string GetOutputDevice(string extension, ConversionOptions options) => extension switch
    {
        "pdf" => "pdfwrite",
        "png" => options.Image.BitDepth == 8 ? "png256" : "png16m",
        "jpg" or "jpeg" => "jpeg",
        "tiff" => "tiff24nc",
        "bmp" => "bmp16m",
        "ppm" => "ppmraw",
        "pgm" => "pgmraw",
        "pbm" => "pbmraw",
        _ => "pdfwrite"
    };

    private static bool IsImageFormat(string extension) => extension switch
    {
        "png" or "jpg" or "jpeg" or "tiff" or "bmp" or "ppm" or "pgm" or "pbm" => true,
        _ => false
    };

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        var pageMatch = PageRegex().Match(line);
        if (pageMatch.Success)
        {
            var currentPage = int.Parse(pageMatch.Groups[1].Value);
            
            if (_totalPages > 0)
            {
                var percent = (double)currentPage / _totalPages * 100;
                return ConversionProgress.FromPercent(percent, $"Processing page {currentPage}/{_totalPages}");
            }
            
            return ConversionProgress.Indeterminate($"Processing page {currentPage}...", ConversionStage.Converting);
        }

        if (line.Contains("Processing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Processing...", ConversionStage.Converting);
        }

        return null;
    }
}
