using System.ComponentModel;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Console.Commands;

/// <summary>
/// List the hardware video encoders (NVENC, AMD AMF, Intel Quick Sync, VAAPI, …)
/// that the local FFmpeg build exposes.
/// </summary>
public class EncodersCommand : Command<EncodersCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandOption("--tools-path <PATH>")]
        [Description("Path to converter tools (where ffmpeg lives).")]
        public string? ToolsPath { get; set; }
    }

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();
        var ffmpegPath = new FFmpegConverter(toolsPath).ResolveExecutablePath();

        if (ffmpegPath is null)
        {
            AnsiConsole.MarkupLine("[yellow]FFmpeg was not found.[/] Install it with [green]ucx tools download ffmpeg[/].");
            return 1;
        }

        var encoders = FfmpegEncoderProbe.Probe(ffmpegPath);
        if (encoders.Count == 0)
        {
            AnsiConsole.MarkupLine("[yellow]No hardware video encoders detected in this FFmpeg build.[/]");
            return 0;
        }

        var table = new Table { Border = TableBorder.Rounded };
        table.AddColumn("Encoder");
        table.AddColumn("Codec");
        table.AddColumn("Vendor");
        foreach (var encoder in encoders)
            table.AddRow(Markup.Escape(encoder.Name), Markup.Escape(encoder.Codec), encoder.Vendor.ToString());

        AnsiConsole.MarkupLine("[green]Hardware video encoders:[/]");
        AnsiConsole.Write(table);
        return 0;
    }

    private static string GetDefaultToolsPath()
    {
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UniversalConverterX", "tools"),
        };

        foreach (var location in locations)
        {
            if (Directory.Exists(location))
                return location;
        }

        return locations[0];
    }
}
