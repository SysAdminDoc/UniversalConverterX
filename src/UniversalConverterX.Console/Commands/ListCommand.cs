using System.ComponentModel;
using Microsoft.Extensions.Options;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Console.Commands;

public class ListCommand : Command<ListCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<TYPE>")]
        [Description("What to list: formats, converters, or categories")]
        public string Type { get; set; } = "formats";

        [CommandOption("-i|--input <EXT>")]
        [Description("Filter by input format")]
        public string? InputFormat { get; set; }

        [CommandOption("-c|--category <CATEGORY>")]
        [Description("Filter by category: video, audio, image, document, ebook")]
        public string? Category { get; set; }

        [CommandOption("--tools-path <PATH>")]
        [Description("Path to converter tools")]
        public string? ToolsPath { get; set; }
    }

    public override int Execute(CommandContext context, Settings settings)
    {
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();
        var options = Options.Create(new ConverterXOptions { ToolsBasePath = toolsPath });
        var orchestrator = new ConversionOrchestrator(options);

        return settings.Type.ToLowerInvariant() switch
        {
            "formats" => ListFormats(orchestrator, settings),
            "converters" => ListConverters(orchestrator),
            "categories" => ListCategories(),
            _ => InvalidType(settings.Type)
        };
    }

    private int ListFormats(ConversionOrchestrator orchestrator, Settings settings)
    {
        var converters = orchestrator.GetConverters();

        if (!string.IsNullOrEmpty(settings.InputFormat))
        {
            // List output formats for specific input
            var ext = settings.InputFormat.TrimStart('.').ToLowerInvariant();
            var outputs = orchestrator.GetOutputFormatsFor($"file.{ext}");

            if (outputs.Count == 0)
            {
                AnsiConsole.MarkupLine($"[yellow]No output formats available for[/] [cyan]{ext}[/]");
                return 1;
            }

            AnsiConsole.MarkupLine($"[green]Output formats for[/] [cyan]{ext}[/]:");
            AnsiConsole.WriteLine();

            var table = new Table();
            table.Border = TableBorder.Rounded;
            table.AddColumn("Format");
            table.AddColumn("Converter");
            table.AddColumn("Category");

            foreach (var output in outputs.OrderBy(o => o))
            {
                var converter = orchestrator.GetBestConverter(ext, output);
                var category = GetCategory(output);
                table.AddRow(output, converter?.Name ?? "N/A", category);
            }

            AnsiConsole.Write(table);
            AnsiConsole.MarkupLine($"\n[dim]Total: {outputs.Count} formats[/]");
        }
        else
        {
            // List all input formats
            var allInputs = new HashSet<string>();
            foreach (var converter in converters)
            {
                foreach (var format in converter.GetSupportedInputFormats())
                {
                    allInputs.Add(format);
                }
            }

            // Filter by category if specified
            if (!string.IsNullOrEmpty(settings.Category))
            {
                allInputs = allInputs.Where(f => GetCategory(f).Equals(settings.Category, StringComparison.OrdinalIgnoreCase)).ToHashSet();
            }

            AnsiConsole.MarkupLine("[green]Supported input formats:[/]");
            AnsiConsole.WriteLine();

            var grouped = allInputs.GroupBy(GetCategory).OrderBy(g => g.Key);

            foreach (var group in grouped)
            {
                AnsiConsole.MarkupLine($"[cyan]{group.Key}[/]");
                var formats = string.Join(", ", group.OrderBy(f => f));
                AnsiConsole.MarkupLine($"  [dim]{formats}[/]");
                AnsiConsole.WriteLine();
            }

            AnsiConsole.MarkupLine($"[dim]Total: {allInputs.Count} formats[/]");
        }

        return 0;
    }

    private int ListConverters(ConversionOrchestrator orchestrator)
    {
        var converters = orchestrator.GetConverters();

        AnsiConsole.MarkupLine("[green]Available converters:[/]");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("ID");
        table.AddColumn("Name");
        table.AddColumn("Priority");
        table.AddColumn("Input Formats");
        table.AddColumn("Output Formats");

        foreach (var converter in converters)
        {
            var inputCount = converter.GetSupportedInputFormats().Count;
            var outputCount = converter.GetSupportedOutputFormats().Count;

            table.AddRow(
                $"[cyan]{converter.Id}[/]",
                converter.Name,
                converter.Priority.ToString(),
                inputCount.ToString(),
                outputCount.ToString());
        }

        AnsiConsole.Write(table);

        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine("[dim]Use --converter <ID> with the convert command to force a specific converter[/]");

        return 0;
    }

    private static int ListCategories()
    {
        AnsiConsole.MarkupLine("[green]Format categories:[/]");
        AnsiConsole.WriteLine();

        var categories = new[]
        {
            ("Video", "mp4, mkv, avi, mov, webm, flv, wmv, m4v, mpg, mpeg, 3gp, ts"),
            ("Audio", "mp3, wav, flac, aac, ogg, wma, m4a, opus, aiff, ac3"),
            ("Image", "jpg, png, gif, bmp, webp, tiff, ico, heic, avif, psd, svg"),
            ("Document", "pdf, doc, docx, odt, rtf, txt, html, md, tex"),
            ("Ebook", "epub, mobi, azw, azw3, fb2, lit"),
            ("Vector", "svg, eps, ai"),
            ("3D", "obj, fbx, stl, gltf, glb, 3ds, dae"),
            ("Data", "json, xml, yaml, csv, tsv")
        };

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Category");
        table.AddColumn("Common Formats");

        foreach (var (name, formats) in categories)
        {
            table.AddRow($"[cyan]{name}[/]", $"[dim]{formats}[/]");
        }

        AnsiConsole.Write(table);

        return 0;
    }

    private static int InvalidType(string type)
    {
        AnsiConsole.MarkupLine($"[red]Unknown list type:[/] {type}");
        AnsiConsole.MarkupLine("[dim]Valid types: formats, converters, categories[/]");
        return 1;
    }

    private static string GetCategory(string extension) => extension switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "mts" => "Video",

        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or
        "opus" or "aiff" or "ape" or "ac3" => "Audio",

        "jpg" or "jpeg" or "png" or "gif" or "bmp" or "tiff" or "tif" or
        "webp" or "ico" or "heic" or "heif" or "avif" or "jxl" or
        "psd" or "raw" or "cr2" or "nef" => "Image",

        "pdf" or "doc" or "docx" or "odt" or "rtf" or "txt" or
        "html" or "htm" or "md" or "tex" => "Document",

        "epub" or "mobi" or "azw" or "azw3" or "fb2" or "lit" => "Ebook",

        "svg" or "eps" or "ai" => "Vector",

        "obj" or "fbx" or "stl" or "gltf" or "glb" or "3ds" or "dae" => "3D",

        "json" or "xml" or "yaml" or "yml" or "csv" or "tsv" => "Data",

        _ => "Other"
    };

    private static string GetDefaultToolsPath()
    {
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UniversalConverterX", "tools"),
        };

        foreach (var loc in locations)
        {
            if (Directory.Exists(loc))
                return loc;
        }

        return locations[0];
    }
}
