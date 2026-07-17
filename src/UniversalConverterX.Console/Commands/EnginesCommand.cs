using System.ComponentModel;
using System.Text.Json;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Commands;

/// <summary>Lists the shared engine catalogue used by every UCX surface.</summary>
public sealed class EnginesCommand : Command<EnginesCommand.Settings>
{
    public sealed class Settings : CommandSettings
    {
        [CommandOption("--json")]
        [Description("Write machine-readable JSON instead of a table.")]
        public bool Json { get; set; }

        [CommandOption("--available")]
        [Description("Show only engines whose frozen executable is installed.")]
        public bool AvailableOnly { get; set; }
    }

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        var entries = SidecarCatalog.Discover()
            .Where(entry => !settings.AvailableOnly || entry.Available)
            .ToList();

        if (settings.Json)
        {
            var catalogue = new List<object>
            {
                new
                {
                    name = "converter",
                    kind = "native",
                    available = true,
                    executable_path = Environment.ProcessPath,
                    manifest_path = (string?)null,
                    tool_directory = AppContext.BaseDirectory,
                },
            };
            catalogue.AddRange(entries.Select(entry => (object)new
            {
                name = entry.Name,
                kind = "sidecar",
                available = entry.Available,
                executable_path = entry.ExecutablePath,
                manifest_path = entry.ManifestPath,
                tool_directory = entry.ToolDirectory,
            }));
            System.Console.WriteLine(JsonSerializer.Serialize(catalogue, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            }));
            return 0;
        }

        var table = new Table().AddColumns("Engine", "Installed", "Manifest", "Executable");
        table.AddRow("converter", "yes", "native", Environment.ProcessPath ?? "ucx");
        foreach (var entry in entries)
        {
            table.AddRow(
                Markup.Escape(entry.Name),
                entry.Available ? "yes" : "no",
                entry.ManifestPath is null ? "no" : "yes",
                Markup.Escape(entry.ExecutablePath ?? "not built"));
        }
        AnsiConsole.Write(table);
        return 0;
    }
}
