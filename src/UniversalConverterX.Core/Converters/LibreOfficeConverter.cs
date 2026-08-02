using System.Collections.Concurrent;
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

    // LibreOffice derives its output filename from the input stem and may
    // overwrite a sibling before UCX gets a chance to relocate it. Keep each
    // invocation isolated until validation has proved that a fresh artifact
    // exists, then promote it to the collision-resolved destination.
    private readonly ConcurrentDictionary<ConversionJob, string> _stagingDirectories = new();

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

    public override async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var stagingDirectory = Path.Combine(
            Path.GetTempPath(),
            $"ucx-libreoffice-{Guid.NewGuid():N}");

        try
        {
            Directory.CreateDirectory(stagingDirectory);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return ConversionResult.Failed(
                job,
                $"Could not create LibreOffice staging directory: {ex.Message}",
                TimeSpan.Zero,
                converter: Id);
        }

        _stagingDirectories[job] = stagingDirectory;
        try
        {
            return await base.ConvertAsync(job, progress, cancellationToken);
        }
        finally
        {
            _stagingDirectories.TryRemove(job, out _);
            try
            {
                if (Directory.Exists(stagingDirectory))
                    Directory.Delete(stagingDirectory, recursive: true);
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger?.LogWarning(ex,
                    "Could not remove LibreOffice staging directory '{Directory}'",
                    stagingDirectory);
            }
        }
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
        var outputDir = _stagingDirectories.TryGetValue(job, out var stagingDirectory)
            ? stagingDirectory
            : Path.GetDirectoryName(job.OutputPath);
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

    protected override ConversionResult? ValidateSuccessfulOutput(
        ConversionJob job,
        TimeSpan duration,
        int exitCode = 0,
        string? standardOutput = null,
        string? standardError = null,
        string? converter = null,
        string? commandLine = null,
        IReadOnlyList<string>? warnings = null)
    {
        // LibreOffice ignores the requested output filename: --convert-to writes
        // <outdir>/<sourceStem>.<ext>, keyed off the SOURCE file stem. When the
        // target filename differs — collision-avoidance suffixes from
        // UniqueOutputPath, or a filename template — the produced file lands
        // beside the intended path and the base validation (which checks
        // job.OutputPath) wrongly reports a successful conversion as failed.
        // Additionally, LibreOffice writes the *filter's native* extension, not
        // necessarily the requested one (requesting .jpeg yields .jpg, .text
        // yields .txt), so an exact-extension match alone can miss the file.
        var hasStagingDirectory = _stagingDirectories.TryGetValue(job, out var stagingDirectory);
        var producedPath = FindProducedOutput(
            job,
            duration,
            hasStagingDirectory ? stagingDirectory : Path.GetDirectoryName(job.OutputPath));

        // A direct converter invocation can legitimately write a custom output
        // filename rather than LibreOffice's source-stem filename. It is still
        // required to be a fresh file and never the input itself.
        if (producedPath is null
            && !hasStagingDirectory
            && IsFreshProduct(job.OutputPath, job, duration))
        {
            producedPath = job.OutputPath;
        }

        // In the normal path the staged directory is the only trusted source.
        // This also prevents a stale final output from turning a zero-output,
        // exit-code-zero soffice run into a false success.
        if (producedPath is null)
        {
            return MissingOutput(
                job, duration, exitCode, standardOutput, standardError,
                converter, commandLine, warnings,
                hasStagingDirectory
                    ? "LibreOffice completed without creating a fresh staged output."
                    : "LibreOffice completed without creating a fresh output.");
        }

        // Relocate the produced file to the requested path. The final move is
        // the first operation allowed to touch the user's output directory.
        try
        {
            if (!string.Equals(
                    Path.GetFullPath(producedPath),
                    Path.GetFullPath(job.OutputPath),
                    StringComparison.OrdinalIgnoreCase))
            {
                var outputExists = File.Exists(job.OutputPath);
                if (outputExists && !job.Options.OverwriteExisting)
                {
                    return MissingOutput(
                        job, duration, exitCode, standardOutput, standardError,
                        converter, commandLine, warnings,
                        "LibreOffice produced an output, but the requested destination appeared during conversion and overwrite is disabled.");
                }

                File.Move(producedPath, job.OutputPath, overwrite: outputExists);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger?.LogWarning(ex,
                "Could not relocate LibreOffice output to '{Output}'", job.OutputPath);
            return MissingOutput(
                job, duration, exitCode, standardOutput, standardError,
                converter, commandLine, warnings,
                $"Could not finalize LibreOffice output: {ex.Message}");
        }

        return base.ValidateSuccessfulOutput(
            job, duration, exitCode, standardOutput, standardError,
            converter, commandLine, warnings);
    }

    /// <summary>
    /// Requested-extension → filter's native extension(s). LibreOffice writes
    /// the filter's own extension, so a job asking for one of these lands as
    /// the aliased extension beside the requested path.
    /// </summary>
    private static readonly Dictionary<string, string[]> _extensionAliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["jpeg"] = ["jpg"],
        ["jpg"] = ["jpeg"],
        ["tif"] = ["tiff"],
        ["tiff"] = ["tif"],
        ["htm"] = ["html"],
        ["html"] = ["htm"],
        ["text"] = ["txt"],
    };

    /// <summary>
    /// Locates the file LibreOffice actually produced for this job, accounting
    /// for both the collision-suffix/template case (same stem, requested
    /// extension) and the native-extension-alias case (e.g. .jpeg → .jpg).
    /// Only considers files freshly written during this conversion and never
    /// the input file, so a stale same-stem file is not picked up.
    /// </summary>
    private static string? FindProducedOutput(
        ConversionJob job,
        TimeSpan duration,
        string? outputDirectory)
    {
        var searchDir = string.IsNullOrEmpty(outputDirectory) ? "." : outputDirectory;
        var sourceStem = Path.GetFileNameWithoutExtension(job.InputPath);
        var requestedExt = Path.GetExtension(job.OutputPath).TrimStart('.');
        var freshAfter = GetFreshAfter(job, duration);

        // 1. Exact extension, the source stem (collision suffix / template case).
        var exact = Path.Combine(searchDir, sourceStem + Path.GetExtension(job.OutputPath));
        if (IsFreshProduct(exact, job, freshAfter))
            return exact;

        // 2. Native-extension alias. Only fall through to a filesystem scan when
        //    the requested extension actually has a known LibreOffice alias.
        if (!_extensionAliases.TryGetValue(requestedExt, out var aliases))
            return null;
        if (!Directory.Exists(searchDir))
            return null;

        foreach (var alias in aliases)
        {
            var candidate = Path.Combine(searchDir, sourceStem + "." + alias);
            if (IsFreshProduct(candidate, job, freshAfter))
                return candidate;
        }

        return null;
    }

    private static bool IsFreshProduct(string candidate, ConversionJob job, TimeSpan duration)
    {
        return IsFreshProduct(
            candidate,
            job,
            GetFreshAfter(job, duration));
    }

    private static DateTime GetFreshAfter(ConversionJob job, TimeSpan duration)
    {
        // Prefer the actual process start when available. Deriving the start
        // only from elapsed duration would eventually re-admit very old files
        // after a sufficiently long conversion.
        var startedAt = job.StartedAt ?? DateTime.UtcNow - duration;
        return startedAt - TimeSpan.FromMinutes(1);
    }

    private static bool IsFreshProduct(
        string candidate,
        ConversionJob job,
        DateTime freshAfter)
    {
        if (!File.Exists(candidate))
            return false;

        try
        {
            return !string.Equals(
                       Path.GetFullPath(candidate),
                       Path.GetFullPath(job.InputPath),
                       StringComparison.OrdinalIgnoreCase)
                && File.GetLastWriteTimeUtc(candidate) >= freshAfter;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    private static ConversionResult MissingOutput(
        ConversionJob job,
        TimeSpan duration,
        int exitCode,
        string? standardOutput,
        string? standardError,
        string? converter,
        string? commandLine,
        IReadOnlyList<string>? warnings,
        string reason)
    {
        job.Status = ConversionStatus.Failed;
        job.OutputFileSize = 0;
        return ConversionResult.Failed(
            job,
            $"{reason} Expected output: {job.OutputPath}",
            duration,
            exitCode,
            standardOutput,
            standardError,
            converter,
            commandLine,
            warnings);
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
