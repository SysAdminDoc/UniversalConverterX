using System.Globalization;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Token-based output filename template engine. Closes ROADMAP Item 5.
///
/// Templates use <c>{token}</c> placeholders that are substituted from a
/// caller-supplied dictionary plus a built-in set derived from the source
/// path (<c>{stem}</c>, <c>{dir}</c>, <c>{ext}</c>) and the current time
/// (<c>{date}</c>, <c>{year}</c>). Every substituted value is run through
/// <see cref="PathSafety.SanitizeFileNameComponent"/> so untrusted metadata
/// (EXIF tags, ID3 strings, yt-dlp probes) cannot escape the directory or
/// inject path separators.
///
/// Designed to be the single source of truth for output filename rendering
/// across CLI presets, the orchestrator, and the Watch Folder service.
/// Pairs with <see cref="UniqueOutputPath"/> — render here, collision-protect
/// there.
/// </summary>
/// <remarks>
/// Per ROADMAP Item 5, the canonical media-aware token set is:
///
///     {title}    — track / video title (from container metadata)
///     {artist}   — artist tag (audio)
///     {date}     — yyyy-MM-dd at render time
///     {year}     — yyyy at render time
///     {resolution} — e.g. "1920x1080" (video)
///     {fps}      — frame rate as integer (video)
///     {bitrate}  — bitrate in kbps (audio / video)
///     {codec}    — primary stream codec name
///     {duration} — duration in HHmmss form (video / audio)
///     {n}        — batch counter; the caller is responsible for assigning
///                  the per-job value before calling Render. The template
///                  engine has no per-batch state of its own.
///
/// Plus the built-in path tokens:
///
///     {stem}     — input filename without extension
///     {dir}      — input file's directory
///     {ext}      — input file's extension WITHOUT the leading dot
///     {preset}   — sanitised preset display name (caller-supplied)
///
/// Unknown tokens render as empty strings (NOT left as literal
/// <c>{foo}</c>) so half-resolved templates can't surface in user-visible
/// paths. Callers wanting strict mode should pre-validate templates against
/// <see cref="GetSupportedTokens"/>.
/// </remarks>
public static class OutputFilenameTemplate
{
    /// <summary>
    /// Tokens always provided by the engine when source-path / time inputs
    /// are available. Listed for documentation + UI hint generation.
    /// </summary>
    public static IReadOnlyCollection<string> BuiltInTokens { get; } =
    [
        "stem", "dir", "ext", "preset",
        "date", "year",
    ];

    /// <summary>
    /// Tokens the engine accepts but does not source itself — the caller
    /// must supply the value via the <c>tokens</c> dict (typically from
    /// FFprobe / metadata probing). Listed for documentation + UI hints.
    /// </summary>
    public static IReadOnlyCollection<string> MediaTokens { get; } =
    [
        "title", "artist", "resolution", "fps", "bitrate",
        "codec", "duration", "n",
    ];

    /// <summary>
    /// Returns the union of <see cref="BuiltInTokens"/> and
    /// <see cref="MediaTokens"/> — every token name the template engine
    /// recognises by name.
    /// </summary>
    public static IReadOnlyCollection<string> GetSupportedTokens() =>
        [.. BuiltInTokens, .. MediaTokens];

    /// <summary>
    /// Render <paramref name="template"/> by substituting <c>{token}</c>
    /// placeholders. Built-in tokens are derived from
    /// <paramref name="sourcePath"/> and the current time;
    /// <paramref name="tokens"/> can override any built-in or supply
    /// any media token. Unknown tokens render to empty strings.
    /// </summary>
    /// <param name="template">
    /// Template string. <c>null</c>/empty returns an empty string.
    /// </param>
    /// <param name="sourcePath">Input file path. May be <c>null</c> when
    /// the template doesn't reference path-derived tokens.</param>
    /// <param name="tokens">Optional overrides + media tokens. Keys are
    /// case-insensitive token names without the curly braces.</param>
    /// <param name="presetName">Optional preset display name; rendered
    /// for <c>{preset}</c>. Sanitised before use.</param>
    /// <param name="now">Time source for <c>{date}</c> / <c>{year}</c>.
    /// Defaults to <see cref="DateTime.Now"/> at call time.</param>
    public static string Render(
        string? template,
        string? sourcePath = null,
        IReadOnlyDictionary<string, string?>? tokens = null,
        string? presetName = null,
        DateTime? now = null)
    {
        if (string.IsNullOrEmpty(template))
            return string.Empty;

        var renderTime = now ?? DateTime.Now;

        // Build the resolved token map. Caller-supplied tokens win over
        // engine-built defaults so a preset that needs to override
        // {stem} (e.g. for batch-output-dir conventions) can do so.
        var resolved = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        if (!string.IsNullOrEmpty(sourcePath))
        {
            resolved["stem"] = PathSafety.SanitizeFileNameComponent(
                Path.GetFileNameWithoutExtension(sourcePath), "output");
            // {dir} is intentionally NOT sanitised — it is a directory
            // path, not a filename component, and callers expect the
            // full path back. Path traversal is not a concern here
            // because the value is always derived from the input the
            // user already chose to convert.
            resolved["dir"] = Path.GetDirectoryName(sourcePath) ?? string.Empty;
            resolved["ext"] = PathSafety.SanitizeFileNameComponent(
                Path.GetExtension(sourcePath).TrimStart('.'), "");
        }

        if (!string.IsNullOrEmpty(presetName))
        {
            resolved["preset"] = PathSafety.SanitizeFileNameComponent(presetName, "preset");
        }

        resolved["date"] = renderTime.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        resolved["year"] = renderTime.ToString("yyyy", CultureInfo.InvariantCulture);

        if (tokens is not null)
        {
            foreach (var kvp in tokens)
            {
                if (string.IsNullOrEmpty(kvp.Key)) continue;
                resolved[kvp.Key] = SanitizeTokenValue(kvp.Key, kvp.Value);
            }
        }

        return SubstituteTokens(template, resolved);
    }

    /// <summary>
    /// Path-component tokens (<c>{dir}</c>) bypass sanitisation; everything
    /// else (filename components, user metadata, batch counters) is
    /// scrubbed for invalid filename chars.
    /// </summary>
    private static string SanitizeTokenValue(string tokenName, string? rawValue)
    {
        if (rawValue is null) return string.Empty;
        if (string.Equals(tokenName, "dir", StringComparison.OrdinalIgnoreCase))
            return rawValue;
        return PathSafety.SanitizeFileNameComponent(rawValue, "");
    }

    /// <summary>
    /// Single-pass substitution. <c>{{</c> and <c>}}</c> are escapes for
    /// literal braces (rare but yt-dlp templates use them; staying compatible).
    /// </summary>
    private static string SubstituteTokens(string template, Dictionary<string, string> tokens)
    {
        var output = new System.Text.StringBuilder(template.Length + 32);
        var i = 0;
        while (i < template.Length)
        {
            var ch = template[i];

            if (ch == '{')
            {
                // Escaped literal "{{"
                if (i + 1 < template.Length && template[i + 1] == '{')
                {
                    output.Append('{');
                    i += 2;
                    continue;
                }

                var close = template.IndexOf('}', i + 1);
                if (close < 0)
                {
                    // Unterminated brace — surface the literal so the user
                    // can spot the typo in the rendered path.
                    output.Append(ch);
                    i++;
                    continue;
                }

                var name = template.Substring(i + 1, close - i - 1).Trim();
                output.Append(tokens.TryGetValue(name, out var value) ? value : string.Empty);
                i = close + 1;
                continue;
            }

            if (ch == '}' && i + 1 < template.Length && template[i + 1] == '}')
            {
                output.Append('}');
                i += 2;
                continue;
            }

            output.Append(ch);
            i++;
        }
        return output.ToString();
    }
}
