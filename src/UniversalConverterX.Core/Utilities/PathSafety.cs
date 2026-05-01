namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Small path and filename guards shared by CLI, presets, and UI services.
/// </summary>
public static class PathSafety
{
    public const string DirectoryOutputSentinel = "__dir__";

    /// <summary>
    /// Normalizes an output extension without allowing path separators or
    /// platform-invalid filename characters to become part of generated paths.
    /// Multi-part extensions such as "tar.gz" are preserved.
    /// </summary>
    public static bool TryNormalizeExtension(
        string? extension,
        out string normalized,
        bool allowDirectorySentinel = false)
    {
        normalized = string.Empty;
        if (string.IsNullOrWhiteSpace(extension))
            return false;

        var value = extension.Trim().TrimStart('.');
        if (allowDirectorySentinel &&
            string.Equals(value, DirectoryOutputSentinel, StringComparison.OrdinalIgnoreCase))
        {
            normalized = DirectoryOutputSentinel;
            return true;
        }

        if (string.IsNullOrWhiteSpace(value))
            return false;
        if (value is "." or "..")
            return false;
        if (value.Any(char.IsWhiteSpace))
            return false;
        if (value.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            return false;
        if (value.IndexOfAny(['/', '\\', ':', '\0']) >= 0)
            return false;

        normalized = value.ToLowerInvariant();
        return true;
    }

    public static string NormalizeExtensionOrThrow(
        string? extension,
        string paramName = "extension",
        bool allowDirectorySentinel = false)
    {
        if (TryNormalizeExtension(extension, out var normalized, allowDirectorySentinel))
            return normalized;

        throw new ArgumentException(
            "Output extension must be a filename-safe value such as 'mp4', 'png', or 'tar.gz'.",
            paramName);
    }

    public static string SanitizeFileNameComponent(string value, string fallback = "output")
    {
        if (string.IsNullOrWhiteSpace(value))
            return fallback;

        var invalid = Path.GetInvalidFileNameChars();
        var safe = string.Concat(value.Trim().Select(c =>
            invalid.Contains(c) || c is '/' or '\\' or ':' or '\0' ? '_' : c));
        safe = safe.Trim();
        return safe.Length == 0 || safe is "." or ".." ? fallback : safe;
    }
}
