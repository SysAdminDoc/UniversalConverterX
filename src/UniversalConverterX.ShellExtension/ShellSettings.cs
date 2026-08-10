using UniversalConverterX.Core.Configuration;

namespace UniversalConverterX.ShellExtension;

/// <summary>
/// Small, fail-closed projection of the shared settings document for Explorer.
/// Explorer loads the COM server out of process, so it cannot use the UI's DI
/// container; reading the same Core document keeps shell preferences observable
/// without adding a second settings schema.
/// </summary>
internal static class ShellSettings
{
    public static ConverterXOptions Load()
    {
        try
        {
            return ConverterXOptions.Load();
        }
        catch
        {
            return new ConverterXOptions();
        }
    }

    public static bool IsQuickPreset(string outputExtension, ConverterXOptions options) =>
        (options.QuickConvertPresets ?? [])
            .Any(extension => extension.Equals(
                outputExtension,
                StringComparison.OrdinalIgnoreCase));
}
