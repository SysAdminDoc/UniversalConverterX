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

    /// <summary>
    /// Windows reserved device names. A file whose stem (the part before the
    /// first dot) matches one of these — with or without an extension, e.g.
    /// "CON" or "NUL.txt" — cannot be created on Windows and the write fails.
    /// </summary>
    private static readonly HashSet<string> ReservedDeviceNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    };

    public static string SanitizeFileNameComponent(string value, string fallback = "output")
    {
        if (string.IsNullOrWhiteSpace(value))
            return fallback;

        var invalid = Path.GetInvalidFileNameChars();
        var safe = string.Concat(value.Trim().Select(c =>
            invalid.Contains(c) || c is '/' or '\\' or ':' or '\0' ? '_' : c));

        // Windows silently strips trailing dots and spaces, which can turn a
        // benign stem into a reserved name ("CON." → "CON") or empty it out.
        safe = safe.Trim().TrimEnd('.', ' ').Trim();
        if (safe.Length == 0 || safe is "." or "..")
            return fallback;

        // Neutralize Windows reserved device names so the downstream file
        // create doesn't fail. Untrusted metadata (EXIF/ID3/probe titles) can
        // resolve a stem to CON/NUL/PRN/COM1…; prefix it to make it writable.
        var stem = safe.Split('.', 2)[0];
        if (ReservedDeviceNames.Contains(stem))
            safe = "_" + safe;

        return safe;
    }
}
