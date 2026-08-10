using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Windows.ApplicationModel.Resources;
using UniversalConverterX.Core.Localization;

namespace UniversalConverterX.UI.Services;

public static class AppLocalizer
{
    private static readonly Lazy<ResourceLoader> Loader = new(() => new ResourceLoader());

    /// <summary>
    /// Resolves a user-visible English fallback without allowing imperative UI
    /// copy to bypass the resource map. The stable key is derived from the
    /// format string so moving a call does not rename its resource.
    /// </summary>
    public static string Get(string englishFallback) =>
        Get(KeyFor(englishFallback), englishFallback);

    public static string Get(string key, string englishFallback)
    {
        var value = englishFallback;
        try
        {
            value = Loader.Value.GetString(key);
            if (string.IsNullOrWhiteSpace(value))
                value = englishFallback;
        }
        catch
        {
            // Resource loading must never take down a conversion surface.
            value = englishFallback;
        }

        return IsPseudoLocale ? PseudoLocalization.Transform(value) : value;
    }

    public static string Format(FormattableString englishFallback)
    {
        var format = Get(englishFallback.Format);
        try
        {
            return string.Format(
                CultureInfo.CurrentCulture,
                format,
                englishFallback.GetArguments());
        }
        catch (FormatException)
        {
            // A malformed third-party translation should still leave the
            // operation readable in the UI.
            return englishFallback.ToString(CultureInfo.CurrentCulture);
        }
    }

    public static string Format(
        string key,
        string englishFormat,
        params object?[] arguments) =>
        string.Format(CultureInfo.CurrentCulture, Get(key, englishFormat), arguments);

    public static string KeyFor(string englishFormat)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(englishFormat));
        return $"Code_{Convert.ToHexString(hash.AsSpan(0, 10))}";
    }

    public static bool IsPseudoLocale =>
        string.Equals(Environment.GetEnvironmentVariable("UCX_PSEUDO_LOCALE"), "1", StringComparison.OrdinalIgnoreCase)
        || string.Equals(Environment.GetEnvironmentVariable("UCX_PSEUDO_LOCALE"), "true", StringComparison.OrdinalIgnoreCase)
        || string.Equals(
            Windows.Globalization.ApplicationLanguages.PrimaryLanguageOverride,
            "qps-ploc",
            StringComparison.OrdinalIgnoreCase);
}
