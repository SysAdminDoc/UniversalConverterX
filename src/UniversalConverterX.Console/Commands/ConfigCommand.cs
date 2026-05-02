using System.ComponentModel;
using System.Text.Json;
using System.Text.Json.Serialization;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;

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
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX",
        "settings.json");

    private static readonly string LegacyConfigPath = Path.Combine(
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

        AddConfigRow(table, "tools-path", config.ToolsBasePath);
        AddConfigRow(table, "search-system-tools", config.SearchSystemTools.ToString());
        AddConfigRow(table, "max-parallel", config.MaxParallelConversions.ToString());
        AddConfigRow(table, "default-timeout", config.DefaultTimeout.ToString());
        AddConfigRow(table, "hardware-accel", config.EnableHardwareAcceleration.ToString());
        AddConfigRow(table, "temp-directory", config.TempDirectory);
        AddConfigRow(table, "keep-failed-output", config.KeepFailedOutput.ToString());
        AddConfigRow(table, "verbose-logging", config.VerboseLogging.ToString());
        AddConfigRow(table, "auto-download-tools", config.AutoDownloadTools.ToString());
        AddConfigRow(table, "default-quality", config.DefaultQuality.ToString());
        AddConfigRow(table, "preserve-metadata", config.PreserveMetadataByDefault.ToString());

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
                    config.MaxParallelConversions = ParsePositiveInt(value, "max-parallel");
                    break;

                case "defaulttimeout":
                    config.DefaultTimeout = ParsePositiveTimeSpan(value, "default-timeout");
                    break;

                case "hardwareaccel":
                    config.EnableHardwareAcceleration = bool.Parse(value);
                    break;

                case "searchsystemtools":
                    config.SearchSystemTools = bool.Parse(value);
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
                    if (!Enum.TryParse<QualityPreset>(value, ignoreCase: true, out var quality))
                        throw new ArgumentException($"default-quality must be one of: {string.Join(", ", Enum.GetNames<QualityPreset>())}");
                    config.DefaultQuality = quality;
                    break;

                case "preservemetadata":
                    config.PreserveMetadataByDefault = bool.Parse(value);
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
        var reset = false;

        if (File.Exists(ConfigPath))
        {
            File.Delete(ConfigPath);
            reset = true;
        }

        if (File.Exists(LegacyConfigPath))
        {
            File.Delete(LegacyConfigPath);
            reset = true;
        }

        if (reset)
        {
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
        AnsiConsole.MarkupLine("  tools-path, search-system-tools, max-parallel, default-timeout, hardware-accel,");
        AnsiConsole.MarkupLine("  temp-directory, keep-failed-output, verbose-logging,");
        AnsiConsole.MarkupLine("  auto-download-tools, default-quality, preserve-metadata");
    }

    private static ConverterXOptions LoadConfig()
    {
        var path = File.Exists(ConfigPath) ? ConfigPath : LegacyConfigPath;
        if (File.Exists(path))
        {
            try
            {
                var json = File.ReadAllText(path);
                // Route through Core's migration-aware loader so legacy
                // settings files (no SchemaVersion field, future renames)
                // get the same upgrade treatment as the GUI path. We do NOT
                // persist the migration back from the CLI — `ucx config`
                // is allowed to inspect read-only files and shouldn't write
                // through silently.
                return ConverterXOptions.LoadFromJson(json, persistMigrated: false);
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

        var json = JsonSerializer.Serialize(config, CreateJsonOptions());
        File.WriteAllText(ConfigPath, json);
    }

    private static void AddConfigRow(Table table, string setting, string value)
    {
        table.Rows.Add(
        [
            new Text(setting),
            new Text(value)
        ]);
    }

    private static int ParsePositiveInt(string value, string key)
    {
        if (!int.TryParse(value, out var parsed) || parsed < 1)
            throw new ArgumentException($"{key} must be a positive integer");

        return parsed;
    }

    private static TimeSpan ParsePositiveTimeSpan(string value, string key)
    {
        if (!TimeSpan.TryParse(value, out var parsed) || parsed <= TimeSpan.Zero)
            throw new ArgumentException($"{key} must be a positive time span");

        return parsed;
    }

    private static JsonSerializerOptions CreateJsonOptions() => new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() }
    };
}
