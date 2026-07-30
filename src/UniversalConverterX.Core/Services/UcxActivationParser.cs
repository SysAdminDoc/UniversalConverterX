using System.Text;
using System.Text.RegularExpressions;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Services;

public static partial class UcxActivationParser
{
    private const int MaximumPathCount = 512;

    public static UcxActivationRequest ParseCommandLine(
        IEnumerable<string> arguments)
    {
        ArgumentNullException.ThrowIfNull(arguments);

        var tokens = arguments.ToArray();
        var route = "home";
        var paths = new List<string>();
        var positionalOnly = false;

        for (var index = 0; index < tokens.Length; index++)
        {
            var token = tokens[index]?.Trim() ?? string.Empty;
            if (token.Length == 0)
                continue;

            if (index == 0 && LooksLikeExecutable(token))
                continue;

            if (!positionalOnly && token == "--")
            {
                positionalOnly = true;
                continue;
            }

            if (!positionalOnly && token.Equals(
                    "--route", StringComparison.OrdinalIgnoreCase))
            {
                if (index + 1 < tokens.Length)
                    route = NormalizeRoute(tokens[++index]);
                continue;
            }

            if (!positionalOnly && token.StartsWith(
                    "--route=", StringComparison.OrdinalIgnoreCase))
            {
                route = NormalizeRoute(token[8..]);
                continue;
            }

            if (!positionalOnly && token.StartsWith('-'))
                continue;

            AddPath(paths, token);
        }

        if (paths.Count > 0 && route == "home")
            route = "converter";

        return new UcxActivationRequest(
            route,
            paths.AsReadOnly(),
            UcxActivationSource.Launch);
    }

    public static UcxActivationRequest ParseCommandLine(string? commandLine) =>
        ParseCommandLine(SplitCommandLine(commandLine ?? string.Empty));

    public static UcxActivationRequest ParseFiles(IEnumerable<string> paths)
    {
        ArgumentNullException.ThrowIfNull(paths);
        var normalized = new List<string>();
        foreach (var path in paths)
            AddPath(normalized, path);
        return new UcxActivationRequest(
            normalized.Count > 0 ? "converter" : "home",
            normalized.AsReadOnly(),
            UcxActivationSource.File);
    }

    public static UcxActivationRequest ParseProtocol(Uri uri)
    {
        ArgumentNullException.ThrowIfNull(uri);
        if (!uri.IsAbsoluteUri
            || !uri.Scheme.Equals("ucx", StringComparison.OrdinalIgnoreCase))
        {
            return Home(UcxActivationSource.Protocol);
        }

        var raw = uri.OriginalString["ucx:".Length..];
        var queryIndex = raw.IndexOf('?');
        var routePart = queryIndex >= 0 ? raw[..queryIndex] : raw;
        var query = queryIndex >= 0 ? raw[(queryIndex + 1)..] : string.Empty;
        var fragmentIndex = query.IndexOf('#');
        if (fragmentIndex >= 0)
            query = query[..fragmentIndex];

        string route;
        if (!string.IsNullOrWhiteSpace(uri.Host))
            route = NormalizeRoute(uri.Host);
        else
            route = NormalizeRoute(routePart.TrimStart('/'));

        var paths = new List<string>();
        foreach (var pair in ParsePairs(query))
        {
            if (pair.Key.Equals("route", StringComparison.OrdinalIgnoreCase))
                route = NormalizeRoute(pair.Value);
            else if (pair.Key.Equals("path", StringComparison.OrdinalIgnoreCase)
                     || pair.Key.Equals("file", StringComparison.OrdinalIgnoreCase))
                AddPath(paths, pair.Value);
        }

        if (route == "convert")
            route = "converter";
        if (paths.Count > 0 && route == "home")
            route = "converter";

        return new UcxActivationRequest(
            route,
            paths.AsReadOnly(),
            UcxActivationSource.Protocol);
    }

    public static UcxActivationRequest ParseToast(string? arguments)
    {
        var route = "history";
        var paths = new List<string>();
        foreach (var pair in ParsePairs(arguments ?? string.Empty))
        {
            if (pair.Key.Equals("route", StringComparison.OrdinalIgnoreCase))
                route = NormalizeRoute(pair.Value);
            else if (pair.Key.Equals("path", StringComparison.OrdinalIgnoreCase)
                     || pair.Key.Equals("file", StringComparison.OrdinalIgnoreCase))
                AddPath(paths, pair.Value);
        }

        if (paths.Count > 0 && route == "home")
            route = "converter";
        return new UcxActivationRequest(
            route,
            paths.AsReadOnly(),
            UcxActivationSource.AppNotification);
    }

    public static UcxActivationRequest Startup() =>
        Home(UcxActivationSource.StartupTask);

    private static UcxActivationRequest Home(UcxActivationSource source) =>
        new("home", Array.Empty<string>(), source);

    private static bool LooksLikeExecutable(string value) =>
        value.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
        && Path.IsPathFullyQualified(value);

    private static string NormalizeRoute(string? route)
    {
        var candidate = (route ?? string.Empty).Trim().Trim('/');
        return RoutePattern().IsMatch(candidate)
            ? candidate.ToLowerInvariant()
            : "home";
    }

    private static void AddPath(ICollection<string> paths, string? value)
    {
        if (paths.Count >= MaximumPathCount
            || string.IsNullOrWhiteSpace(value)
            || value.IndexOf('\0') >= 0)
        {
            return;
        }

        try
        {
            if (!Path.IsPathFullyQualified(value))
                return;
            var normalized = Path.GetFullPath(value);
            if (normalized.Length > 32767
                || paths.Any(path => path.Equals(
                    normalized,
                    StringComparison.OrdinalIgnoreCase)))
            {
                return;
            }
            paths.Add(normalized);
        }
        catch (Exception exception) when (
            exception is ArgumentException
            or NotSupportedException
            or PathTooLongException)
        {
            // Ignore malformed external activation data.
        }
    }

    private static IEnumerable<KeyValuePair<string, string>> ParsePairs(
        string value)
    {
        var query = value.TrimStart('?');
        foreach (var segment in query.Split(
                     '&', StringSplitOptions.RemoveEmptyEntries))
        {
            var equals = segment.IndexOf('=');
            var rawKey = equals >= 0 ? segment[..equals] : segment;
            var rawValue = equals >= 0 ? segment[(equals + 1)..] : string.Empty;
            string key;
            string decoded;
            try
            {
                key = Uri.UnescapeDataString(rawKey.Replace('+', ' '));
                decoded = Uri.UnescapeDataString(rawValue.Replace('+', ' '));
            }
            catch (UriFormatException)
            {
                continue;
            }
            yield return new KeyValuePair<string, string>(key, decoded);
        }
    }

    private static IEnumerable<string> SplitCommandLine(string commandLine)
    {
        var arguments = new List<string>();
        var index = 0;
        while (index < commandLine.Length)
        {
            while (index < commandLine.Length && char.IsWhiteSpace(commandLine[index]))
                index++;
            if (index >= commandLine.Length)
                break;

            var value = new StringBuilder();
            var quoted = false;
            while (index < commandLine.Length)
            {
                if (!quoted && char.IsWhiteSpace(commandLine[index]))
                    break;

                if (commandLine[index] == '\\')
                {
                    var slashStart = index;
                    while (index < commandLine.Length && commandLine[index] == '\\')
                        index++;
                    var slashCount = index - slashStart;
                    if (index < commandLine.Length && commandLine[index] == '"')
                    {
                        value.Append('\\', slashCount / 2);
                        if (slashCount % 2 == 0)
                            quoted = !quoted;
                        else
                            value.Append('"');
                        index++;
                    }
                    else
                    {
                        value.Append('\\', slashCount);
                    }
                    continue;
                }

                if (commandLine[index] == '"')
                {
                    quoted = !quoted;
                    index++;
                    continue;
                }

                value.Append(commandLine[index]);
                index++;
            }
            arguments.Add(value.ToString());
        }
        return arguments;
    }

    [GeneratedRegex(
        @"^[a-z0-9][a-z0-9-]{0,63}(?::[a-z0-9][a-z0-9._-]{0,63})?$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex RoutePattern();
}
