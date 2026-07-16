using Microsoft.Windows.ApplicationModel.Resources;

namespace UniversalConverterX.UI.Services;

public static class AppLocalizer
{
    private static readonly Lazy<ResourceLoader> Loader = new(() => new ResourceLoader());

    public static string Get(string key, string englishFallback)
    {
        try
        {
            var value = Loader.Value.GetString(key);
            return string.IsNullOrWhiteSpace(value) ? englishFallback : value;
        }
        catch
        {
            return englishFallback;
        }
    }
}
