using System.ComponentModel;
using System.Text.Json;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Configuration;
using UniversalConverterX.Console.Presets;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Commands;

/// <summary>Runs any installed sidecar by its catalogue name.</summary>
public sealed class InvokeEngineCommand : Command<InvokeEngineCommand.Settings>
{
    public sealed class Settings : CommandSettings
    {
        [CommandArgument(0, "<ENGINE>")]
        [Description("Engine name from `ucx engines`.")]
        public string Engine { get; set; } = "";

        [CommandOption("--args-json <JSON>")]
        [Description("JSON string array passed verbatim to the engine.")]
        [DefaultValue("[]")]
        public string ArgumentsJson { get; set; } = "[]";

        [CommandOption("--args-file <PATH>")]
        [Description("UTF-8 JSON file containing the argument string array.")]
        public string? ArgumentsFile { get; set; }
    }

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        if (!SidecarCatalog.IsSafeName(settings.Engine))
        {
            AnsiConsole.MarkupLine("[red]Invalid engine name.[/]");
            return 2;
        }
        if (string.Equals(settings.Engine, "converter", StringComparison.OrdinalIgnoreCase))
        {
            AnsiConsole.MarkupLine("[red]Use `ucx convert` for the native converter engine.[/]");
            return 2;
        }

        string payload;
        try
        {
            payload = string.IsNullOrWhiteSpace(settings.ArgumentsFile)
                ? settings.ArgumentsJson
                : File.ReadAllText(settings.ArgumentsFile);
        }
        catch (Exception ex)
        {
            AnsiConsole.MarkupLineInterpolated($"[red]Could not read arguments:[/] {ex.Message}");
            return 2;
        }

        string[]? arguments;
        try { arguments = JsonSerializer.Deserialize<string[]>(payload); }
        catch (JsonException ex)
        {
            AnsiConsole.MarkupLineInterpolated($"[red]Invalid --args-json:[/] {ex.Message}");
            return 2;
        }
        if (arguments is null || arguments.Any(argument => argument is null))
        {
            AnsiConsole.MarkupLine("[red]Arguments must be a JSON array of strings.[/]");
            return 2;
        }

        return PresetRunner.RunRaw(settings.Engine, arguments, CliConfiguration.Get(context));
    }
}
