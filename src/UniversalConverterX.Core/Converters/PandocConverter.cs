using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Pandoc converter for document formats (43 input → 65 output formats)
/// </summary>
public class PandocConverter : BaseConverterStrategy
{
    public PandocConverter(string toolsBasePath, ILogger<PandocConverter>? logger = null) 
        : base(toolsBasePath, logger) { }

    public override string Id => "pandoc";
    public override string Name => "Pandoc";
    public override int Priority => 80;
    public override string ExecutableName => "pandoc";

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Markup
        "md", "markdown", "html", "htm", "xhtml", "xml", "tex", "latex",
        "rst", "textile", "org", "mediawiki", "twiki", "tikiwiki",
        "creole", "jira", "dokuwiki", "muse", "t2t", "txt2tags",
        
        // Office formats
        "docx", "odt", "rtf", "epub", "fb2",
        
        // Data formats
        "json", "csv", "tsv",
        
        // Other
        "ipynb", "man", "opml", "haddock", "native", "biblatex", "bibtex"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Markup
        "md", "markdown", "html", "html5", "htm", "xhtml", "xml", 
        "tex", "latex", "context", "rst", "textile", "org", "asciidoc",
        "mediawiki", "dokuwiki", "jira", "zimwiki", "muse", "plain",
        
        // Office/Document formats
        "docx", "odt", "rtf", "epub", "epub2", "epub3", "fb2", "pdf",
        
        // Presentation
        "pptx", "beamer", "revealjs", "s5", "slidy", "slideous", "dzslides",
        
        // eBook formats
        "icml", "opml",
        
        // Data formats
        "json",
        
        // Other
        "ipynb", "man", "ms", "texinfo", "tei", "native", "chunkedhtml"
    ];

    // Format aliases for Pandoc
    private static readonly Dictionary<string, string> _formatAliases = new()
    {
        ["md"] = "markdown",
        ["htm"] = "html",
        ["tex"] = "latex"
    };

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var doc = options.Document;

        // Input format (auto-detect or explicit)
        var inputFormat = GetPandocFormat(job.InputExtension);
        args.AddRange(["-f", inputFormat]);

        // Output format
        var outputFormat = GetPandocFormat(job.OutputExtension);
        args.AddRange(["-t", outputFormat]);

        // Input file
        args.Add(job.InputPath);

        // Output file
        args.AddRange(["-o", job.OutputPath]);

        // Standalone document
        if (doc.Standalone)
        {
            args.Add("-s");
        }

        // PDF engine
        if (job.OutputExtension == "pdf")
        {
            var engine = doc.PdfEngine ?? "xelatex";
            args.AddRange(["--pdf-engine", engine]);
        }

        // Table of contents
        if (doc.TableOfContents)
        {
            args.Add("--toc");
        }

        // Number sections
        if (doc.NumberSections)
        {
            args.Add("--number-sections");
        }

        // CSS file
        if (!string.IsNullOrEmpty(doc.CssFile) && File.Exists(doc.CssFile))
        {
            args.AddRange(["-c", doc.CssFile]);
        }

        // Template
        if (!string.IsNullOrEmpty(doc.Template) && File.Exists(doc.Template))
        {
            args.AddRange(["--template", doc.Template]);
        }

        // Page size and margins for PDF
        if (job.OutputExtension == "pdf")
        {
            if (!string.IsNullOrEmpty(doc.PageSize))
            {
                args.AddRange(["-V", $"papersize:{doc.PageSize}"]);
            }

            if (!string.IsNullOrEmpty(doc.Margin))
            {
                args.AddRange(["-V", $"geometry:margin={doc.Margin}"]);
            }

            if (!string.IsNullOrEmpty(doc.Orientation))
            {
                args.AddRange(["-V", $"geometry:{doc.Orientation}"]);
            }
        }

        // Metadata preservation
        if (options.PreserveMetadata)
        {
            args.Add("--extract-media=.");
        }

        // Format-specific options
        AddFormatSpecificOptions(args, job.OutputExtension, options);

        // Custom arguments
        args.AddRange(options.CustomArguments);

        return [.. args];
    }

    private static string GetPandocFormat(string extension)
    {
        var ext = extension.ToLowerInvariant();
        
        if (_formatAliases.TryGetValue(ext, out var alias))
            return alias;

        return ext switch
        {
            "docx" => "docx",
            "odt" => "odt",
            "rtf" => "rtf",
            "html" or "htm" => "html",
            "xhtml" => "html",
            "epub" => "epub",
            "pdf" => "pdf",
            "pptx" => "pptx",
            "tex" or "latex" => "latex",
            "rst" => "rst",
            "org" => "org",
            "txt" => "plain",
            "json" => "json",
            "ipynb" => "ipynb",
            "fb2" => "fb2",
            "man" => "man",
            _ => ext
        };
    }

    private static void AddFormatSpecificOptions(List<string> args, string outputExt, ConversionOptions options)
    {
        switch (outputExt)
        {
            case "html" or "htm" or "html5":
                args.Add("--embed-resources");
                args.Add("--mathml");
                break;

            case "docx":
                // Reference doc for styling if available
                break;

            case "epub" or "epub2" or "epub3":
                args.AddRange(["--epub-chapter-level", "2"]);
                break;

            case "revealjs" or "slidy" or "s5" or "slideous" or "dzslides":
                args.Add("--slide-level=2");
                break;

            case "latex" or "tex" or "beamer":
                args.Add("--listings");
                break;
        }
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        // Pandoc doesn't output progress, but we can detect stages
        if (string.IsNullOrWhiteSpace(line))
            return null;

        if (line.Contains("Parsing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Parsing document...", ConversionStage.Analyzing);
        }
        if (line.Contains("Writing", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Writing output...", ConversionStage.Finalizing);
        }
        if (line.Contains("Running", StringComparison.OrdinalIgnoreCase))
        {
            return ConversionProgress.Indeterminate("Processing...", ConversionStage.Converting);
        }

        return null;
    }
}
