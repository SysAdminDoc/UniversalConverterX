using System.ComponentModel;
using Microsoft.Extensions.Options;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Console.Commands;

public class InfoCommand : AsyncCommand<InfoCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<FILE>")]
        [Description("File to analyze")]
        public string FilePath { get; set; } = "";

        [CommandOption("--tools-path <PATH>")]
        [Description("Path to converter tools")]
        public string? ToolsPath { get; set; }
    }

    public override async Task<int> ExecuteAsync(CommandContext context, Settings settings)
    {
        if (!File.Exists(settings.FilePath))
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] File not found: {settings.FilePath}");
            return 1;
        }

        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();
        var options = Options.Create(new ConverterXOptions { ToolsBasePath = toolsPath });
        var orchestrator = new ConversionOrchestrator(options);

        var fileInfo = new FileInfo(settings.FilePath);
        var format = await orchestrator.DetectFormatAsync(settings.FilePath);
        var availableOutputs = orchestrator.GetOutputFormatsFor(settings.FilePath);

        AnsiConsole.MarkupLine($"[green]File Information:[/] {fileInfo.Name}");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Property");
        table.AddColumn("Value");

        table.AddRow("Path", fileInfo.FullName);
        table.AddRow("Size", FormatSize(fileInfo.Length));
        table.AddRow("Created", fileInfo.CreationTime.ToString("yyyy-MM-dd HH:mm:ss"));
        table.AddRow("Modified", fileInfo.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss"));
        table.AddRow("Extension", fileInfo.Extension.TrimStart('.'));
        table.AddRow("Detected Format", format.Extension);
        table.AddRow("MIME Type", format.MimeType);
        table.AddRow("Category", format.Category.ToString());

        if (!string.IsNullOrEmpty(format.Description))
        {
            table.AddRow("Description", format.Description);
        }

        AnsiConsole.Write(table);

        if (availableOutputs.Count > 0)
        {
            AnsiConsole.WriteLine();
            AnsiConsole.MarkupLine("[green]Available conversions:[/]");
            
            var grouped = availableOutputs.GroupBy(GetCategory).OrderBy(g => g.Key);
            foreach (var group in grouped)
            {
                var formats = string.Join(", ", group.OrderBy(f => f));
                AnsiConsole.MarkupLine($"  [cyan]{group.Key}:[/] [dim]{formats}[/]");
            }
        }
        else
        {
            AnsiConsole.WriteLine();
            AnsiConsole.MarkupLine("[yellow]No conversions available for this format.[/]");
        }

        return 0;
    }

    private static string GetCategory(string extension) => extension switch
    {
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "gif" => "Video",

        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or
        "opus" or "aiff" or "ac3" => "Audio",

        "jpg" or "jpeg" or "png" or "bmp" or "tiff" or "tif" or
        "webp" or "ico" or "heic" or "avif" or "jxl" or
        "psd" => "Image",

        "pdf" or "doc" or "docx" or "odt" or "rtf" or "txt" or
        "html" or "htm" or "md" or "tex" => "Document",

        "epub" or "mobi" or "azw3" or "fb2" => "Ebook",

        "svg" or "eps" => "Vector",

        _ => "Other"
    };

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        int i = 0;
        double size = bytes;

        while (size >= 1024 && i < suffixes.Length - 1)
        {
            size /= 1024;
            i++;
        }

        return $"{size:F2} {suffixes[i]}";
    }

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
