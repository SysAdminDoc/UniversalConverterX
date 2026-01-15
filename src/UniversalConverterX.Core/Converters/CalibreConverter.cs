using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Calibre converter for ebook formats (26 input → 19 output formats)
/// Uses ebook-convert CLI tool from Calibre
/// </summary>
public class CalibreConverter : BaseConverterStrategy
{
    public CalibreConverter(string toolsBasePath, ILogger<CalibreConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "calibre";
    public override string Name => "Calibre";
    public override int Priority => 85; // Higher than Pandoc for ebook formats
    public override string ExecutableName => "ebook-convert";

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Ebook formats
        "epub", "mobi", "azw", "azw3", "azw4", "kf8", "kfx",
        "fb2", "fbz", "lit", "lrf", "pdb", "pml", "rb", "snb", "tcr",
        
        // Document formats
        "pdf", "doc", "docx", "odt", "rtf", "txt", "html", "htm",
        "xhtml", "cbz", "cbr", "cbc", "chm"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Ebook formats
        "epub", "mobi", "azw3", "fb2", "lit", "lrf", "pdb", "pml",
        "rb", "snb", "tcr",
        
        // Document formats
        "pdf", "docx", "odt", "rtf", "txt", "html", "htmlz",
        "txtz", "zip"
    ];

    #endregion

    protected override string GetExecutablePath()
    {
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var paths = new[]
            {
                Path.Combine(programFiles, "Calibre2", "ebook-convert.exe"),
                Path.Combine(programFiles + " (x86)", "Calibre2", "ebook-convert.exe"),
                Path.Combine(ToolsBasePath, "bin", "Calibre", "ebook-convert.exe"),
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
                "/Applications/calibre.app/Contents/MacOS/ebook-convert",
                Path.Combine(ToolsBasePath, "bin", "ebook-convert")
            };

            foreach (var path in paths)
            {
                if (File.Exists(path))
                    return path;
            }
        }
        else // Linux
        {
            var paths = new[]
            {
                "/usr/bin/ebook-convert",
                Path.Combine(ToolsBasePath, "bin", "ebook-convert")
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

        // Output file
        args.Add(job.OutputPath);

        // Format-specific options
        AddFormatSpecificOptions(args, job.OutputExtension, options);

        // Metadata preservation
        if (options.PreserveMetadata)
        {
            args.Add("--dont-split-on-page-breaks");
        }

        // Custom arguments
        args.AddRange(options.CustomArguments);

        return [.. args];
    }

    private static void AddFormatSpecificOptions(List<string> args, string outputExt, ConversionOptions options)
    {
        switch (outputExt)
        {
            case "epub":
                args.Add("--epub-version=3");
                args.Add("--no-default-epub-cover");
                break;

            case "mobi" or "azw3":
                args.Add("--output-profile=kindle_pw3");
                break;

            case "pdf":
                args.Add("--pdf-page-numbers");
                args.Add("--paper-size=letter");
                if (!string.IsNullOrEmpty(options.Document.PageSize))
                {
                    args.Add($"--paper-size={options.Document.PageSize}");
                }
                if (!string.IsNullOrEmpty(options.Document.Margin))
                {
                    args.Add($"--pdf-page-margin-left={options.Document.Margin}");
                    args.Add($"--pdf-page-margin-right={options.Document.Margin}");
                    args.Add($"--pdf-page-margin-top={options.Document.Margin}");
                    args.Add($"--pdf-page-margin-bottom={options.Document.Margin}");
                }
                break;

            case "html" or "htmlz":
                args.Add("--max-levels=0");
                break;

            case "txt" or "txtz":
                args.Add("--txt-output-encoding=utf-8");
                break;

            case "docx":
                args.Add("--docx-page-size=letter");
                break;
        }
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // Calibre outputs percentage
        if (line.Contains('%'))
        {
            // Try to extract percentage like "45%" or "45.5%"
            var percentIndex = line.IndexOf('%');
            if (percentIndex > 0)
            {
                var startIndex = percentIndex - 1;
                while (startIndex > 0 && (char.IsDigit(line[startIndex - 1]) || line[startIndex - 1] == '.'))
                {
                    startIndex--;
                }
                
                var percentStr = line[startIndex..percentIndex];
                if (double.TryParse(percentStr, out var percent))
                {
                    return ConversionProgress.FromPercent(percent);
                }
            }
        }

        // Stage detection
        if (line.Contains("Loading", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Parsing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Loading ebook...", ConversionStage.Analyzing);
        }

        if (line.Contains("Converting", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Converting...", ConversionStage.Converting);
        }

        if (line.Contains("Creating", StringComparison.OrdinalIgnoreCase) ||
            line.Contains("Writing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Creating output...", ConversionStage.Finalizing);
        }

        return null;
    }
}
