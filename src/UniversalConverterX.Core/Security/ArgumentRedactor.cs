using System.Text.RegularExpressions;

namespace UniversalConverterX.Core.Security;

/// <summary>
/// Removes credentials and personal paths from an argument vector before it is
/// written to job provenance, history, or a diagnostics bundle.
///
/// Provenance is only useful if a user can attach it to a bug report, and the
/// argument vectors that reach sidecars routinely carry cookies, tokens, signed
/// URLs, and the operator's home directory. Redaction happens once, here,
/// rather than at each of the places that persist or export a job.
/// </summary>
public static partial class ArgumentRedactor
{
    /// <summary>Replacement written in place of a removed value.</summary>
    public const string Placeholder = "<redacted>";

    /// <summary>
    /// Flags whose *value* is a secret. Matched case-insensitively, in both the
    /// "--flag value" and "--flag=value" forms.
    /// </summary>
    private static readonly string[] SecretFlags =
    [
        "--cookie",
        "--cookies",
        "--cookies-from-browser",
        "--api-key",
        "--apikey",
        "--auth",
        "--authorization",
        "--bearer",
        "--client-secret",
        "--hf-token",
        "--key",
        "--password",
        "--passphrase",
        "--secret",
        "--token",
        "--username",
        "--user",
    ];

    /// <summary>
    /// Redacts an argument vector: secret-flag values are removed entirely,
    /// URLs lose their credentials and query strings, and paths under the
    /// user's profile are rewritten relative to it.
    /// </summary>
    public static IReadOnlyList<string> Redact(IEnumerable<string>? args)
    {
        if (args is null)
        {
            return [];
        }

        var redacted = new List<string>();
        var secretValueExpected = false;

        foreach (var argument in args)
        {
            if (secretValueExpected)
            {
                redacted.Add(Placeholder);
                secretValueExpected = false;
                continue;
            }

            var flag = MatchSecretFlag(argument);
            if (flag is not null)
            {
                if (argument.Length > flag.Length && argument[flag.Length] == '=')
                {
                    redacted.Add($"{flag}={Placeholder}");
                }
                else
                {
                    redacted.Add(argument);
                    secretValueExpected = true;
                }
                continue;
            }

            redacted.Add(RedactValue(argument));
        }

        return redacted;
    }

    /// <summary>
    /// Redacts a single free-form value: URL credentials and query strings, and
    /// the user's profile directory.
    /// </summary>
    public static string RedactValue(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value ?? string.Empty;
        }

        var result = value;

        if (Uri.TryCreate(result, UriKind.Absolute, out var uri)
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
        {
            // A signed URL carries its authorization in the query string, and
            // userinfo carries it outright. Keep only scheme, host, and path so
            // the record still says what was fetched.
            var builder = new UriBuilder(uri)
            {
                UserName = string.Empty,
                Password = string.Empty,
                Query = string.IsNullOrEmpty(uri.Query) ? string.Empty : Placeholder,
                Fragment = string.Empty,
            };
            result = builder.Uri.ToString();
            if (!string.IsNullOrEmpty(uri.Query))
            {
                result = result.Replace(
                    "?" + Uri.EscapeDataString(Placeholder),
                    "?" + Placeholder,
                    StringComparison.Ordinal);
            }
            return result;
        }

        return RedactUserProfile(result);
    }

    /// <summary>
    /// Rewrites a path under the current user's profile as <c>~\rest</c> so the
    /// record keeps its shape without naming the operator.
    /// </summary>
    public static string RedactUserProfile(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value;
        }

        string profile;
        try
        {
            profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        }
        catch
        {
            return value;
        }

        if (string.IsNullOrEmpty(profile))
        {
            return value;
        }

        profile = Path.TrimEndingDirectorySeparator(profile);
        if (value.StartsWith(profile, StringComparison.OrdinalIgnoreCase))
        {
            return "~" + value[profile.Length..];
        }

        return value;
    }

    /// <summary>Redacts a free-form message such as an engine error string.</summary>
    public static string RedactMessage(string? message)
    {
        if (string.IsNullOrEmpty(message))
        {
            return message ?? string.Empty;
        }

        var scrubbed = InlineSecretPattern().Replace(message, $"$1{Placeholder}");
        return RedactUserProfile(scrubbed);
    }

    private static string? MatchSecretFlag(string argument)
    {
        foreach (var flag in SecretFlags)
        {
            if (argument.Equals(flag, StringComparison.OrdinalIgnoreCase))
            {
                return flag;
            }
            if (argument.Length > flag.Length
                && argument[flag.Length] == '='
                && argument.StartsWith(flag, StringComparison.OrdinalIgnoreCase))
            {
                return flag;
            }
        }

        return null;
    }

    // "token=abc123", "Authorization: Bearer xyz", "api_key = ..." inside prose.
    // The optional scheme word is part of the *prefix*, not the secret: without
    // it, "Authorization: Bearer eyJ..." redacts only the word "Bearer" and
    // leaves the token in the record.
    [GeneratedRegex(
        @"((?:token|secret|password|passwd|api[_-]?key|authorization|bearer)\s*[:=]\s*(?:bearer\s+|token\s+|basic\s+)?)\S+",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex InlineSecretPattern();
}
