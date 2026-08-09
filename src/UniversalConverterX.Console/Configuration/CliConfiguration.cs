using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.Console.Configuration;

/// <summary>
/// Loads the process-wide CLI configuration once and exposes it through the
/// Spectre command context. Commands may still be instantiated directly by
/// tests or embedding callers, so <see cref="Get"/> has a defensive fallback.
/// </summary>
internal static class CliConfiguration
{
    internal static string SettingsPath { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX",
        "settings.json");

    internal static string LegacySettingsPath { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "UniversalConverterX",
        "config.json");

    internal static ConverterXOptions Load()
    {
        if (!File.Exists(SettingsPath) && File.Exists(LegacySettingsPath))
        {
            try
            {
                return ConverterXOptions.LoadFromJson(
                    File.ReadAllText(LegacySettingsPath),
                    persistMigrated: false);
            }
            catch
            {
                // Fall through to the canonical loader, which returns safe
                // defaults and backs up a corrupt canonical settings file.
            }
        }

        return ConverterXOptions.Load();
    }

    internal static ConverterXOptions Get(CommandContext context) =>
        context.Data as ConverterXOptions ?? Load();
}
