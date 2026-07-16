using System.Globalization;

namespace UniversalConverterX.Core.Localization;

/// <summary>
/// Keeps Core independent of WinUI while allowing the host to resolve
/// user-visible messages from its compiled resource map.
/// </summary>
public static class LocalizedText
{
    private static Func<string, string, string>? _resolver;

    public static void Configure(Func<string, string, string>? resolver) =>
        Volatile.Write(ref _resolver, resolver);

    public static string Get(string key, string englishFallback)
    {
        var resolver = Volatile.Read(ref _resolver);
        if (resolver is null)
            return englishFallback;
        try
        {
            return resolver(key, englishFallback);
        }
        catch
        {
            return englishFallback;
        }
    }

    public static string Format(string key, string englishFallback, params object?[] arguments) =>
        string.Format(CultureInfo.CurrentCulture, Get(key, englishFallback), arguments);
}
