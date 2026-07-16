using System.Text.RegularExpressions;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Compares version strings reported by tools and release tags without treating
/// every formatting difference as an available update.
/// </summary>
public static partial class VersionOrdering
{
    private sealed record ParsedVersion(
        IReadOnlyList<int> Components,
        bool IsPrerelease,
        IReadOnlyList<string> PrereleaseIdentifiers);

    /// <summary>
    /// Return a negative value when <paramref name="installed"/> is older,
    /// zero when equivalent, a positive value when newer, or <see langword="null"/>
    /// when either value does not contain a comparable dotted numeric version.
    /// </summary>
    public static int? TryCompare(string? installed, string? latest)
    {
        var installedVersion = TryParse(installed);
        var latestVersion = TryParse(latest);
        if (installedVersion is null || latestVersion is null)
            return null;

        var length = Math.Max(
            installedVersion.Components.Count,
            latestVersion.Components.Count);
        for (var index = 0; index < length; index++)
        {
            var installedPart = index < installedVersion.Components.Count
                ? installedVersion.Components[index]
                : 0;
            var latestPart = index < latestVersion.Components.Count
                ? latestVersion.Components[index]
                : 0;
            var componentComparison = installedPart.CompareTo(latestPart);
            if (componentComparison != 0)
                return componentComparison;
        }

        if (installedVersion.IsPrerelease != latestVersion.IsPrerelease)
            return installedVersion.IsPrerelease ? -1 : 1;
        if (!installedVersion.IsPrerelease)
            return 0;

        return ComparePrerelease(
            installedVersion.PrereleaseIdentifiers,
            latestVersion.PrereleaseIdentifiers);
    }

    public static bool IsUpdateAvailable(string? installed, string? latest) =>
        TryCompare(installed, latest) is < 0;

    private static ParsedVersion? TryParse(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
            return null;

        var match = DottedVersionPattern().Match(raw.Trim());
        if (!match.Success)
            return null;

        var componentStrings = match.Groups["core"].Value.Split('.');
        var components = new List<int>(componentStrings.Length);
        foreach (var component in componentStrings)
        {
            if (!int.TryParse(component, out var value))
                return null;
            components.Add(value);
        }

        var suffix = match.Groups["pre"].Value.TrimStart('-');
        var identifiers = suffix.Length == 0
            ? []
            : suffix.Split('.', StringSplitOptions.RemoveEmptyEntries).ToList();
        var isPrerelease = identifiers.Count > 0 && IsPrereleaseLabel(identifiers[0]);
        return new ParsedVersion(components, isPrerelease, identifiers);
    }

    private static bool IsPrereleaseLabel(string label)
    {
        if (label.All(char.IsAsciiDigit))
            return true;
        var normalized = label.ToLowerInvariant();
        return normalized.StartsWith("alpha", StringComparison.Ordinal)
            || normalized.StartsWith("beta", StringComparison.Ordinal)
            || normalized.StartsWith("rc", StringComparison.Ordinal)
            || normalized.StartsWith("preview", StringComparison.Ordinal)
            || normalized.StartsWith("pre", StringComparison.Ordinal)
            || normalized.StartsWith("dev", StringComparison.Ordinal)
            || normalized.StartsWith("nightly", StringComparison.Ordinal);
    }

    private static int ComparePrerelease(
        IReadOnlyList<string> installed,
        IReadOnlyList<string> latest)
    {
        var length = Math.Max(installed.Count, latest.Count);
        for (var index = 0; index < length; index++)
        {
            if (index >= installed.Count) return -1;
            if (index >= latest.Count) return 1;

            var installedNumeric = int.TryParse(installed[index], out var installedNumber);
            var latestNumeric = int.TryParse(latest[index], out var latestNumber);
            int comparison;
            if (installedNumeric && latestNumeric)
                comparison = installedNumber.CompareTo(latestNumber);
            else if (installedNumeric != latestNumeric)
                comparison = installedNumeric ? -1 : 1;
            else
                comparison = string.Compare(installed[index], latest[index], StringComparison.OrdinalIgnoreCase);
            if (comparison != 0)
                return comparison;
        }
        return 0;
    }

    [GeneratedRegex(
        @"(?<![A-Za-z0-9])v?(?<core>\d+(?:\.\d+){1,3})(?<pre>-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
        RegexOptions.CultureInvariant)]
    private static partial Regex DottedVersionPattern();
}
