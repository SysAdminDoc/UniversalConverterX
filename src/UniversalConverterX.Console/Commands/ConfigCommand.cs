using System.ComponentModel;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Configuration;
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

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        var config = CliConfiguration.Get(context);
        return settings.Action.ToLowerInvariant() switch
        {
            "show" => ShowConfig(config),
            "set" => SetConfig(settings.Key, settings.Value, config),
            "reset" => ResetConfig(),
            "path" => ShowConfigPath(),
            _ => InvalidAction(settings.Action)
        };
    }

    private int ShowConfig(ConverterXOptions config)
    {
        AnsiConsole.MarkupLine("[green]Current Configuration:[/]");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Setting");
        table.AddColumn("Value");

        AddConfigRow(table, "tools-path", config.ToolsBasePath);
        AddConfigRow(table, "search-system-tools", config.SearchSystemTools.ToString());
        AddConfigRow(table, "overwrite", config.OverwriteBehavior.ToString());
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
        AnsiConsole.MarkupLine($"[dim]Config file: {CliConfiguration.SettingsPath}[/]");

        return 0;
    }

    private int SetConfig(string? key, string? value, ConverterXOptions config)
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

        try
        {
            switch (key.ToLowerInvariant().Replace("-", "").Replace("_", ""))
            {
                case "toolspath":
                    if (!CliConfiguration.TryNormalizeToolsPath(value, out var normalizedToolsPath, out var toolsPathError))
                        throw new ArgumentException(toolsPathError);

                    value = normalizedToolsPath;
                    if (!Directory.Exists(normalizedToolsPath))
                    {
                        AnsiConsole.MarkupLine($"[yellow]Warning:[/] Directory does not exist: {Markup.Escape(normalizedToolsPath)}");
                    }
                    config.ToolsBasePath = normalizedToolsPath;
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

                case "overwrite" or "overwritebehavior":
                    if (!Enum.TryParse<OverwriteBehavior>(value, ignoreCase: true, out var overwrite))
                        throw new ArgumentException(
                            $"overwrite must be one of: {string.Join(", ", Enum.GetNames<OverwriteBehavior>())}");
                    config.OverwriteBehavior = overwrite;
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
                    AnsiConsole.MarkupLine($"[red]Error:[/] Unknown configuration key: {Markup.Escape(key)}");
                    ShowAvailableKeys();
                    return 1;
            }

            SaveConfig(config);
            AnsiConsole.MarkupLine($"[green]✓[/] Set [cyan]{Markup.Escape(key)}[/] = [yellow]{Markup.Escape(value)}[/]");
            return 0;
        }
        catch (Exception ex)
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Invalid value: {Markup.Escape(ex.Message)}");
            return 1;
        }
    }

    private int ResetConfig()
    {
        var reset = false;

        if (File.Exists(CliConfiguration.SettingsPath))
        {
            File.Delete(CliConfiguration.SettingsPath);
            reset = true;
        }

        if (File.Exists(CliConfiguration.LegacySettingsPath))
        {
            File.Delete(CliConfiguration.LegacySettingsPath);
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
        AnsiConsole.MarkupLine($"[green]Configuration file:[/] {CliConfiguration.SettingsPath}");
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
        AnsiConsole.MarkupLine("  tools-path, search-system-tools, overwrite, max-parallel, default-timeout, hardware-accel,");
        AnsiConsole.MarkupLine("  temp-directory, keep-failed-output, verbose-logging,");
        AnsiConsole.MarkupLine("  auto-download-tools, default-quality, preserve-metadata");
    }

    private static void SaveConfig(ConverterXOptions config)
    {
        config.Save();
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

}
