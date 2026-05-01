using System.ComponentModel;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Presets;

namespace UniversalConverterX.Console.Commands;

/// <summary>
/// <c>ucx convert-preset --preset "Name" file1 [file2 ...]</c>
///
/// Designed to be the CLI surface that the right-click shell extension calls.
/// Supports an <c>--input-files PATH</c> long-arg fallback so the shell
/// extension can dump a 1000-file selection to a temp file rather than
/// overflowing the 8 KB Windows command-line limit.
/// </summary>
public class ConvertPresetCommand : Command<ConvertPresetCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandOption("-p|--preset <NAME>")]
        [Description("Preset display name to apply (must match a <Name> in presets/*.preset.xml)")]
        public string? Preset { get; set; }

        [CommandOption("--list")]
        [Description("List discoverable presets and exit (no conversion).")]
        public bool ListOnly { get; set; }

        [CommandOption("--input-files <PATH>")]
        [Description("Path to a UTF-8 text file containing one input path per line. " +
                     "Used by the shell extension to bypass the 8 KB Windows command-line limit.")]
        public string? InputFilesList { get; set; }

        [CommandArgument(0, "[FILES]")]
        [Description("Input files. Can be combined with --input-files (both lists are merged).")]
        public string[] Files { get; set; } = [];
    }

    public override int Execute(CommandContext context, Settings settings)
    {
        var presets = PresetLoader.LoadAll();

        if (settings.ListOnly)
        {
            DumpPresets(presets);
            return 0;
        }

        if (string.IsNullOrWhiteSpace(settings.Preset))
        {
            AnsiConsole.MarkupLine("[red]Missing --preset.[/] Use --list to enumerate presets.");
            return 2;
        }

        var match = presets.FirstOrDefault(p =>
            string.Equals(p.Name, settings.Preset, StringComparison.OrdinalIgnoreCase));
        if (match is null)
        {
            AnsiConsole.MarkupLineInterpolated($"[red]Preset not found:[/] {settings.Preset}");
            AnsiConsole.MarkupLine("[grey]Discoverable presets:[/]");
            DumpPresets(presets);
            return 3;
        }

        var inputs = new List<string>(settings.Files);
        if (!string.IsNullOrWhiteSpace(settings.InputFilesList))
        {
            try
            {
                foreach (var raw in File.ReadAllLines(settings.InputFilesList))
                {
                    var line = raw.Trim();
                    if (line.Length > 0) inputs.Add(line);
                }
            }
            catch (Exception ex)
            {
                AnsiConsole.MarkupLineInterpolated($"[red]Failed to read --input-files {settings.InputFilesList}: {ex.Message}[/]");
                return 4;
            }
        }

        // Filter to existing files only, preserving order, deduping.
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var resolved = new List<string>(inputs.Count);
        foreach (var path in inputs)
        {
            if (string.IsNullOrEmpty(path)) continue;
            try
            {
                var full = Path.GetFullPath(path);
                if (!seen.Add(full)) continue;
                if (File.Exists(full)) resolved.Add(full);
                else AnsiConsole.MarkupLineInterpolated($"[yellow]skip (missing):[/] {full}");
            }
            catch
            {
                AnsiConsole.MarkupLineInterpolated($"[yellow]skip (invalid):[/] {path}");
            }
        }

        if (resolved.Count == 0)
        {
            AnsiConsole.MarkupLine("[red]No valid input files.[/]");
            return 5;
        }

        if (!match.MatchesAll(resolved))
        {
            var msg = $"[yellow]Warning:[/] preset '{match.Name}' lists {match.InputTypes.Count} input "
                    + "extension(s) and not every selected file matches. Running anyway -- the sidecar "
                    + "may reject incompatible inputs.";
            AnsiConsole.MarkupLine(msg);
        }

        AnsiConsole.MarkupLineInterpolated(
            $"[green]Preset:[/] {match.Name} [grey]({match.Engine}, {match.Mode}, {resolved.Count} input(s))[/]");
        return PresetRunner.Run(match, resolved);
    }

    private static void DumpPresets(IReadOnlyList<ConversionPreset> presets)
    {
        if (presets.Count == 0)
        {
            AnsiConsole.MarkupLine("[grey]No presets discovered. " +
                "Drop *.preset.xml files in %LocalAppData%/UniversalConverterX/presets/ " +
                "or %ProgramFiles%/UniversalConverterX/presets/.[/]");
            return;
        }
        var table = new Table().AddColumns("Name", "Folder", "Engine", "Inputs", "Output", "Source");
        foreach (var p in presets.OrderBy(x => x.Folder ?? "").ThenBy(x => x.Name))
        {
            table.AddRow(
                p.Name,
                p.Folder ?? "(root)",
                p.Engine,
                p.InputTypes.Count == 0 ? "*" : string.Join(",", p.InputTypes),
                "." + p.OutputExtension,
                Path.GetFileName(p.SourcePath));
        }
        AnsiConsole.Write(table);
    }
}
