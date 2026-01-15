using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// LibreOffice converter for office document formats (41 input → 22 output formats)
/// Uses LibreOffice in headless mode for conversion
/// </summary>
public class LibreOfficeConverter : BaseConverterStrategy
{
    public LibreOfficeConverter(string toolsBasePath, ILogger<LibreOfficeConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "libreoffice";
    public override string Name => "LibreOffice";
    public override int Priority => 70;
    public override string ExecutableName => "soffice";

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => _formatMappings;

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Word processing
        "doc", "docx", "docm", "dot", "dotx", "dotm", "odt", "ott", "rtf", "txt",
        "wps", "wpd", "lwp", "wri", "sdw", "sxw", "vor", "xml",
        
        // Spreadsheets
        "xls", "xlsx", "xlsm", "xlsb", "xlt", "xltx", "xltm", "ods", "ots",
        "csv", "tsv", "dif", "slk", "sdc", "sxc", "dbf", "wk1", "wks",
        
        // Presentations
        "ppt", "pptx", "pptm", "pot", "potx", "potm", "pps", "ppsx", "ppsm",
        "odp", "otp", "sdd", "sxi", "sti",
        
        // Other
        "html", "htm", "mht", "mhtml", "fodp", "fods", "fodt"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Word processing
        "doc", "docx", "odt", "rtf", "txt", "pdf", "html", "epub",
        
        // Spreadsheets
        "xls", "xlsx", "ods", "csv", "pdf", "html",
        
        // Presentations
        "ppt", "pptx", "odp", "pdf", "html", "swf",
        
        // Images (from documents)
        "png", "jpg", "gif", "bmp", "svg"
    ];

    private static readonly Dictionary<string, HashSet<string>> _formatMappings = new()
    {
        // Word processor documents
        ["doc"] = ["docx", "odt", "rtf", "txt", "pdf", "html", "epub"],
        ["docx"] = ["doc", "odt", "rtf", "txt", "pdf", "html", "epub"],
        ["odt"] = ["doc", "docx", "rtf", "txt", "pdf", "html", "epub"],
        ["rtf"] = ["doc", "docx", "odt", "txt", "pdf", "html"],

        // Spreadsheets
        ["xls"] = ["xlsx", "ods", "csv", "pdf", "html"],
        ["xlsx"] = ["xls", "ods", "csv", "pdf", "html"],
        ["ods"] = ["xls", "xlsx", "csv", "pdf", "html"],
        ["csv"] = ["xls", "xlsx", "ods", "pdf", "html"],

        // Presentations
        ["ppt"] = ["pptx", "odp", "pdf", "html", "png", "jpg", "gif", "svg"],
        ["pptx"] = ["ppt", "odp", "pdf", "html", "png", "jpg", "gif", "svg"],
        ["odp"] = ["ppt", "pptx", "pdf", "html", "png", "jpg", "gif", "svg"]
    };

    #endregion

    protected override string GetExecutablePath()
    {
        // LibreOffice has different executable names on different platforms
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var paths = new[]
            {
                Path.Combine(programFiles, "LibreOffice", "program", "soffice.exe"),
                Path.Combine(programFiles + " (x86)", "LibreOffice", "program", "soffice.exe"),
                Path.Combine(ToolsBasePath, "bin", "LibreOffice", "program", "soffice.exe"),
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
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                Path.Combine(ToolsBasePath, "bin", "soffice")
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
                "/usr/bin/soffice",
                "/usr/bin/libreoffice",
                Path.Combine(ToolsBasePath, "bin", "soffice")
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

        // Headless mode
        args.Add("--headless");
        args.Add("--invisible");
        args.Add("--nologo");
        args.Add("--nofirststartwizard");

        // Convert to filter
        var filter = GetOutputFilter(job.InputExtension, job.OutputExtension);
        args.Add($"--convert-to");
        args.Add(filter);

        // Output directory
        var outputDir = Path.GetDirectoryName(job.OutputPath);
        if (!string.IsNullOrEmpty(outputDir))
        {
            args.Add("--outdir");
            args.Add(outputDir);
        }

        // Input file
        args.Add(job.InputPath);

        return [.. args];
    }

    private static string GetOutputFilter(string inputExt, string outputExt)
    {
        // LibreOffice uses format:filter syntax
        return outputExt switch
        {
            // Document outputs
            "pdf" => "pdf",
            "docx" => "docx",
            "doc" => "doc",
            "odt" => "odt",
            "rtf" => "rtf",
            "txt" => "txt:Text",
            "html" => "html",
            "epub" => "epub",

            // Spreadsheet outputs
            "xlsx" => "xlsx",
            "xls" => "xls",
            "ods" => "ods",
            "csv" => "csv:Text - txt - csv (StarCalc)",

            // Presentation outputs
            "pptx" => "pptx",
            "ppt" => "ppt",
            "odp" => "odp",

            // Image outputs (for presentations)
            "png" => "png",
            "jpg" or "jpeg" => "jpg",
            "gif" => "gif",
            "svg" => "svg",
            "bmp" => "bmp",

            _ => outputExt
        };
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        // LibreOffice doesn't output progress, conversion is typically quick
        if (string.IsNullOrWhiteSpace(line))
            return null;

        if (line.Contains("Loading", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Loading document...", ConversionStage.Analyzing);
        }
        if (line.Contains("convert", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Converting...", ConversionStage.Converting);
        }

        return null;
    }

    public override ValidationResult ValidateJob(ConversionJob job)
    {
        var baseResult = base.ValidateJob(job);
        if (!baseResult.IsValid)
            return baseResult;

        // Check if the specific conversion path is supported
        if (_formatMappings.TryGetValue(job.InputExtension, out var outputs))
        {
            if (!outputs.Contains(job.OutputExtension))
            {
                return ValidationResult.Fail(
                    $"LibreOffice cannot convert {job.InputExtension} to {job.OutputExtension}");
            }
        }

        return ValidationResult.Success;
    }
}
