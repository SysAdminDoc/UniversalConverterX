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

    /// <summary>
    /// Resolves the command-line spelling of a tools directory. Windows users
    /// commonly pass cmd-style <c>%VAR%</c> values even when invoking UCX from
    /// PowerShell; .NET does not expand those values until asked to do so.
    /// Leaving an unresolved token in the result is unsafe because a relative
    /// token such as <c>%TEMP%\tools</c> would otherwise become a real folder
    /// below the current working directory.
    /// </summary>
    internal static bool TryNormalizeToolsPath(
        string? rawPath,
        out string normalizedPath,
        out string error)
    {
        normalizedPath = string.Empty;
        error = string.Empty;

        if (string.IsNullOrWhiteSpace(rawPath))
        {
            error = "the tools path must not be empty";
            return false;
        }

        var expandedPath = Environment.ExpandEnvironmentVariables(rawPath.Trim());
        if (expandedPath.Contains('%') || expandedPath.Contains("$env:", StringComparison.OrdinalIgnoreCase))
        {
            error = "the tools path contains an unresolved environment-variable token; " +
                    "define the variable or provide an explicit path";
            return false;
        }

        try
        {
            normalizedPath = Path.GetFullPath(expandedPath);
            return true;
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or NotSupportedException)
        {
            error = $"the tools path is invalid: {ex.Message}";
            return false;
        }
    }
}
