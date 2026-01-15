using System.ComponentModel;
using System.Text.Json;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.Console.Commands;

public class ConfigCommand : Command<ConfigCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<ACTION>")]
        [Description("Action: show, set, reset")]
        public string Action { get; set; } = "show";

        [CommandArgument(1, "[KEY]")]
        [Description("Configuration key (for set)")]
        public string? Key { get; set; }

        [CommandArgument(2, "[VALUE]")]
        [Description("Configuration value (for set)")]
        public string? Value { get; set; }
    }

    private static readonly string ConfigPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "UniversalConverterX",
        "config.json");

    public override int Execute(CommandContext context, Settings settings)
    {
        return settings.Action.ToLowerInvariant() switch
        {
            "show" => ShowConfig(),
            "set" => SetConfig(settings.Key, settings.Value),
            "reset" => ResetConfig(),
            "path" => ShowConfigPath(),
            _ => InvalidAction(settings.Action)
        };
    }

    private int ShowConfig()
    {
        var config = LoadConfig();

        AnsiConsole.MarkupLine("[green]Current Configuration:[/]");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Setting");
        table.AddColumn("Value");

        table.AddRow("tools-path", config.ToolsBasePath);
        table.AddRow("max-parallel", config.MaxConcurrentConversions.ToString());
        table.AddRow("default-timeout", config.DefaultTimeout.ToString());
        table.AddRow("hardware-accel", config.EnableHardwareAcceleration.ToString());
        table.AddRow("temp-directory", config.TempDirectory);
        table.AddRow("keep-failed-output", config.KeepFailedOutput.ToString());
        table.AddRow("verbose-logging", config.VerboseLogging.ToString());
        table.AddRow("auto-download-tools", config.AutoDownloadTools.ToString());
        table.AddRow("default-quality", config.DefaultQuality);
        table.AddRow("preserve-metadata", config.PreserveMetadata.ToString());

        AnsiConsole.Write(table);

        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine($"[dim]Config file: {ConfigPath}[/]");

        return 0;
    }

    private int SetConfig(string? key, string? value)
    {
        if (string.IsNullOrEmpty(key))
        {
            AnsiConsole.MarkupLine("[red]Error:[/] Key is required for set action");
            return 1;
        }

        if (string.IsNullOrEmpty(value))
        {
            AnsiConsole.MarkupLine("[red]Error:[/] Value is required for set action");
            return 1;
        }

        var config = LoadConfig();

        try
        {
            switch (key.ToLowerInvariant().Replace("-", "").Replace("_", ""))
            {
                case "toolspath":
                    if (!Directory.Exists(value))
                    {
                        AnsiConsole.MarkupLine($"[yellow]Warning:[/] Directory does not exist: {value}");
                    }
                    config.ToolsBasePath = value;
                    break;

                case "maxparallel":
                    config.MaxConcurrentConversions = int.Parse(value);
                    break;

                case "defaulttimeout":
                    config.DefaultTimeout = TimeSpan.Parse(value);
                    break;

                case "hardwareaccel":
                    config.EnableHardwareAcceleration = bool.Parse(value);
                    break;

                case "tempdirectory":
                    config.TempDirectory = value;
                    break;

                case "keepfailedoutput":
                    config.KeepFailedOutput = bool.Parse(value);
                    break;

                case "verboselogging":
                    config.VerboseLogging = bool.Parse(value);
                    break;

                case "autodownloadtools":
                    config.AutoDownloadTools = bool.Parse(value);
                    break;

                case "defaultquality":
                    config.DefaultQuality = value;
                    break;

                case "preservemetadata":
                    config.PreserveMetadata = bool.Parse(value);
                    break;

                default:
                    AnsiConsole.MarkupLine($"[red]Error:[/] Unknown configuration key: {key}");
                    ShowAvailableKeys();
                    return 1;
            }

            SaveConfig(config);
            AnsiConsole.MarkupLine($"[green]✓[/] Set [cyan]{key}[/] = [yellow]{value}[/]");
            return 0;
        }
        catch (Exception ex)
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Invalid value: {ex.Message}");
            return 1;
        }
    }

    private int ResetConfig()
    {
        if (File.Exists(ConfigPath))
        {
            File.Delete(ConfigPath);
            AnsiConsole.MarkupLine("[green]✓[/] Configuration reset to defaults");
        }
        else
        {
            AnsiConsole.MarkupLine("[yellow]Configuration was already at defaults[/]");
        }

        return 0;
    }

    private int ShowConfigPath()
    {
        AnsiConsole.MarkupLine($"[green]Configuration file:[/] {ConfigPath}");
        return 0;
    }

    private static int InvalidAction(string action)
    {
        AnsiConsole.MarkupLine($"[red]Unknown action:[/] {action}");
        AnsiConsole.MarkupLine("[dim]Valid actions: show, set, reset, path[/]");
        return 1;
    }

    private static void ShowAvailableKeys()
    {
        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine("[dim]Available keys:[/]");
        AnsiConsole.MarkupLine("  tools-path, max-parallel, default-timeout, hardware-accel,");
        AnsiConsole.MarkupLine("  temp-directory, keep-failed-output, verbose-logging,");
        AnsiConsole.MarkupLine("  auto-download-tools, default-quality, preserve-metadata");
    }

    private static ConverterXOptions LoadConfig()
    {
        if (File.Exists(ConfigPath))
        {
            try
            {
                var json = File.ReadAllText(ConfigPath);
                return JsonSerializer.Deserialize<ConverterXOptions>(json) ?? new ConverterXOptions();
            }
            catch
            {
                return new ConverterXOptions();
            }
        }

        return new ConverterXOptions();
    }

    private static void SaveConfig(ConverterXOptions config)
    {
        var dir = Path.GetDirectoryName(ConfigPath);
        if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
        {
            Directory.CreateDirectory(dir);
        }

        var json = JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(ConfigPath, json);
    }
}
