using System.ComponentModel;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Console.Commands;

/// <summary>
/// Offline "best format for this file and target" advisor. Deterministic and
/// fully local — no network, no telemetry.
/// </summary>
public class RecommendCommand : Command<RecommendCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<FILE>")]
        [Description("File (or extension) to get a format recommendation for.")]
        public string FilePath { get; set; } = "";

        [CommandOption("-t|--target <TARGET>")]
        [Description("Delivery target: web, apple, android, discord, email, archive, editing.")]
        public string Target { get; set; } = "web";
    }

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        if (!TryParseTarget(settings.Target, out var target))
        {
            AnsiConsole.MarkupLine(
                $"[red]Error:[/] Unknown target '{Markup.Escape(settings.Target)}'. " +
                "Use one of: web, apple, android, discord, email, archive, editing.");
            return 1;
        }

        var recommendation = FormatRecommender.Recommend(settings.FilePath, target);

        var table = new Table { Border = TableBorder.Rounded };
        table.AddColumn("Property");
        table.AddColumn("Value");
        table.AddRow("Source", Markup.Escape(settings.FilePath));
        table.AddRow("Target", target.ToString());
        table.AddRow("Container", Markup.Escape(recommendation.Container));
        if (!string.IsNullOrEmpty(recommendation.VideoCodec))
            table.AddRow("Video codec", Markup.Escape(recommendation.VideoCodec));
        if (!string.IsNullOrEmpty(recommendation.AudioCodec))
            table.AddRow("Audio codec", Markup.Escape(recommendation.AudioCodec));
        table.AddRow("Lossless", recommendation.Lossless ? "yes" : "no");
        table.AddRow("Why", Markup.Escape(recommendation.Rationale));

        AnsiConsole.Write(table);
        return 0;
    }

    private static bool TryParseTarget(string value, out RecommendationTarget target) =>
        Enum.TryParse(value?.Trim(), ignoreCase: true, out target)
            && Enum.IsDefined(target);
}
